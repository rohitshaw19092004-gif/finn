from finn import snapshot
from finn.intel import research


def test_viewer_links_are_unwrapped_to_the_pdf_itself():
    v = ("https://www.marutisuzuki.com/pdf-viewer?pdf=%2Fcontent%2Fdam%2Farena-eds%2Fcorporate%2Fpdf%2F"
         "company-reports%2F2026-2027%2FTranscript_earnings_call_Maruti_Suzuki_Q2_FY_27.pdf")
    assert research.direct_pdf(v) == ("https://www.marutisuzuki.com/content/dam/arena-eds/corporate/pdf/"
                                      "company-reports/2026-2027/Transcript_earnings_call_Maruti_Suzuki_Q2_FY_27.pdf")
    plain = "https://example.com/call.pdf?download=1"
    assert research.direct_pdf(plain) == plain
    assert research.direct_pdf("https://example.com/page?x=1") == "https://example.com/page?x=1"


def test_handled_conditions_are_notes_and_keep_health_ok():
    snapshot._reset_report()
    snapshot.REPORT["sources"]["prices"]["X"] = "yahoo"
    snapshot.REPORT["sources"]["fundamentals"]["X"] = "live"
    snapshot.REPORT["sources"]["filings"]["X"] = "NSE"
    snapshot.note("BSE announcements API refused this runner; filings for this run come from NSE.")
    snapshot.REPORT["research"]["X"] = {"status": "partial", "limited_by": "sources"}
    r = snapshot.finish_report(["X"])
    assert r["health"] == "ok" and not r["warnings"] and len(r["notes"]) == 2
    snapshot.REPORT["research"]["Y"] = {"status": "partial", "limited_by": "model"}
    assert snapshot.finish_report(["X"])["health"] == "degraded"     # a model failure still counts
