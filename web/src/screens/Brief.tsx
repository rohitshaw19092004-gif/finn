import { useMemo, useState } from "react";
import { useSnap } from "../data";
import { moves, Move } from "../alerts";
import type { Filing, Rules, Story, Tier, FiledPerson } from "../types";
import { ago, CAT_LABEL, cls, crore, fq, parseTs, pct, save, store, tone, chg, chgTone } from "../util";
import { Avatar, Icon, Panel, Seg, Spark, Tie } from "../ui/kit";
import { AreaChart, DistBar, Num, StackedBars } from "../ui/charts";
import { dayChange } from "../alerts";
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

  const winLabel = WINDOWS.find((w) => w[0] === rules.windowHours)?.[1] ?? "period";
  const held = holdings.filter((h) => h.held);
  const cov = useMemo(() => idx.coverage(held.map((h) => h.symbol)), [idx]); // eslint-disable-line
  const covered = cov.filter((c) => c.insiders.length).length;
  const ruleSorted = snap.meta.classification.exchange + snap.meta.classification.rule;
  const mvSyms = new Set(mv.map((m) => m.symbol)).size;
  return (
    <div className="screen brief dash">
      <header className="top dash-head">
        <div className="dash-title">
          <h1 className="headline">
            {act.length ? <><b>{act.length}</b> {act.length === 1 ? "thing needs" : "things need"} you.</> : <>Nothing needs you.</>}{" "}
            <span className="dim">{routineFilings + glance.length} filings didn't.</span>
          </h1>
          <div className="sub-head">Morning brief · as of {asOf.toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</div>
        </div>
        <div className="dash-controls">
          <Seg value={rules.windowHours} options={WINDOWS} onChange={(h) => setRules({ ...rules, windowHours: h })} />
          <button className="btn ghost" onClick={listen} aria-label={speaking ? "Stop" : "Listen to brief"} title="Listen to the brief"><Icon name={speaking ? "stop" : "play"} size={13} /><span className="btn-l">{speaking ? "Stop" : "Listen"}</span></button>
          <button className="btn" onClick={openRules} aria-label="Watch rules" title="Watch rules"><Icon name="rules" size={14} /><span className="btn-l">Watch rules</span></button>
        </div>
      </header>

      <div className="stats">
        <Stat i={0} label="Needs you" value={act.length} badge={glance.length ? `${glance.length} worth a glance` : "nothing else"} tone="violet" note={`in the last ${winLabel}`} />
        <Stat i={1} label="Price alerts" value={mvSyms} badge={`±${rules.pricePct}% or ${rules.volMult}× volume`} tone={mvSyms ? "warn" : "up"} note="your rules, on device" />
        <Stat i={2} label="Network coverage" value={covered} suffix={` / ${held.length}`} badge={`${held.length - covered} blind spot${held.length - covered === 1 ? "" : "s"}`} tone="up" note="holdings with an insider you know" />
        <Stat i={3} label="Filings read" value={snap.meta.filings} badge={`${Math.round((ruleSorted / Math.max(1, snap.meta.filings)) * 100)}% without a model`} tone="up" note={`last ${snap.meta.window_days} days`} />
      </div>

      <div className="dash-charts">
        <BookIndex />
        <Allocation />
      </div>

      <div className="dash-main">
        <div className="col-main">
          {intro && <div className="intro">
            <p><b>FINN reads every filing across your {held.length} holdings and only interrupts you for what moves the thesis.</b> Each card says what happened, why it matters, and who in your network can explain it.</p>
            <p className="small dim">Ask digs into any company from its own filings and calls. People shows what your network can see that you can't. Your network stays on this phone.</p>
            <button className="btn" onClick={() => { setIntro(false); save("introSeen", true); }}>Got it</button>
          </div>}

          <Panel i={4} title="Needs you" count={act.length} className="stories-panel" right={<span className="tiny dim">ranked by materiality · {winLabel}</span>}>
            {act.length === 0 && (
              <div className="quiet">
                Quiet {winLabel}.{" "}
                {rules.windowHours < 336 && <button className="link" onClick={() => setRules({ ...rules, windowHours: 336 })}>See the last 2 weeks →</button>}
              </div>
            )}
            {act.length === 0 && lastAct && <>
              <h3 className="sub">Last thing that needed you</h3>
              <StoryCard st={lastAct} lead={byId.get(lastAct.lead)!} />
            </>}
            {act.slice(0, BUDGET).map((x, k) => <StoryCard key={x.st.id} st={x.st} lead={x.lead} onDone={() => toggleDone(x.st.id)} i={k} />)}
            {act.length > BUDGET && <>
              <h3 className="sub">Also needs you <span className="count">{act.length - BUDGET}</span></h3>
              <ul className="glance">{act.slice(BUDGET).map((x) => <GlanceRow key={x.st.id} st={x.st} lead={x.lead} onDone={() => toggleDone(x.st.id)} full />)}</ul>
            </>}
          </Panel>

          {glance.length > 0 && <Panel i={5} title="Worth a glance" count={glance.length}>
            <ul className="glance">{glance.map((x) => <GlanceRow key={x.st.id} st={x.st} lead={x.lead} onDone={() => toggleDone(x.st.id)} />)}</ul>
          </Panel>}

          {(routine.length > 0 || cleared.length > 0) && <Panel i={6} title="Filed away">
            {routine.length > 0 && <>
              <button className="routine-toggle" onClick={() => setShowRoutine(!showRoutine)}>
                <span><b>{routineFilings}</b> routine filings</span>
                <span className="dim small">{routineMix(routine.map((x) => x.lead))}</span>
                <span className="chev">{showRoutine ? "−" : "+"}</span>
              </button>
              {showRoutine && <ul className="glance routine">{routine.map((x) => <GlanceRow key={x.st.id} st={x.st} lead={x.lead} compact />)}</ul>}
            </>}
            {cleared.length > 0 && <>
              <button className="routine-toggle" onClick={() => setShowDone(!showDone)}><span>Cleared <b>{cleared.length}</b></span><span className="chev">{showDone ? "−" : "+"}</span></button>
              {showDone && <ul className="glance">{cleared.map((x) => <GlanceRow key={x.st.id} st={x.st} lead={x.lead} onDone={() => toggleDone(x.st.id)} doneLabel="Restore" />)}</ul>}
            </>}
          </Panel>}
        </div>

        <div className="col-side">
          {mv.length > 0 ? <MovesStrip moves={mv} /> : <Panel i={4} title="Price watch"><div className="quiet small">No moves beyond your rules in the last {winLabel}.</div></Panel>}
          <FilingFlow />
          <AskCard />
          <HoldingsPanel />
          <HealthPanel />
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, suffix, badge, tone: t, note, i }: { label: string; value: number; suffix?: string; badge: string; tone: string; note: string; i: number }) {
  return <section className="panel stat" style={{ ["--i" as string]: i }}>
    <div className="stat-label">{label}<span className="tiny dim">{note}</span></div>
    <Num value={value} suffix={suffix} />
    <span className={cls("pill", t)}>{badge}</span>
  </section>;
}

/** Weighted index of current holdings (constant current weights), rebased to 100 — EOD closes only. */
function BookIndex() {
  const { holdings } = useSnap();
  const [range, setRange] = useState(250);
  const data = useMemo(() => {
    const held = holdings.filter((h) => h.held && h.weight && h.close.length > 30);
    const base = held.reduce((a, h) => (h.dates.length > a.dates.length ? h : a), held[0]);
    if (!base) return null;
    const maps = held.map((h) => ({ w: h.weight!, m: new Map(h.dates.map((d, i) => [d, h.close[i]] as const)), v: new Map(h.dates.map((d, i) => [d, h.volume[i]] as const)), h }));
    const dates = base.dates.slice(-range);
    const first = new Map(maps.map((x) => [x.h.symbol, dates.map((d) => x.m.get(d)).find((v) => v != null)] as const));
    const med = new Map(maps.map((x) => { const vs = x.h.volume.filter((v): v is number => !!v).sort((a, b) => a - b); return [x.h.symbol, vs[Math.floor(vs.length / 2)] || 1] as const; }));
    const vals: number[] = [], vols: number[] = [];
    let last = 100;
    for (const d of dates) {
      let num = 0, den = 0, rv = 0, rn = 0;
      for (const x of maps) {
        const c = x.m.get(d), f = first.get(x.h.symbol);
        if (c != null && f) { num += x.w * (c / f); den += x.w; }
        const v = x.v.get(d);
        if (v) { rv += v / med.get(x.h.symbol)!; rn += 1; }
      }
      last = den ? (num / den) * 100 : last;
      vals.push(last);
      vols.push(rn ? rv / rn : 0);
    }
    return { dates, vals, vols };
  }, [holdings, range]);
  if (!data) return null;
  const now = data.vals[data.vals.length - 1], chg = now - 100;
  const day = data.vals.length > 1 ? (now / data.vals[data.vals.length - 2] - 1) * 100 : 0;
  return <Panel i={4} className="index-panel" title={<>Your book <Icon name="chart" size={13} /></>} right={<Seg value={range} options={[[22, "1M"], [66, "3M"], [130, "6M"], [250, "1Y"]]} onChange={setRange} />}>
    <div className="row gap wrap index-head">
      <Num value={now} dp={2} />
      <span className={cls("pill", chg >= 0 ? "up" : "down")}><Icon name="up" size={11} />{pct(chg, 1)} over {range >= 250 ? "1Y" : range >= 130 ? "6M" : range >= 66 ? "3M" : "1M"}</span>
      <span className={cls("small num", tone(day))}>{pct(day, 2)} last session</span>
    </div>
    <AreaChart dates={data.dates} values={data.vals} volume={data.vols} height={window.innerWidth >= 1024 ? 250 : 200} fmt={(v) => v.toFixed(0)}
      tip={(i) => <><div><b className="num">{data.vals[i].toFixed(2)}</b> <span className="tiny dim">index</span></div>
        {i > 0 && <div className={cls("tiny num", tone(data.vals[i] - data.vals[i - 1]))}>{pct((data.vals[i] / data.vals[i - 1] - 1) * 100, 2)} that day</div>}
        <div className="tiny dim">volume {data.vols[i].toFixed(1)}× normal</div></>} />
    <div className="tiny dim">Holdings weighted by today's portfolio weights, EOD closes rebased to 100. Bars: average volume vs each stock's normal.</div>
  </Panel>;
}

const SHADES = ["c1", "c2", "c3", "c4", "c5", "c6"];
function Allocation() {
  const { holdings } = useSnap();
  const nav = useNav();
  const groups = useMemo(() => {
    const m = new Map<string, { w: number; syms: string[]; day: number }>();
    holdings.filter((h) => h.held && h.weight).forEach((h) => {
      const k = h.industry ?? h.sector ?? "Other";
      const g = m.get(k) ?? { w: 0, syms: [], day: 0 };
      g.w += h.weight!; g.syms.push(h.symbol); g.day += (dayChange(h) ?? 0) * h.weight!;
      m.set(k, g);
    });
    const all = [...m.entries()].sort((a, b) => b[1].w - a[1].w);
    const top = all.slice(0, 5), rest = all.slice(5);
    if (rest.length) top.push(["Other sectors", { w: rest.reduce((a, [, g]) => a + g.w, 0), syms: rest.flatMap(([, g]) => g.syms), day: rest.reduce((a, [, g]) => a + g.day, 0) }]);
    return top;
  }, [holdings]);
  const tot = groups.reduce((a, [, g]) => a + g.w, 0) || 1;
  return <Panel i={5} className="alloc-panel" title="Allocation" right={<span className="tiny dim">by industry · weight</span>}>
    <div className="alloc-total"><Num value={tot} dp={1} suffix="%" /><span className="tiny dim">of book in {groups.reduce((a, [, g]) => a + g.syms.length, 0)} stocks</span></div>
    <DistBar parts={groups.map(([k, g], i) => ({ label: k, value: g.w, cls: SHADES[i % SHADES.length] }))} />
    <ul className="alloc">{groups.map(([k, g], i) => <li key={k}>
      <i className={SHADES[i % SHADES.length]} />
      <span><b>{k}</b><span className="tiny dim">{((g.w / tot) * 100).toFixed(0)}% · {g.syms.slice(0, 3).map((s, j) => <span key={s}>{j ? ", " : ""}<button className="link-q" onClick={() => nav.company(s)}>{s}</button></span>)}{g.syms.length > 3 ? ` +${g.syms.length - 3}` : ""}</span></span>
      <span className={cls("num small", tone(g.day))}>{pct(g.day / g.w * 100, 2)}</span>
    </li>)}</ul>
  </Panel>;
}

/** Filings per day by tier — what FINN read, and how little of it reached you. */
function FilingFlow() {
  const { filings } = useSnap();
  const days = useMemo(() => {
    const m = new Map<string, { act: number; glance: number; routine: number }>();
    filings.forEach((f) => { const d = m.get(f.date) ?? { act: 0, glance: 0, routine: 0 }; d[f.tier] += 1; m.set(f.date, d); });
    return [...m.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).slice(-10);
  }, [filings]);
  if (!days.length) return null;
  const total = days.reduce((a, [, d]) => a + d.act + d.glance + d.routine, 0);
  return <Panel i={6} title="Filings read" right={<span className="legend"><i className="c1" />needs you<i className="c3" />glance<i className="c5" />routine</span>}>
    <div className="row gap index-head"><Num value={total} /><span className="pill violet">{days.reduce((a, [, d]) => a + d.act, 0)} reached you</span><span className="tiny dim">last {days.length} filing days</span></div>
    <StackedBars labels={days.map(([d]) => d.slice(8))} height={120}
      series={[{ name: "needs you", values: days.map(([, d]) => d.act), cls: "c1" }, { name: "glance", values: days.map(([, d]) => d.glance), cls: "c3" }, { name: "routine", values: days.map(([, d]) => d.routine), cls: "c5" }]} />
  </Panel>;
}

function AskCard() {
  const nav = useNav();
  return <section className="panel promo" style={{ ["--i" as string]: 7 }}>
    <div className="pixels" aria-hidden>{Array.from({ length: 14 }, (_, k) => <i key={k} style={{ ["--k" as string]: k, left: `${k % 2 ? 78 + ((k * 7) % 18) : 2 + ((k * 11) % 18)}%`, top: `${4 + ((k * 29) % 60)}%` }} />)}</div>
    <span className="promo-icon"><Icon name="bot" size={22} /></span>
    <h3>Ask FINN about any company</h3>
    <p className="small dim">Promised vs delivered from its own earnings calls, every quote checked against the transcript — and who you know there.</p>
    <button className="btn wide" onClick={() => nav.tab("ask")}>Try Ask</button>
  </section>;
}

function HoldingsPanel() {
  const snap = useSnap();
  const nav = useNav();
  const held = snap.holdings.filter((h) => h.held).sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0));
  const watch = snap.holdings.filter((h) => !h.held);
  const Row = ({ h }: { h: typeof held[number] }) => {
    const ch = dayChange(h);
    return <tr onClick={() => nav.company(h.symbol)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && nav.company(h.symbol)}>
      <td><span className="t-sym">{h.symbol}</span><span className="t-name">{h.industry ?? h.sector ?? ""}</span></td>
      <td className="num">{h.close.length ? h.close[h.close.length - 1].toLocaleString("en-IN", { maximumFractionDigits: 1 }) : "—"}</td>
      <td className={cls("num", tone(ch))}>{ch != null ? pct(ch * 100, 2) : "—"}</td>
      <td className="num dim t-wt">{h.weight != null ? h.weight + "%" : ""}</td>
      <td className="t-spark"><Spark data={h.close.slice(-30)} w={54} h={18} /></td>
    </tr>;
  };
  return <Panel i={8} title="Portfolio" count={held.length} right={<span className="tiny dim">EOD · 1D · weight</span>}>
    <table className="dtable"><thead><tr><th>Stock</th><th>Last</th><th>1D</th><th className="t-wt">Wt</th><th>30D</th></tr></thead>
      <tbody>{held.map((h) => <Row key={h.symbol} h={h} />)}</tbody>
      {watch.length > 0 && <><thead><tr><th colSpan={5} className="t-group">Research list</th></tr></thead>
        <tbody>{watch.map((h) => <Row key={h.symbol} h={h} />)}</tbody></>}
    </table>
  </Panel>;
}

function HealthPanel() {
  const { meta } = useSnap();
  const run = meta.run;
  const totals = (meta.llm as any)?.totals;
  const research = run ? Object.values(run.research) : [];
  const byStatus = new Map<string, number>();
  research.forEach((r) => byStatus.set(r.status, (byStatus.get(r.status) ?? 0) + 1));
  return <Panel i={9} title={<><Icon name="health" size={14} /> Data refresh</>} right={run && <span className={cls("pill", run.health === "ok" ? "up" : run.health === "failed" ? "down" : "warn")}>{run.health}</span>}>
    <div className="kv small">
      <span>Generated</span><span>{new Date(meta.generated_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</span>
      <span>Filings</span><span>{meta.filings} from {filingSources(meta)}</span>
      <span>Classified</span><span>{meta.classification.exchange + meta.classification.rule} by rules, {meta.classification.llm ?? 0} by model</span>
      {totals && <><span>Model calls</span><span>{totals.calls} ok · {totals.cached} cached{totals.failed ? <span className="warn-t"> · {totals.failed} failed</span> : null}{totals.deferred ? <span className="warn-t"> · {totals.deferred} deferred</span> : null}</span></>}
      {byStatus.size > 0 && <><span>Dossiers</span><span>{[...byStatus.entries()].map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(" · ")}</span></>}
    </div>
    {run && (() => { const allNotes = [...run.warnings, ...(run.notes ?? [])]; return allNotes.length > 0 && <details className="health"><summary className={cls("small", run.warnings.length ? "warn-t" : "dim")}>{allNotes.length} note{allNotes.length > 1 ? "s" : ""} from this refresh</summary>
      <ul className="small">{run.warnings.map((w, i) => <li key={"w" + i}>{w}</li>)}{(run.notes ?? []).map((w, i) => <li key={"n" + i} className="dim">{w}</li>)}</ul></details>; })()}
    {!run && <div className="tiny dim">Snapshot predates the refresh report.</div>}
  </Panel>;
}

function filingSources(meta: ReturnType<typeof useSnap>["meta"]) {
  const f = meta.run?.sources?.filings;
  if (!f) return "BSE";
  const c = new Map<string, number>();
  Object.values(f).forEach((v) => c.set(v, (c.get(v) ?? 0) + 1));
  return [...c.entries()].sort((a, b) => b[1] - a[1]).map(([k, n]) => (c.size > 1 ? `${k} ×${n}` : k)).join(", ");
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
    <Panel title="Price watch" count={list.length} className="moves" right={<span className="tiny dim">beyond your rules</span>}>
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
    </Panel>
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

export function StoryCard({ st, lead, onDone, i = 0 }: { st: Story; lead: Filing; onDone?: () => void; i?: number }) {
  const snap = useSnap();
  const nav = useNav();
  const h = snap.holdings.find((x) => x.symbol === st.symbol);
  const others = st.filings.slice(1).map((id) => snap.byId.get(id)!).filter(Boolean);
  const peopleIds = Array.from(new Set(st.filings.flatMap((id) => snap.byId.get(id)?.people ?? [])));
  const people = peopleIds.map((id) => snap.peopleById.get(id)).filter(Boolean) as FiledPerson[];
  const [showAll, setShowAll] = useState(false);
  const day = h ? h.close[h.close.length - 1] / h.close[h.close.length - 2] - 1 : null;

  return (
    <article className="card" style={{ ["--i" as string]: i }}>
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
            <td className={cls("num", chgTone(m, "qoq"))}>{chg(m, "qoq")}</td><td className={cls("num", chgTone(m, "yoy"))}>{chg(m, "yoy")}</td></tr>
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
