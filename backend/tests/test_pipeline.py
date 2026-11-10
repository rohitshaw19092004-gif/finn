"""Tests run against real captured payloads (data/raw) — no network, no model."""
import json
from pathlib import Path

import pytest

from finn.intel import classify, materiality, results
from finn.intel.fundamentals import dossier_numbers
from finn.intel.transcripts import prefilter
from finn.sources import bse
from finn.sources.screener import parse_company

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def screener():
    return json.loads((RAW / "screener.json").read_text())


@pytest.fixture(scope="module")
def filings():
    raw = json.loads((RAW / "bse_announcements.json").read_text())
    fs = [bse.normalise(r, s) for s, arr in raw.items() for r in arr]

    def doc(f):
        p = RAW / "filings" / ((f.get("attachment") or "x").replace(".pdf", ".txt"))
        return p.read_text() if p.exists() else None
    classify.classify_batch(fs, doc_text=doc)
    return fs


def by_att(fs, att):
    return next(f for f in fs if f.get("attachment") == att)


def test_screener_parser_matches_browser_capture(screener):
    for sym in ("NAVINFLUOR", "HDFCBANK"):
        o = parse_company((FIX / f"screener_{sym}.html").read_text(), sym)
        assert o["quarters"]["cols"] == screener[sym]["quarters"]["cols"]
        assert o["quarters"]["rows"] == screener[sym]["quarters"]["rows"]
        assert o["cf"]["rows"] == screener[sym]["cf"]["rows"]
        assert len(o["concalls"]) >= 5


def test_ceo_change_found_behind_opaque_title(filings):
    f = by_att(filings, "e5b2d06f-fea8-4dea-aa03-84674215a0fd.pdf")   # 'Disclosure under Regulation 30...'
    assert f["category"] == "management_change"
    assert f["signals"]["seniority"] == 3 and f["signals"]["direction"] == "succession"


def test_esop_issue_is_routine_not_a_capital_raise(filings):
    f = by_att(filings, "fda5e9e1-3aa9-4ccc-837a-d45817ef7360.pdf")   # BSE label: 'Issue of Securities'
    assert f["category"] == "unclassified" and f["kind"] == "esop"


def test_lodr_boilerplate_does_not_look_like_litigation(filings):
    f = by_att(filings, "cbad9087-72a3-4ba2-a5e9-dd6d9d405981.pdf")   # '...not debarred ... by any SEBI order'
    assert f["category"] == "management_change"


def test_hidden_contract_extension_is_surfaced(filings):
    f = by_att(filings, "eb20c4c1-0833-4524-90a2-0a2e2a8ea41b.pdf")   # Navin Fluorine $410M HFO contract
    assert f["category"] == "press_release" and f["kind"] == "contract"


def test_order_size_judged_relative_to_company(filings, screener):
    f = by_att(filings, "8269aea9-54c0-4a24-a615-6dda0ab8f054.pdf")   # L&T 'Significant' = ₹1,000–2,500 Cr
    assert f["signals"]["order_bucket"] == "significant"
    rev = screener["LT"]["pl"]["rows"]["Sales"][-1]
    add, why = materiality.order_relevance(f, rev)
    assert add < 0 and "routine for its size" in why


def test_rules_need_almost_no_model(filings):
    unresolved = [f for f in filings if f["class_method"] == "default"]
    assert len(unresolved) / len(filings) < 0.06


def test_lender_results_use_nii_not_ebitda(screener):
    card = results.quarter_card(screener["HDFCBANK"])
    labels = [m["label"] for m in card["metrics"]]
    assert card["lender"] and "NII" in labels and "EBITDA" not in labels


def test_results_card_math(screener):
    card = results.quarter_card(screener["NAVINFLUOR"])
    rev = {m["label"]: m for m in card["metrics"]}["Revenue"]
    assert rev["value"] == 1191 and rev["yago"] == 758 and rev["yoy"] == pytest.approx(57.1, abs=0.1)


def test_dossier_numbers_flag_merger_step_change(screener):
    d = dossier_numbers(screener["HDFCBANK"])
    assert any("step change" in n["text"] for n in d["trajectory"]["notes"])


def test_transcript_prefilter_keeps_management_only():
    t = (RAW / "transcripts" / "99e65c90-6bb0-4984-ac71-2a0f0eb4cc7f.txt").read_text()
    ex = prefilter([t])
    assert ex and {e["speaker"] for e in ex} == {"Amit Syngle"}
    assert sum(len(e["text"]) for e in ex) < len(t) * 0.25
