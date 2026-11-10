import { useMemo, useState } from "react";
import { useSnap } from "../data";
import { moves, Move } from "../alerts";
import type { Filing, Rules, Story, Tier, FiledPerson } from "../types";
import { ago, CAT_LABEL, cls, crore, fq, parseTs, pct, save, store, tone } from "../util";
import { Avatar, Chip, Spark, Tie } from "../ui/kit";
import { useNav } from "../nav";
import { speak } from "../speech";

const WINDOWS: [number, string][] = [[24, "24h"], [72, "3 days"], [168, "7 days"], [336, "2 weeks"]];
const BUDGET = 5;   // a materiality budget: at most five full cards; the rest compress

export function effective(st: Story, rules: Rules, netBoost: boolean): { score: number; tier: Tier } {
  let s = st.score;
  if (rules.boost.includes(st.category)) s += 15;
  if (rules.mute.includes(st.category)) s -= 40;
  if (netBoost) s += 4;
  return { score: s, tier: s >= 60 ? "act" : s >= 30 ? "glance" : "routine" };
}

export function Brief({ rules, setRules, openRules }: { rules: Rules; setRules: (r: Rules) => void; openRules: () => void }) {
  const snap = useSnap();
  const { asOf, stories, byId, holdings, idx } = snap;
  const [done, setDone] = useState<string[]>(() => store("done", []));
  const [showRoutine, setShowRoutine] = useState(false);
  const [showDone, setShowDone] = useState(false);
  const [speaking, setSpeaking] = useState<null | (() => void)>(null);
  const [intro, setIntro] = useState<boolean>(() => !store("introSeen", false));

  const start = new Date(asOf.getTime() - rules.windowHours * 36e5);
  const sinceDate = start.toISOString().slice(0, 10);

  const items = useMemo(() => stories
    .filter((s) => parseTs(s.latest) >= start)
    .map((s) => {
      const lead = byId.get(s.lead)!;
      const hasNet = s.tier !== "routine" && idx.whoToCall(s.symbol, 1).length > 0;
      return { st: s, lead, ...effective(s, rules, hasNet) };
    })
    .sort((a, b) => b.score - a.score), [stories, rules, asOf.getTime()]); // eslint-disable-line

  const live = items.filter((x) => !done.includes(x.st.id));
  const act = live.filter((x) => x.tier === "act");
  const glance = live.filter((x) => x.tier === "glance");
  const routine = live.filter((x) => x.tier === "routine");
  const cleared = items.filter((x) => done.includes(x.st.id));
  const lastAct = useMemo(() => [...stories].filter((s) => s.tier === "act" && !done.includes(s.id))
    .sort((a, b) => (b.latest > a.latest ? 1 : -1))[0], [stories, done]);
  const mv = useMemo(() => moves(holdings.filter((h) => h.held), rules, sinceDate), [holdings, rules, sinceDate]);
  const routineFilings = routine.reduce((a, x) => a + x.st.filings.length, 0);

  const toggleDone = (id: string) => { const n = done.includes(id) ? done.filter((x) => x !== id) : [...done, id]; setDone(n); save("done", n); };

  const listen = () => {
    if (speaking) { speaking(); setSpeaking(null); return; }
    const lines = [
      `${act.length ? act.length + (act.length === 1 ? " thing needs" : " things need") + " you" : "Nothing needs you"} in the last ${WINDOWS.find((w) => w[0] === rules.windowHours)?.[1] ?? "period"}.`,
      ...act.slice(0, 5).map((x, i) => `${i + 1}. ${coName(snap, x.st.symbol)}. ${x.lead.results?.headline ? fq(x.lead.results.period) + " results: " + x.lead.results.headline : x.lead.summary ?? x.lead.headline}.`),
      mv.length ? `Price watch: ${mv.slice(0, 3).map((m) => `${coName(snap, m.symbol)} ${(m.ret * 100).toFixed(1)} percent${m.volMult && m.volMult >= rules.volMult ? `, on ${m.volMult.toFixed(1)} times normal volume` : ""}`).join("; ")}.` : "",
      `${routineFilings} routine filings were filed away.`,
    ].filter(Boolean);
    const stop = speak(lines, () => setSpeaking(null));
    setSpeaking(() => stop);
  };

  return (
    <div className="screen brief">
      <header className="top">
        <div className="row between">
          <div className="eyebrow">As of {asOf.toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</div>
          <div className="row gap">
            <button className="round" onClick={listen} aria-label={speaking ? "Stop" : "Listen to brief"} title="Listen to the brief">{speaking ? "■" : "▶"}</button>
            <button className="round" onClick={openRules} aria-label="Watch rules" title="Watch rules">⚙</button>
          </div>
        </div>
        <h1 className="headline">
          {act.length ? <><b>{act.length}</b> {act.length === 1 ? "thing needs" : "things need"} you.</> : <>Nothing needs you.</>}{" "}
          <span className="dim">{routineFilings + glance.length} filings didn't.</span>
        </h1>
        <div className="chips scroll">
          {WINDOWS.map(([h, l]) => <Chip key={h} active={rules.windowHours === h} onClick={() => setRules({ ...rules, windowHours: h })}>{l}</Chip>)}
        </div>
      </header>

      {intro && <div className="intro">
        <p><b>FINN reads every filing across your {holdings.filter((h) => h.held).length} holdings and only interrupts you for what moves the thesis.</b> Each card says what happened, why it matters, and who in your network can explain it.</p>
        <p className="small dim">Ask digs into any company from its own filings and calls. People shows what your network can see that you can't. Your network stays on this phone.</p>
        <button className="link small" onClick={() => { setIntro(false); save("introSeen", true); }}>Got it</button>
      </div>}

      {mv.length > 0 && <MovesStrip moves={mv} />}

      {act.length === 0 && (
        <div className="quiet">
          Quiet {WINDOWS.find((w) => w[0] === rules.windowHours)?.[1]}.{" "}
          {rules.windowHours < 336 && <button className="link" onClick={() => setRules({ ...rules, windowHours: 336 })}>See the last 2 weeks →</button>}
        </div>
      )}
      {act.length === 0 && lastAct && <>
        <h2 className="section">Last thing that needed you</h2>
        <StoryCard st={lastAct} lead={byId.get(lastAct.lead)!} />
      </>}

      {act.slice(0, BUDGET).map((x) => <StoryCard key={x.st.id} st={x.st} lead={x.lead} onDone={() => toggleDone(x.st.id)} />)}

      {act.length > BUDGET && <section className="block">
        <h2 className="section">Also needs you <span className="count">{act.length - BUDGET}</span></h2>
        <ul className="glance">{act.slice(BUDGET).map((x) => <GlanceRow key={x.st.id} st={x.st} lead={x.lead} onDone={() => toggleDone(x.st.id)} full />)}</ul>
      </section>}

      {glance.length > 0 && <section className="block">
        <h2 className="section">Worth a glance <span className="count">{glance.length}</span></h2>
        <ul className="glance">{glance.map((x) => <GlanceRow key={x.st.id} st={x.st} lead={x.lead} onDone={() => toggleDone(x.st.id)} />)}</ul>
      </section>}

      {routine.length > 0 && <section className="block">
        <button className="routine-toggle" onClick={() => setShowRoutine(!showRoutine)}>
          <span><b>{routineFilings}</b> routine filings, filed away</span>
          <span className="dim small">{routineMix(routine.map((x) => x.lead))}</span>
          <span className="chev">{showRoutine ? "−" : "+"}</span>
        </button>
        {showRoutine && <ul className="glance routine">{routine.map((x) => <GlanceRow key={x.st.id} st={x.st} lead={x.lead} compact />)}</ul>}
      </section>}

      {cleared.length > 0 && <section className="block">
        <button className="routine-toggle" onClick={() => setShowDone(!showDone)}><span>Cleared <b>{cleared.length}</b></span><span className="chev">{showDone ? "−" : "+"}</span></button>
        {showDone && <ul className="glance">{cleared.map((x) => <GlanceRow key={x.st.id} st={x.st} lead={x.lead} onDone={() => toggleDone(x.st.id)} doneLabel="Restore" />)}</ul>}
      </section>}
      <footer className="foot">
        Filings: BSE · Prices: EOD · {snap.meta.classification.exchange + snap.meta.classification.rule} of {snap.meta.filings} filings classified without a model
      </footer>
    </div>
  );
}

const coName = (snap: ReturnType<typeof useSnap>, sym: string) => snap.holdings.find((h) => h.symbol === sym)?.name?.replace(/ (Ltd|Limited|Industries|International|Technology|Company)\.?$/i, "") ?? sym;

function routineMix(fs: Filing[]) {
  const c = new Map<string, number>();
  fs.forEach((f) => c.set(CAT_LABEL[f.category] ?? f.category, (c.get(CAT_LABEL[f.category] ?? f.category) ?? 0) + 1));
  return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ");
}

function MovesStrip({ moves }: { moves: Move[] }) {
  const snap = useSnap();
  const nav = useNav();
  // one card per stock (its most unusual day), with the filing that likely explains it
  const best = new Map<string, Move & { n: number }>();
  moves.forEach((m) => { const b = best.get(m.symbol); if (!b || Math.abs(m.z) > Math.abs(b.z)) best.set(m.symbol, { ...m, n: (b?.n ?? 0) + 1 }); else b.n += 1; });
  const list = [...best.values()].sort((a, b) => (b.date > a.date ? 1 : b.date < a.date ? -1 : Math.abs(b.z) - Math.abs(a.z)));
  const why = (m: Move) => {
    const t = new Date(m.date).getTime();
    const st = snap.stories.find((s) => s.symbol === m.symbol && s.tier !== "routine" && Math.abs(t - new Date(s.latest.slice(0, 10)).getTime()) <= 3 * 864e5);
    if (!st) return null;
    const f = snap.byId.get(st.lead)!;
    return f.results ? `after ${fq(f.results.period)} results` : `after: ${(CAT_LABEL[st.category] ?? st.why).toLowerCase()}`;
  };
  return (
    <section className="moves">
      <h2 className="section">Price watch <span className="count">{list.length}</span></h2>
      <div className="moves-row scroll">
        {list.slice(0, 12).map((m) => {
          const h = snap.holdings.find((x) => x.symbol === m.symbol)!;
          const w = why(m);
          return (
            <button key={m.symbol} className="move" onClick={() => nav.company(m.symbol)}>
              <div className="mv-sym">{m.symbol}</div>
              <div className="row between"><span className={cls("mv-pct num", tone(m.ret))}>{pct(m.ret * 100, 1)}</span><Spark data={h.close.slice(-30)} w={56} h={22} /></div>
              <div className="tiny">{m.reasons.map((r) => r.replace("volume", "vol").replace(" 20-day avg", " avg")).join(" · ")}</div>
              <div className="tiny dim">{new Date(m.date).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}{w ? ` · ${w}` : ""}</div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function GlanceRow({ st, lead, onDone, compact, doneLabel, full }: { st: Story; lead: Filing; onDone?: () => void; compact?: boolean; doneLabel?: string; full?: boolean }) {
  const snap = useSnap();
  const nav = useNav();
  const [open, setOpen] = useState(false);
  const more = st.filings.length - 1;
  return (
    <li className={cls("g-row", open && "open")}>
      <button className="g-main" onClick={() => setOpen(!open)}>
        <span className="sym">{st.symbol}</span>
        <span className="g-text">{lead.results?.headline ? `${fq(lead.results.period)}: ${lead.results.headline}` : lead.summary ?? lead.headline ?? lead.subject}
          {more > 0 && <span className="dim"> · +{more}</span>}</span>
        {!compact && <span className="g-meta"><span className="cat">{CAT_LABEL[st.category]}</span><span>{ago(st.latest, snap.asOf)}</span></span>}
      </button>
      {open && full && <StoryCard st={st} lead={lead} onDone={onDone} />}
      {open && !full && <div className="g-detail">
        <div className="small dim">{lead.subject}</div>
        {lead.reasons.length > 0 && <div className="small">Why this rank: {lead.reasons.join("; ")} · score {lead.score}</div>}
        <div className="row gap wrap">
          {lead.url && <a className="link small" href={lead.url} target="_blank" rel="noreferrer">Open filing ↗</a>}
          <button className="link small" onClick={() => nav.company(st.symbol)}>{st.symbol} dossier →</button>
          {onDone && <button className="link small" onClick={onDone}>{doneLabel ?? "Done"}</button>}
        </div>
      </div>}
    </li>
  );
}

export function StoryCard({ st, lead, onDone }: { st: Story; lead: Filing; onDone?: () => void }) {
  const snap = useSnap();
  const nav = useNav();
  const h = snap.holdings.find((x) => x.symbol === st.symbol);
  const others = st.filings.slice(1).map((id) => snap.byId.get(id)!).filter(Boolean);
  const peopleIds = Array.from(new Set(st.filings.flatMap((id) => snap.byId.get(id)?.people ?? [])));
  const people = peopleIds.map((id) => snap.peopleById.get(id)).filter(Boolean) as FiledPerson[];
  const [showAll, setShowAll] = useState(false);
  const day = h ? h.close[h.close.length - 1] / h.close[h.close.length - 2] - 1 : null;

  return (
    <article className="card">
      <div className="card-top">
        <button className="co" onClick={() => nav.company(st.symbol)}>
          <span className="sym">{st.symbol}</span>
          <span className="co-name">{h?.name ?? st.symbol}</span>
        </button>
        <span className="card-meta"><span className="cat">{CAT_LABEL[st.category] ?? st.why}</span><span>{ago(st.latest, snap.asOf)}</span></span>
      </div>

      {lead.results ? <ResultsBody lead={lead} /> : (
        <p className="card-line">{lead.summary ?? lead.headline}</p>
      )}

      {people.length > 0 && <PeopleBody people={people} />}

      {others.length > 0 && <div className="also">
        <button className="link small" onClick={() => setShowAll(!showAll)}>{showAll ? "Hide" : `+${others.length} related filing${others.length > 1 ? "s" : ""} in this story`}</button>
        {showAll && <ul>{others.map((f) => <li key={f.id}><span className="dim">{f.date.slice(5)}</span> {f.summary ?? f.headline.slice(0, 140)} {f.url && <a href={f.url} target="_blank" rel="noreferrer" className="link">↗</a>}</li>)}</ul>}
      </div>}

      {!people.length && <CallLine sym={st.symbol} category={st.category} limit={st.category === "litigation" || st.category === "M&A" ? 2 : 1} />}

      <div className="card-foot">
        <span className="small dim foot-why">{[...lead.reasons.slice(0, 2), h?.weight ? `${h.weight}% of book` : "", day != null && !Number.isNaN(day) ? `stock ${pct(day * 100, 1)} last session` : ""].filter(Boolean).join(" · ")}</span>
        <span className="row gap">
          {lead.url && <a className="link small" href={lead.url} target="_blank" rel="noreferrer">Filing ↗</a>}
          {onDone && <button className="done-btn" onClick={onDone} aria-label="Mark done">✓</button>}
        </span>
      </div>
    </article>
  );
}

function ResultsBody({ lead }: { lead: Filing }) {
  const r = lead.results!;
  return (
    <div className="results">
      <div className="results-title">{fq(r.period)} results <span className="dim">· {r.lender ? "lender — NII shown instead of EBITDA" : "consolidated"}</span></div>
      <table className="rt">
        <thead><tr><th /><th>{r.period.replace(" 20", " '")}</th><th>QoQ</th><th>YoY</th></tr></thead>
        <tbody>{r.metrics.map((m) => (
          <tr key={m.label}><td>{m.label}</td><td className="num">{crore(m.value)}</td>
            <td className={cls("num", tone(m.qoq))}>{pct(m.qoq)}</td><td className={cls("num", tone(m.yoy))}>{pct(m.yoy)}</td></tr>
        ))}</tbody>
      </table>
      {r.margin && <div className="small">EBITDA margin <b>{r.margin.now.toFixed(1)}%</b> <span className={tone(r.margin.qoq_pp)}>{r.margin.qoq_pp != null ? `${r.margin.qoq_pp > 0 ? "+" : ""}${r.margin.qoq_pp}pp QoQ` : ""}</span> · <span className={tone(r.margin.yoy_pp)}>{r.margin.yoy_pp != null ? `${r.margin.yoy_pp > 0 ? "+" : ""}${r.margin.yoy_pp}pp YoY` : ""}</span></div>}
      {r.flags.map((f) => <div key={f} className="flag">⚑ {f}</div>)}
    </div>
  );
}

function PeopleBody({ people }: { people: FiledPerson[] }) {
  const snap = useSnap();
  const nav = useNav();
  const ranked = people.map((p) => ({ p, paths: snap.idx.pathsTo(p), top: /md|ceo|chief|chairman/i.test(p.event.role) && !/additional charge/i.test(p.event.change) }))
    .sort((a, b) => Number(b.top) - Number(a.top) || (b.paths[0]?.strength ?? 0) - (a.paths[0]?.strength ?? 0));
  const [lead, ...rest] = ranked;
  const when = (d?: string) => d ? new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "";
  return (
    <div className="people">
      <div className="person">
        <button className="person-head" onClick={() => nav.filedPerson(lead.p.id)}>
          <Avatar name={lead.p.name} size={30} />
          <span><b>{lead.p.name}</b><span className="dim small"> · {lead.p.event.role} · {lead.p.event.change} {when(lead.p.event.effective)}</span></span>
        </button>
        {lead.p.summary && <p className="small bio">{lead.p.summary}</p>}
        <PathLine p={lead.p} paths={lead.paths} />
      </div>
      {rest.length > 0 && <ul className="also-people">{rest.map(({ p, paths }) => (
        <li key={p.id}><button onClick={() => nav.filedPerson(p.id)}>
          <span className={cls("net-dot", !paths.length && "off")} />
          <span><b>{p.name}</b> <span className="dim">· {p.event.role.split(/[;(]/)[0].trim()}, {p.event.change}</span>
            {paths[0] && <span className="small"> — {paths[0].contact.name} ({paths[0].evidence[0].short})</span>}</span>
        </button></li>))}</ul>}
    </div>
  );
}

function PathLine({ p, paths }: { p: FiledPerson; paths: ReturnType<ReturnType<typeof useSnap>["idx"]["pathsTo"]> }) {
  const nav = useNav();
  if (!paths.length) return <div className="net-line muted"><span className="net-dot off" />{p.career.length ? `No one in your network overlaps with ${p.name.split(" ")[0]}.` : "No profile in the filing — enrichment pending."}</div>;
  const x = paths[0];
  return (
    <button className="net-line as-btn" onClick={() => nav.filedPerson(p.id)}>
      <span className="net-dot" />
      <span>{x.via ? <>Intro via <b>{x.via.name}</b> → <b>{x.contact.name}</b></> : <><b>{x.contact.name}</b> <Tie n={x.contact.tie} /></>}
        <span className="dim"> · {x.evidence[0].short}</span>
        {paths.length > 1 && <span className="link"> · {paths.length - 1} more</span>}</span>
    </button>
  );
}

export function CallLine({ sym, limit = 1, category }: { sym: string; limit?: number; category?: string }) {
  const snap = useSnap();
  const nav = useNav();
  const picks = snap.idx.whoToCall(sym, limit, category);
  if (!picks.length) return <div className="net-line muted"><span className="net-dot off" />No one in your network has worked at or around {sym}.</div>;
  return <>{picks.map((p) => (
    <button key={p.contact.id} className="net-line as-btn" onClick={() => nav.contact(p.contact.id)}>
      <span className="net-dot" />
      <span><b>Call {p.contact.name}</b> <Tie n={p.contact.tie} /> — {p.reason}.{p.flag && <span className="compliance"> {p.flag}.</span>}
        {snap.idx.daysSince(p.contact) > 120 && <span className="dim"> Last spoke {Math.round(snap.idx.daysSince(p.contact) / 30)} months ago.</span>}</span>
    </button>
  ))}</>;
}
