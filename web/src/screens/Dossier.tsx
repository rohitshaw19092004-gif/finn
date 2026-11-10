import { useEffect, useRef, useState } from "react";
import { loadDossier, useSnap, apiBase } from "../data";
import type { Analysis, Dossier as D, Note } from "../types";
import { cls, crore, fq, pct, tone } from "../util";
import { Bars, Spark, Verdict, Empty } from "../ui/kit";
import { CallLine, StoryCard } from "./Brief";
import { dayChange } from "../alerts";

const SECTIONS = [["snap", "Snapshot"], ["promises", "Promises"], ["traj", "Trajectory"], ["bs", "Balance sheet"], ["cash", "Cash"], ["debate", "Bull / bear"], ["people", "Who to call"]] as const;

export function Dossier({ sym, onBack }: { sym: string; onBack: () => void }) {
  const snap = useSnap();
  const [d, setD] = useState<D | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [steps, setSteps] = useState<string[]>([]);
  const [active, setActive] = useState("snap");
  const refs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    setD(null); setErr(null); setSteps([]);
    loadDossier(sym, (m) => setSteps((s) => [...s, m])).then(setD).catch((e) => setErr(e.message));
    window.scrollTo(0, 0);
  }, [sym]);

  useEffect(() => {
    if (!d) return;
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive((e.target as HTMLElement).dataset.k!)), { rootMargin: "-40% 0px -55% 0px" });
    Object.values(refs.current).forEach((el) => el && io.observe(el));
    return () => io.disconnect();
  }, [d]);

  const h = snap.holdings.find((x) => x.symbol === sym);
  const stories = snap.stories.filter((s) => s.symbol === sym && s.tier === "act").slice(0, 2);

  if (err) return (
    <div className="screen"><button className="back" onClick={onBack}>← Back</button>
      <Empty>{err === "offline"
        ? <>FINN's research engine isn't connected in this preview, so live research on <b>{sym}</b> isn't available here. Pre-built dossiers: {snap.holdings.slice(0, 6).map((x) => x.symbol).join(", ")}…</>
        : <>Couldn't research {sym}: {err}</>}</Empty></div>);
  if (!d) return (
    <div className="screen"><button className="back" onClick={onBack}>← Back</button>
      <div className="loading"><div className="pulse" /><div>Researching {sym} from primary sources…</div>
        <ol className="steps">{steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
        {apiBase && <div className="small dim">First request may take ~30s while the free-tier server wakes up.</div>}
      </div></div>);

  const s = d.snapshot;
  const go = (k: string) => refs.current[k]?.scrollIntoView({ behavior: "smooth", block: "start" });
  const reg = (k: string) => (el: HTMLElement | null) => { refs.current[k] = el; if (el) el.dataset.k = k; };
  const ch = h ? dayChange(h) : null;

  return (
    <div className="screen dossier">
      <button className="back" onClick={onBack}>← Back</button>
      <header className="d-head">
        <div className="eyebrow">{s.sector?.join(" · ")}{h?.held ? ` · ${h.weight}% of portfolio` : " · not held"}</div>
        <h1 className="d-name">{d.name}</h1>
        <div className="d-stats">
          <div><span className="k">Price</span><span className="v num">₹{(h?.close.length ? h.close[h.close.length - 1] : s.price)?.toLocaleString("en-IN")}</span>{ch != null && <span className={cls("small num", tone(ch))}>{pct(ch * 100, 1)}</span>}</div>
          <div><span className="k">Mkt cap</span><span className="v num">{crore(s.mcap_cr)}</span></div>
          <div><span className="k">P/E</span><span className="v num">{s.pe ?? "—"}</span></div>
          <div><span className="k">{s.lender ? "ROE" : "ROCE"}</span><span className="v num">{(s.lender ? s.roe : s.roce) ?? "—"}%</span></div>
        </div>
        {h && <><Spark data={h.close.slice(-250)} w={340} h={44} fluid /><div className="tiny dim">1 year · EOD {h.dates[h.dates.length - 1]}</div></>}
      </header>

      <AnalysisBanner a={d.analysis} prose={d.generated_by.prose} />

      <nav className="d-tabs scroll">{SECTIONS.map(([k, l]) => <button key={k} className={cls(active === k && "on")} onClick={() => go(k)}>{l}</button>)}</nav>

      {stories.length > 0 && <div className="d-news">{stories.map((st) => <StoryCard key={st.id} st={st} lead={snap.byId.get(st.lead)!} />)}</div>}

      <section ref={reg("snap")} className="d-sec">
        <h2 className="section">Snapshot</h2>
        <p className="lede">{d.business_mix?.what_it_does ?? s.about}</p>
        {d.business_mix?.segments?.length ? <Segments segs={d.business_mix.segments} src={d.business_mix.source} /> : null}
        {s.latest_quarter && <QuarterTable d={d} />}
        {d.red_flags.length > 0 && <div className="flags">{d.red_flags.map((n, i) => <div key={i} className="flag">⚑ {n.text}</div>)}</div>}
      </section>

      <section ref={reg("promises")} className="d-sec">
        <h2 className="section">Promised vs delivered</h2>
        {d.promises ? <>
          <p className="lede">{d.promises.credibility}</p>
          <ul className="promises">{d.promises.promises.map((p, i) => (
            <li key={i}>
              <div className="row between"><span className="small dim">{p.said_in} · {p.metric}</span><Verdict v={p.verdict} /></div>
              <div className="p-promise">“{p.promise}”</div>
              <div className="p-outcome">{p.outcome}</div>
              {p.evidence && p.evidence !== "—" && <div className="tiny dim">{p.evidence}</div>}
              <Checks quote={p.quote_check} evidence={p.evidence_check} note={p.verdict_note} />
            </li>))}</ul>
          <h3 className="sub">Narrative vs numbers</h3>
          <div className="nvn">{d.promises.narrative_vs_numbers.map((n, i) => (
            <div key={i} className={cls("nvn-row", n.agree ? "agree" : "disagree")}>
              <div className="nvn-theme">{n.theme} <span>{n.agree ? "agree" : "diverge"}</span></div>
              <div className="nvn-cols"><div><span className="k">Management says</span>{n.management_says}</div><div><span className="k">Numbers say</span>{n.numbers_say}</div></div>
            </div>))}</div>
          {d.guidance.length > 0 && <details className="guidance"><summary>All {d.guidance.length} guidance statements, with quotes</summary>
            <ul>{d.guidance.map((g, i) => <li key={i}><span className="small dim">{g.said_in} · {g.kind}</span><div><b>{g.statement}</b>{g.target ? <span className="dim"> — {g.target}, {g.horizon}</span> : null}</div><q>{g.quote}</q>{g.speaker && <span className="tiny dim"> — {g.speaker}</span>}
              <span className="tiny dim">{g.quote_check === "verbatim" ? "✓ quote found verbatim in the transcript" : g.quote_check === "near" ? "≈ quote found near-verbatim in the transcript" : "quote not re-checked"}{g.page ? ` · p.${g.page}` : ""}</span></li>)}</ul></details>}
        </> : <Empty>{missingWhy(d.analysis, "Reading management commentary")} The numbers below are computed from the filings and work without it.</Empty>}
      </section>

      <section ref={reg("traj")} className="d-sec">
        <h2 className="section">Trajectory</h2>
        <Notes notes={d.trajectory.notes} />
        <Bars labels={d.trajectory.years.slice(-8).map((y) => "'" + y.slice(-2))} fmt={String}
          series={[{ name: "Revenue", values: d.trajectory.revenue.slice(-8), color: "var(--ink-3)" }, { name: s.lender ? "Financing profit" : "Operating profit", values: d.trajectory.operating_profit.slice(-8), color: "var(--accent)" }]} />
        <div className="cagr">
          {["revenue", "pat", "eps"].map((k) => <div key={k}><span className="k">{k.toUpperCase()} CAGR</span>
            <span className="num">3y {pct(d.trajectory.cagr[k]?.["3y"])} · 5y {pct(d.trajectory.cagr[k]?.["5y"])}</span></div>)}
          {!s.lender && <div><span className="k">Operating margin</span><span className="num">{d.trajectory.opm.slice(-6).map((x) => x ?? "—").join(" → ")}%</span></div>}
        </div>
      </section>

      <section ref={reg("bs")} className="d-sec">
        <h2 className="section">Balance sheet</h2>
        <Notes notes={d.balance_sheet.notes} />
        {!s.lender && <table className="mini"><thead><tr><th />{d.balance_sheet.cols.map((c) => <th key={c}>{c.replace(/^\w+ 20/, "'")}</th>)}</tr></thead><tbody>
          <tr><td>Debt</td>{d.balance_sheet.debt.map((v, i) => <td key={i} className="num">{v?.toLocaleString("en-IN") ?? "—"}</td>)}</tr>
          <tr><td>D/E</td>{d.balance_sheet.de.map((v, i) => <td key={i} className="num">{v ?? "—"}</td>)}</tr>
          <tr><td>CWIP</td>{d.balance_sheet.cwip.map((v, i) => <td key={i} className="num">{v?.toLocaleString("en-IN") ?? "—"}</td>)}</tr>
        </tbody></table>}
        {!s.lender && d.balance_sheet.wc["Cash Conversion Cycle"]?.some((x) => x != null) && <table className="mini"><thead><tr><th>Days</th>{d.balance_sheet.ratio_cols.map((c) => <th key={c}>{c.replace(/^\w+ 20/, "'")}</th>)}</tr></thead><tbody>
          {["Debtor Days", "Inventory Days", "Days Payable", "Cash Conversion Cycle"].map((k) => d.balance_sheet.wc[k]?.some((x) => x != null) &&
            <tr key={k}><td>{k.replace(" Days", "").replace("Cash Conversion Cycle", "Cash cycle")}</td>{d.balance_sheet.wc[k].map((v, i) => <td key={i} className="num">{v ?? "—"}</td>)}</tr>)}
        </tbody></table>}
      </section>

      <section ref={reg("cash")} className="d-sec">
        <h2 className="section">Cash quality</h2>
        <Notes notes={d.cash.notes} />
        {!s.lender && <Bars labels={d.cash.cols.map((c) => "'" + c.slice(-2))} fmt={String}
          series={[{ name: "PAT", values: d.cash.pat, color: "var(--ink-3)" }, { name: "Cash from ops", values: d.cash.cfo, color: "var(--accent)" }, { name: "Free cash flow", values: d.cash.fcf, color: "var(--accent-2)" }]} />}
      </section>

      <section ref={reg("debate")} className="d-sec">
        <h2 className="section">Bull vs bear</h2>
        {d.bull_bear ? <div className="debate">
          <div className="bull"><h3>Bull</h3><ul>{d.bull_bear.bull.map((x, i) => <li key={i}>{x}{d.bull_bear!.untraced?.includes(x) && <Untraced />}</li>)}</ul></div>
          <div className="bear"><h3>Bear</h3><ul>{d.bull_bear.bear.map((x, i) => <li key={i}>{x}{d.bull_bear!.untraced?.includes(x) && <Untraced />}</li>)}</ul></div>
          {d.bull_bear.what_would_change_my_mind && <p className="small"><b>What would change the view:</b> {d.bull_bear.what_would_change_my_mind}</p>}
        </div> : <Empty>{missingWhy(d.analysis, "The debate")} Facts it would argue from: {[...d.trajectory.notes, ...d.cash.notes].slice(0, 3).map((n) => n.text).join("; ")}.</Empty>}
      </section>

      <section ref={reg("people")} className="d-sec">
        <h2 className="section">Who to call about {s.name?.split(" ")[0]}</h2>
        <CallLine sym={sym} limit={4} />
      </section>

      <footer className="sources">
        <div><b>Sources (primary only).</b> Statements: <a className="link" href={d.sources.statements} target="_blank" rel="noreferrer">screener.in (from exchange filings)</a>.
          {d.sources.transcripts.length > 0 && <> Calls: {d.sources.transcripts.map((t, i) => <a key={i} className="link" href={t.url} target="_blank" rel="noreferrer">{t.period}</a>).reduce((a: any[], x, i) => i ? [...a, ", ", x] : [x], [])}.</>}</div>
        <div className="tiny dim">Numbers: {d.generated_by.numbers}. Commentary: {proseLabel(d)}. No news, broker notes or model memory.</div>
      </footer>
    </div>
  );
}

const STATUS: Record<string, [string, string]> = {
  complete: ["Analysed this refresh", "up"], partial: ["Partly analysed", "warn"], seeded: ["Build-time analysis", "warn"],
  deferred: ["Analysis deferred", "warn"], failed: ["Analysis failed", "down"], unavailable: ["Numbers only", "muted"],
  numbers_only: ["Numbers only", "muted"],
};

/** What the commentary on this page is, how fresh it is, and what is missing — before anyone reads it. */
function AnalysisBanner({ a, prose }: { a?: Analysis; prose: string }) {
  if (!a) return prose === "seeded" ? <div className="analysis warn"><span className="verdict warn">Build-time analysis</span>
    <span className="small"> Commentary was generated before this refresh, from the calls listed under Sources.</span></div> : null;
  const [label, tone] = STATUS[a.status] ?? [a.status, "muted"];
  const bad = a.transcripts.filter((t) => !["ok", "cached", "not_attempted"].includes(t.status));
  return <details className={cls("analysis", tone)}>
    <summary><span className={cls("verdict", tone)}>{label}</span> <span className="small">{a.coverage}{a.verified_quotes ? ` · ${a.verified_quotes} quotes verified against transcripts` : ""}</span></summary>
    {a.notes.map((n, i) => <p key={i} className="small">{n}</p>)}
    <table className="mini"><thead><tr><th>Call</th><th>Status</th><th>Verified</th><th>Model</th></tr></thead><tbody>
      {a.transcripts.map((t) => <tr key={t.period}><td><a className="link" href={t.url} target="_blank" rel="noreferrer">{t.period}</a></td>
        <td className={cls(["ok", "cached"].includes(t.status) ? "up" : t.status === "not_attempted" ? "dim" : "warn-t")}>{t.status.replace(/_/g, " ")}</td>
        <td className="num">{t.verified ?? "—"}{t.rejected ? <span className="dim"> (−{t.rejected})</span> : null}</td><td className="tiny dim">{t.model ?? "—"}</td></tr>)}
    </tbody></table>
    {bad.some((t) => t.error) && <div className="tiny dim">Errors: {bad.filter((t) => t.error).map((t) => `${t.period}: ${t.error}`).join(" · ")}</div>}
    {a.rejected && a.rejected.length > 0 && <div className="tiny dim">Dropped by verification: {a.rejected.slice(0, 5).map((r) => `“${(r.quote ?? r.statement ?? "").slice(0, 60)}…” (${r.reason})`).join("; ")}</div>}
    <div className="tiny dim">Checked {new Date(a.as_of).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</div>
  </details>;
}

function Checks({ quote, evidence, note }: { quote?: string; evidence?: string; note?: string }) {
  if (!quote && !evidence && !note) return null;
  return <div className="tiny checks">
    {quote && <span className={quote === "verbatim" || quote === "near" ? "up" : "warn-t"}>{quote === "verbatim" ? "✓ quote verbatim" : quote === "near" ? "≈ quote near-verbatim" : "quote not verified"}</span>}
    {evidence && <span className={evidence === "traced" ? "up" : evidence === "untraced" ? "warn-t" : "dim"}>
      {evidence === "traced" ? "✓ figures match reported numbers" : evidence === "partly traced" ? "some figures derived" : evidence === "untraced" ? "⚠ figures not found in reported numbers" : "evidence: later calls"}</span>}
    {note && <span className="warn-t">{note}</span>}
  </div>;
}

const Untraced = () => <span className="tiny warn-t" title="Cites a figure that is not in the facts given to the model"> ⚠ unverified figure</span>;

function missingWhy(a: Analysis | undefined, what: string) {
  if (!a) return `${what} needs the research engine (Gemini).`;
  const why: Record<string, string> = {
    deferred: "was deferred: this refresh ran out of model time before reaching this company. The next refresh picks it up.",
    failed: "failed this refresh (model errors are listed above). The next refresh retries it.",
    unavailable: "needs a model key, which this build doesn't have.", numbers_only: "had no readable transcripts to work from.",
    partial: "was not produced this refresh (see the status above).",
  };
  return `${what} ${why[a.status] ?? "is unavailable."}`;
}

function proseLabel(d: D) {
  const a = d.analysis;
  if (!a) return d.generated_by.prose === "seeded" ? "build-time model run (same prompts & schemas as live)" : d.generated_by.prose;
  if (a.source === "seed") return `build-time analysis, not regenerated in this refresh (${d.generated_by.models ?? "build-time run"})`;
  if (a.source === "live") return `generated this refresh by ${(d.generated_by.models ?? []).join(", ") || "the model router"}; every quote checked against the transcript`;
  return "none";
}

function Notes({ notes }: { notes: Note[] }) {
  if (!notes.length) return null;
  return <ul className="notes">{notes.map((n, i) => <li key={i} className={n.tone}>{n.text}</li>)}</ul>;
}

function Segments({ segs, src }: { segs: { name: string; share_pct: number | null; note?: string }[]; src?: string }) {
  const known = segs.filter((s) => s.share_pct != null);
  return <div className="segs">
    {known.length > 0 && <div className="seg-bar">{known.map((s, i) => <span key={i} style={{ flex: s.share_pct! }} title={s.name}>{s.share_pct}%</span>)}</div>}
    <ul>{segs.map((s, i) => <li key={i}><b>{s.name}</b>{s.share_pct != null ? ` ${s.share_pct}%` : ""}{s.note && s.note !== "—" ? <span className="dim"> — {s.note}</span> : null}</li>)}</ul>
    {src && <div className="tiny dim">{src}</div>}
  </div>;
}

function QuarterTable({ d }: { d: D }) {
  const q = d.snapshot.latest_quarter!;
  return <div className="results">
    <div className="results-title">{fq(q.period)} <span className="dim">· {q.headline}</span></div>
    <table className="rt"><thead><tr><th /><th>{q.period.replace(" 20", " '")}</th><th>QoQ</th><th>YoY</th></tr></thead>
      <tbody>{q.metrics.map((m) => <tr key={m.label}><td>{m.label}</td><td className="num">{crore(m.value)}</td><td className={cls("num", tone(m.qoq))}>{pct(m.qoq)}</td><td className={cls("num", tone(m.yoy))}>{pct(m.yoy)}</td></tr>)}</tbody></table>
  </div>;
}
