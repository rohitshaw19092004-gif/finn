"""Evidence discipline + NSE path + dossier honesty. Real captured data, fake model (no network)."""
import json
from pathlib import Path

import pytest

from conftest import FABRICATED
from finn import llm
from finn.intel import classify, research
from finn.intel import transcripts as tx
from finn.sources import bse, nse, screener

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
FIX = Path(__file__).parent / "fixtures"


def _docs(symbol):
    cap = json.loads((RAW / "screener.json").read_text())
    out = {}
    for l in screener.transcript_links(cap[symbol], n=5):
        p = RAW / "transcripts" / l["file"].replace(".pdf", ".txt")
        out[l["period"]] = p.read_text().split("\f")
    return out


# ---------------------------------------------------------------- quote verification
def test_real_quotes_verify_and_fabricated_ones_do_not():
    idx = tx.TranscriptIndex(_docs("CLEAN"))
    seed = json.loads((RAW / "llm_seed" / "CLEAN.json").read_text())
    ok, bad = tx.verify_guidance([dict(g) for g in seed["guidance"]], idx)
    assert len(ok) == len(seed["guidance"]) and not bad
    q = seed["guidance"][0]["quote"]
    words = q.split()
    assert idx.find(" ".join(words[:6]) + " ... " + " ".join(words[-6:]))["status"] == "verbatim"   # ellipsis
    assert idx.find(FABRICATED)["status"] == "not_found"
    assert idx.find("we expect growth")["status"] == "not_found"                                   # too short
    altered = q.replace("sequential", "double-digit")
    assert idx.find(altered)["status"] in ("near", "not_found")      # never 'verbatim' once a word is changed


def test_quote_said_on_another_call_is_reattributed():
    idx = tx.TranscriptIndex(_docs("CLEAN"))
    g = json.loads((RAW / "llm_seed" / "CLEAN.json").read_text())["guidance"][0]
    wrong = dict(g, said_in="Aug 2026")
    ok, _ = tx.verify_guidance([wrong], idx)
    assert ok[0]["said_in"] == g["said_in"]


def test_promises_must_point_at_verified_guidance():
    guidance = [{"said_in": "Nov 2025", "metric": "revenue growth", "statement": "s", "horizon": "FY26",
                 "quote": "q0", "quote_check": "verbatim"},
                {"said_in": "Feb 2026", "metric": "capex", "statement": "s", "horizon": "FY27", "quote": "q1"}]
    quarters = {"cols": ["Sep 2025", "Dec 2025"], "rows": {"Sales": [245, 220], "OPM %": [31, 36]}}
    out = tx.validate_promises({"promises": [
        {"ref": 0, "said_in": "?", "metric": "revenue growth", "promise": "grow", "outcome": "fell",
         "evidence": "Sales ₹245 Cr (Sep-25) → ₹220 Cr (Dec-25)", "verdict": "missed"},
        {"ref": 7, "said_in": "Mar 2026", "metric": "other", "promise": "made up", "outcome": "x", "evidence": "1",
         "verdict": "delivered"},
        {"ref": 1, "said_in": "Feb 2026", "metric": "capex", "promise": "c", "outcome": "?", "evidence": "",
         "verdict": "delivered"},
        {"ref": 0, "said_in": "Nov 2025", "metric": "revenue growth", "promise": "g", "outcome": "o",
         "evidence": "Sales up 37% to ₹999 Cr", "verdict": "delivered"}]}, guidance, quarters)
    p = out["promises"]
    assert len(p) == 3 and len(out["rejected"]) == 1                      # the invented promise is gone
    assert p[0]["quote"] == "q0" and p[0]["said_in"] == "Nov 2025" and p[0]["evidence_check"] == "traced"
    assert p[1]["verdict"] == "unknown" and "without citing figures" in p[1]["verdict_note"]
    assert p[2]["evidence_check"] == "untraced"                           # 37% / ₹999 Cr appear nowhere


# ---------------------------------------------------------------- NSE path
def test_nse_record_normalises_and_points_at_nse_archive(monkeypatch):
    rows = json.loads((FIX / "nse_HDFCBANK.json").read_text())
    f = nse.normalise(rows[1], "HDFCBANK")
    assert f["ts"] == "2026-11-06T15:21:56" and f["date"] == "2026-11-06"
    assert f["size"] == int(673.49 * 1024)
    assert f["url"].startswith("https://nsearchives.nseindia.com/corporate/")
    assert f["attachment"] == "HDFCBANK3_06112026152141_SE_Intimation-Srivatsan.pdf"
    asked = []
    monkeypatch.setattr(nse.http, "get", lambda url, **kw: asked.append(url) or b"%PDF-1.4")
    nse.document(f["attachment"])
    assert asked == ["https://nsearchives.nseindia.com/corporate/HDFCBANK3_06112026152141_SE_Intimation-Srivatsan.pdf"]
    assert nse.parse_ts({"an_dt": "06-Nov-2026 15:21:56"}) == "2026-11-06T15:21:56"


def test_nse_categories_classify():
    rows = json.loads((FIX / "nse_HDFCBANK.json").read_text())
    fs = [nse.normalise(r, "HDFCBANK") for r in rows]
    classify.classify_batch(fs)
    assert fs[1]["category"] == "management_change"
    assert fs[0]["category"] in ("postal_ballot", "agm_egm", "unclassified")
    res = nse.normalise({"desc": "Financial Result Updates", "attchmntText": "Financial results for the quarter ended September 30, 2026",
                         "sort_date": "2026-10-20 17:00:00", "seq_id": "1"}, "INFY")
    classify.classify_batch([res])
    assert res["category"] == "results"


def test_nse_filing_document_is_fetched_from_nse_not_bse(monkeypatch, tmp_path):
    from finn import snapshot
    from finn.sources import docs
    snapshot._reset_report()
    monkeypatch.setattr(docs, "TEXT_CACHE", tmp_path)
    monkeypatch.setattr(snapshot.docs, "pdf_text", lambda b: ["page one text"])
    hits = []
    monkeypatch.setattr(snapshot.nse, "document", lambda u: hits.append(("NSE", u)) or b"%PDF")
    monkeypatch.setattr(snapshot.bse, "document", lambda a: hits.append(("BSE", a)) or b"%PDF")
    f = nse.normalise(json.loads((FIX / "nse_HDFCBANK.json").read_text())[1], "HDFCBANK")
    assert snapshot.doc_text(f) == "page one text"
    assert snapshot.doc_text(f) == "page one text"                      # memoised: one fetch per run
    assert hits == [("NSE", f["url"])] and snapshot.DOCS["fetched from NSE"] == 1


def test_nse_filing_is_bridged_to_its_bse_twin_and_keeps_people():
    from finn import snapshot
    cap = json.loads((RAW / "bse_announcements.json").read_text())
    b = next(r for r in cap["HDFCBANK"] if r["ATTACHMENTNAME"] == "e5b2d06f-fea8-4dea-aa03-84674215a0fd.pdf")
    twin = nse.normalise({"desc": "Change in Management", "seq_id": "42", "sort_date": "2026-10-27 08:04:10",
                          "attchmntText": "HDFC Bank Limited has informed the Exchange about Change in Managing "
                                          "Director and Chief Executive Officer of the Bank",
                          "attchmntFile": "https://nsearchives.nseindia.com/corporate/HDFCBANK_27102026080400_x.pdf"},
                         "HDFCBANK")
    other = nse.normalise({"desc": "Updates", "seq_id": "43", "sort_date": "2026-10-27 19:00:00",
                           "attchmntText": "Unrelated", "attchmntFile": "y.pdf"}, "HDFCBANK")
    n = snapshot.bridge_to_bse([twin, other])
    assert n == 1 and twin["seed_key"] == b["ATTACHMENTNAME"] and "seed_key" not in other
    # local BSE text is reused, so classification sees the real filing
    snapshot._reset_report()
    t = snapshot.doc_text(twin)
    assert t and snapshot.DOCS["repo text"] == 1


# ---------------------------------------------------------------- dossier honesty
def test_live_dossier_drops_fabricated_quotes_and_unevidenced_verdicts(fake_gemini):
    fake = fake_gemini()
    d = research.build("CLEAN")
    a = d["analysis"]
    assert a["status"] == "complete" and a["source"] == "live" and d["generated_by"]["prose"] == "llm"
    assert a["coverage"].startswith("5/5")
    assert all(g["quote"] != FABRICATED for g in d["guidance"]) and d["guidance"]
    assert all(g["quote_check"] in ("verbatim", "near") for g in d["guidance"])
    assert len(a["rejected"]) == 5 and all(r["reason"] == "quote not found in transcript" for r in a["rejected"])
    verdicts = [p["verdict"] for p in d["promises"]["promises"]]
    assert "unknown" in verdicts and len(d["promises"]["rejected"]) == 1
    assert d["bull_bear"]["untraced"] == ["Margins could fall to 4.2% next year"]
    assert "gemini-flash-lite-latest" in d["generated_by"]["models"]


def test_model_outage_falls_back_to_labelled_seed_not_fake_freshness(fake_gemini):
    fake_gemini(fail_all=True)
    d = research.build("CLEAN")
    a = d["analysis"]
    assert a["status"] == "seeded" and a["source"] == "seed"
    assert d["generated_by"]["prose"] == "seeded (build-time)"
    assert "build-time" in a["notes"][0] and "0/5" in a["notes"][0]
    assert all(t["status"] == "failed" for t in a["transcripts"])          # the outage is recorded, not hidden
    assert d["guidance"] and all(g.get("quote_check") for g in d["guidance"])


def test_partial_outage_without_seed_is_partial_and_names_the_gaps(fake_gemini, monkeypatch):
    fake_gemini(fail_periods={"Nov 2026", "Aug 2026"})
    monkeypatch.setattr(research, "_seed", lambda s: None)
    d = research.build("CLEAN")
    a = d["analysis"]
    assert a["status"] == "partial" and a["coverage"].startswith("3/5")
    assert any("Nov 2026 (failed)" in n for n in a["notes"])
    assert {t["period"] for t in a["transcripts"] if t["status"] == "failed"} == {"Nov 2026", "Aug 2026"}
    assert {g["said_in"] for g in d["guidance"]} <= {"May 2026", "Feb 2026", "Nov 2025"}


def test_budget_exhausted_without_seed_is_numbers_only_and_says_deferred(fake_gemini, monkeypatch):
    fake = fake_gemini(budget_min=0)
    monkeypatch.setattr(research, "_seed", lambda s: None)
    d = research.build("CLEAN")
    assert d["analysis"]["status"] == "deferred" and d["guidance"] == [] and d["promises"] is None
    assert "deferred" in d["analysis"]["notes"][0] and fake.calls == []
    assert d["snapshot"]["roce"] is not None                               # numbers are still there


def test_flash_outage_is_absorbed_by_lite_fallback(fake_gemini):
    fake = fake_gemini(fail_models={"gemini-flash-latest"})
    d = research.build("CLEAN")
    assert d["analysis"]["status"] == "complete"
    assert d["analysis"]["sections"]["promises"]["model"] == "gemini-flash-lite-latest"
    assert llm.usage_report()["models"]["gemini-flash-latest"]["errors"].get("http_503")


def test_full_offline_refresh_with_flaky_model_reports_honestly(fake_gemini, monkeypatch, tmp_path):
    from finn import snapshot
    fake_gemini(fail_periods={"Nov 2026"})
    monkeypatch.setattr(snapshot, "OUT", tmp_path)
    (tmp_path / "research").mkdir()
    meta = snapshot.build()
    run = meta["run"]
    assert run["health"] == "degraded" and run["warnings"]
    assert run["research"]["CLEAN"]["status"] in ("seeded", "complete", "partial")
    assert meta["llm"]["totals"]["failed"] >= 1
    people = json.loads((tmp_path / "people.json").read_text())
    assert all(p["name"] != "Imaginary Person" for p in people)            # names not in the filing are dropped
    feed = json.loads((tmp_path / "feed.json").read_text())
    assert all(f.get("summary_by") in (None, "seeded", "rule", "llm") for f in feed["filings"])
    blob = (tmp_path / "meta.json").read_text()
    assert "AIzaFAKE" not in blob


# ---------------------------------------------------------------- transcript layouts (RELIANCE/INFY/BHARTIARTL case)
def _clean_pages():
    return (RAW / "transcripts" / "01002668-d786-415d-9d3d-025cabcfec27.txt").read_text().split("\f")


def test_speakers_found_when_pdf_loses_line_breaks():
    import re as _re
    ex = tx.prefilter([p.replace("\n", " ") for p in _clean_pages()])
    assert len(ex) >= 10 and {"Siddharth Sikchi"} <= {e["speaker"] for e in ex}


def test_speaker_with_title_after_dash():
    import re as _re
    pages = [_re.sub(r"^(Siddharth Sikchi):", r"\1 – Executive Director:", p, flags=_re.M) for p in _clean_pages()]
    assert "Siddharth Sikchi" in {e["speaker"] for e in tx.prefilter(pages)}


def test_no_speaker_markers_falls_back_to_cue_sentences():
    import re as _re
    pages = [_re.sub(r"^(\s*[A-Z][A-Za-z.\- ]{2,40}):", r"\1", p, flags=_re.M) for p in _clean_pages()]
    ex = tx.prefilter(pages)
    assert len(ex) >= 3 and all(e["speaker"] == "unattributed" for e in ex)
