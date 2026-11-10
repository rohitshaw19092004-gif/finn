# FINN: write-up

## What I built

A mobile web app (PWA) with three tabs, one per layer, plus the plumbing behind it. Everything runs on real data:
18 NSE holdings plus 3 research names, BSE filings from 12 Oct to 9 Nov 2026, screener statements, and 10 concall
transcripts.

- **Brief (Push).** For the window you pick (24h, 3d, 7d or 2 weeks), FINN answers one question first: *how many
  things need me?* It shows at most five full cards; everything else becomes a one-liner or is filed away as routine.
  Over the two weeks to 9 Nov, 13 stories needed attention; about 120 other filings (investor-meet notices, call
  notices, ESOP allotments, newspaper ads) did not. Price and volume alerts are computed on the phone
  against thresholds you set: a fixed % move, or **σ-based**, meaning unusual *for that stock*. You can listen to the
  brief, and you can tick cards off to keep a zero-inbox.
  - *Management change:* the incoming person's career comes from the filing's own LODR annexure, and the network
    line tells you who worked with them. Example: Anup Bagchi at HDFC Bank. A contact ran retail-assets strategy at
    ICICI Bank while he was ED for retail. A weak-tie contact who worked under him at ICICI Pru Life is reachable
    through a warm intro from a close friend.
  - *Results:* Revenue, EBITDA, PBT and PAT, QoQ and YoY, with margins and quality flags. Lenders show NII instead
    of EBITDA.
  - *Material events* (NCLAT ruling, regulatory halt, contract extension): the best person to call and why.
- **Ask (Pull).** One input box that routes between a company, a person, a theme and "who knows X". Voice input
  works where the phone supports it. A company opens a dossier: snapshot, segment mix, latest quarter, **promised
  vs delivered** (every guidance item from the last five calls, with a verbatim quote and a verdict against the
  reported numbers), narrative vs numbers, trajectory, balance sheet, cash quality, bull/bear, and who to call.
  Example: Asian Paints holds its 18–20% margin band only if you count ₹290 Cr of other income; core margin was
  15.6% in September.
- **People (Network).** Lines into this month's leadership changes, natural reasons to reconnect (a dormant
  contact whose ex-employer is in the news), a portfolio coverage map with blind spots, an expertise map, and
  LinkedIn-export import.

## Key decisions and trade-offs

1. **Filtering is the product, so most of it is deterministic.** About 95% of filings are classified by BSE's own
   labels plus rules. Opaque titles get page 1 of the PDF read, and only around 5% reach the cheapest model. Reading
   the PDF is what surfaced a Navin Fluorine "Disclosure under Reg 30" that was really a 4-year extension of a $410M
   contract. It also caught a Bajaj Finance "Issue of Securities" that was routine ESOP plumbing.
2. **Materiality is relative.** Results are scored by their own surprise (profit swing, margin shock, quality flags),
   so in-line quarters drop to one-liners. An order is judged against the company's revenue: a "Significant" L&T
   order is noise. A management change is scored on the role of the named person, and a shareholder vote that only
   confirms an earlier appointment is demoted.
3. **Models read prose, code does arithmetic.** Every number is computed. Transcripts are pre-filtered to
   management answers with forward-looking cues (about 15% of the text) before the extract model sees them. The
   reasoning model only sees already-extracted facts and reported numbers. Calls are cached by content hash, so a
   re-run costs about zero tokens. Gemini Flash-Lite and Flash on the free tier cover everything.
4. **The network never leaves the device.** Matching (tenure overlaps, group membership, school and years,
   warm-intro paths, who-to-call) runs in the browser. Server and models only ever see public documents. That is
   the privacy story and the architecture at once.
5. **The demo works offline.** A static snapshot (refreshed daily by a GitHub Action) is served from GitHub Pages,
   so the app opens instantly on a phone. The research API (Render, free) only adds live Pull for tickers outside the
   snapshot.

## Architecture (detail in docs/architecture.md)

- **Pipelines:** yfinance prices (screener fallback). BSE announcements API (NSE fallback). screener statements
  and document links. Transcripts and filing PDFs via pypdf, immutable and cached forever. Filings are linked to
  people through annexure extraction, and to companies through an org registry of aliases, groups, peers and
  themes.
- **Security and privacy:** contacts stay on the device; in production they would be in an end-to-end-encrypted
  sync blob. Import is consented (LinkedIn data export), never scraped. People-in-filings data is public and
  sourced. FINN flags current employees and people at competitors before you call, which is the MNPI line.
- **LLMs and agents:** three tiers (bulk, extract, reason), with JSON schemas, caching and a usage ledger. The Pull
  agent plans which documents to read, calls fetchers and parsers, and streams progress. It never acts on my behalf.
- **Cloud:** GitHub Actions (daily job), GitHub Pages (app), Render (API), Google AI Studio (models).

**Data honesty.** The network is synthetic: fictional people with real employers, so overlaps with real filings
can be demonstrated. Prices, filings, statements and transcripts are real. In the committed snapshot, the
model-written parts were produced at build time with the pipeline's own prompts and schemas. The first scheduled
run with a Gemini key regenerates them.

## What I deliberately left out

- **Real push notifications** (web push / VAPID) and an intraday feed. EOD plus the in-app brief was enough to
  prove the idea.
- **Annual-report deep reads** (notes, contingent liabilities, related-party transactions). Transcripts gave the
  best signal per token for the promise tracker.
- **OCR for scanned PDFs, consensus estimates for "surprise", and auth/multi-user.**
- **Scraped LinkedIn.** Against its terms, and unnecessary given the user's own export.

## Where I'd take it next

1. A per-filing event trigger every few minutes during market hours, with push.
2. **Promise tracking as a living ledger** across years, with management credibility scores that feed back into
   materiality.
3. Expert-call notes captured into the network ("what did Meera say about mortgages?") and searchable from Ask.
4. A licensed people-data provider for appointees without annexure profiles, and calendar/CRM sync for "last
   spoke".
5. Annual-report reading for related-party transactions and contingent liabilities as red flags.
