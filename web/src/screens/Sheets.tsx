import { useSnap } from "../data";
import { useNav } from "../nav";
import { Avatar, Chip, Sheet, Tie } from "../ui/kit";
import type { Rules, Stint } from "../types";
import { CAT_LABEL, shortDate } from "../util";

const yr = (s: Stint) => `${s.from ? s.from.slice(0, 4) : "?"}–${s.to ? s.to.slice(0, 4) : s.from ? "now" : "?"}${s.approx ? " (approx.)" : ""}`;

function Timeline({ career }: { career: Stint[] }) {
  return <ol className="timeline">{[...career].reverse().map((s, i) => (
    <li key={i}><span className="t-when">{yr(s)}</span><span className="t-what"><b>{s.org}</b><span className="small">{s.title}</span>{s.source && <span className="tiny dim"> · {s.source}</span>}</span></li>
  ))}</ol>;
}

export function ContactSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const snap = useSnap();
  const nav = useNav();
  const c = id ? snap.idx.byId.get(id) : undefined;
  if (!c) return <Sheet open={false} onClose={onClose}>{null}</Sheet>;
  const helps = snap.holdings.map((h) => ({ h, pick: snap.idx.whoToCall(h.symbol, 50).find((p) => p.contact.id === c.id) }))
    .filter((x) => x.pick && x.pick.relation !== "theme").sort((a, b) => b.pick!.score - a.pick!.score);
  const filed = snap.people.map((p) => ({ p, ev: snap.idx.overlaps(p, c) })).filter((x) => x.ev.length);
  const knows = c.knows.map((k) => ({ k, c: snap.idx.byId.get(k.id)! })).filter((x) => x.c);
  const knownBy = snap.network.contacts.filter((x) => x.knows.some((k) => k.id === c.id) && !c.knows.some((k) => k.id === x.id));
  const days = snap.idx.daysSince(c);
  return (
    <Sheet open onClose={onClose} title={<span className="row gap"><Avatar name={c.name} size={36} /><span><b>{c.name}</b><br /><span className="small dim">{c.headline}</span></span></span>}>
      <div className="kv"><span>Tie</span><Tie n={c.tie} /><span>How you know them</span><span>{c.how_met}</span>
        <span>Last spoke</span><span className={days > 180 ? "warn-t" : ""}>{shortDate(c.last_contact)} · {Math.round(days / 30)} months ago</span><span>Last 12 months</span><span>{c.interactions_12m} conversations</span></div>
      {filed.length > 0 && <><h3 className="sub">Connects you to people in the news</h3>
        {filed.map(({ p, ev }) => <button key={p.id} className="net-line as-btn" onClick={() => nav.filedPerson(p.id)}><span className="net-dot" /><span><b>{p.name}</b> ({p.event.role}, {p.symbol}) — {ev[0].text}.</span></button>)}</>}
      {helps.length > 0 && <><h3 className="sub">Can help you understand</h3>
        <ul className="list">{helps.slice(0, 6).map(({ h, pick }) => <li key={h.symbol}><button className="link" onClick={() => nav.company(h.symbol)}><b>{h.symbol}</b></button> <span className="small">— {pick!.reason}</span>{pick!.flag && <div className="compliance small">{pick!.flag}</div>}</li>)}</ul></>}
      <h3 className="sub">Career</h3><Timeline career={c.career} />
      {c.education.length > 0 && <div className="small dim">{c.education.map((e) => `${e.degree}, ${e.school} (${e.from ?? "?"}–${e.to ?? "?"})`).join(" · ")}</div>}
      {(knows.length > 0 || knownBy.length > 0) && <><h3 className="sub">Knows</h3>
        <div className="chips wrap">{knows.map(({ k, c: o }) => <Chip key={o.id} onClick={() => nav.contact(o.id)}>{o.name} <Tie n={k.s} /></Chip>)}
          {knownBy.map((o) => <Chip key={o.id} onClick={() => nav.contact(o.id)}>{o.name}</Chip>)}</div></>}
      <div className="chips wrap">{c.expertise.map((e) => <span key={e} className="tag">{e}</span>)}</div>
      <p className="tiny dim">Private to you. FINN never sends your contacts to a server or a model.</p>
    </Sheet>
  );
}

export function FiledPersonSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const snap = useSnap();
  const nav = useNav();
  const p = id ? snap.peopleById.get(id) : undefined;
  if (!p) return <Sheet open={false} onClose={onClose}>{null}</Sheet>;
  const paths = snap.idx.pathsTo(p);
  const filingName = p.event.filing.split(":").pop();
  return (
    <Sheet open onClose={onClose} title={<span className="row gap"><Avatar name={p.name} size={36} /><span><b>{p.name}</b><br /><span className="small dim">{p.event.role} · {p.symbol}</span></span></span>}>
      <p className="lede">{p.summary}</p>
      <div className="kv"><span>Change</span><span>{p.event.change}</span><span>Effective</span><span>{p.event.effective ? shortDate(p.event.effective) : "—"}</span>
        <span>Source</span><span><a className="link" href={`https://www.bseindia.com/xml-data/corpfiling/AttachLive/${filingName}`} target="_blank" rel="noreferrer">{p.source} ↗</a></span></div>
      <h3 className="sub">How you can reach {p.name.split(" ")[0]}</h3>
      {paths.length ? paths.slice(0, 5).map((x, i) => (
        <div key={i} className="path">
          <div className="path-line">
            <span className="node me">You</span><span className="edge" />
            {x.via && <><button className="node" onClick={() => nav.contact(x.via!.id)}>{x.via.name}</button><span className="edge" /></>}
            <button className="node" onClick={() => nav.contact(x.contact.id)}>{x.contact.name}</button><span className="edge dashed" />
            <span className="node target">{p.name.split(" ").slice(-1)[0]}</span>
          </div>
          <div className="small">{x.evidence.map((e) => e.text).join("; ")}.</div>
          <div className="tiny dim">{x.label} · strength {x.strength.toFixed(1)}</div>
        </div>)) : <p className="small dim">No one in your network overlaps with {p.name}{p.career.length ? "" : " — the filing had no profile; a profile provider would fill this"}.</p>}
      {p.career.length > 0 && <><h3 className="sub">Career (from the filing)</h3><Timeline career={p.career} /></>}
      {p.education.length > 0 && <div className="small">{p.education.map((e) => [e.degree, e.school].filter(Boolean).join(", ")).join(" · ")}</div>}
      {p.track_record && <><h3 className="sub">Worth asking about</h3><ul className="list">{p.track_record.map((t) => <li key={t} className="small">{t}</li>)}</ul></>}
    </Sheet>
  );
}

const CATS = ["results", "management_change", "M&A", "litigation", "fund_raise", "capex", "credit_rating", "pledging", "insider_trading", "press_release", "dividend", "earnings_call", "investor_meetings"];

export function RulesSheet({ open, onClose, rules, setRules }: { open: boolean; onClose: () => void; rules: Rules; setRules: (r: Rules) => void }) {
  const toggle = (k: "boost" | "mute", c: string) => {
    const other = k === "boost" ? "mute" : "boost";
    const has = rules[k].includes(c);
    setRules({ ...rules, [k]: has ? rules[k].filter((x) => x !== c) : [...rules[k], c], [other]: rules[other].filter((x) => x !== c) });
  };
  return (
    <Sheet open={open} onClose={onClose} title={<b>Watch rules</b>}>
      <p className="small dim">You decide what “unusual” means. Alerts re-evaluate instantly on your device.</p>
      <h3 className="sub">Price move</h3>
      <div className="chips"><Chip active={rules.priceMode === "pct"} onClick={() => setRules({ ...rules, priceMode: "pct" })}>Fixed %</Chip>
        <Chip active={rules.priceMode === "sigma"} onClick={() => setRules({ ...rules, priceMode: "sigma" })}>Unusual for this stock (σ)</Chip></div>
      {rules.priceMode === "pct"
        ? <label className="slider"><span>Alert beyond ±{rules.pricePct}% in a day</span><input type="range" min={1} max={10} step={0.5} value={rules.pricePct} onChange={(e) => setRules({ ...rules, pricePct: +e.target.value })} /></label>
        : <label className="slider"><span>Alert beyond {rules.sigma}σ of its own 60-day moves</span><input type="range" min={1.5} max={4} step={0.25} value={rules.sigma} onChange={(e) => setRules({ ...rules, sigma: +e.target.value })} /></label>}
      <h3 className="sub">Volume</h3>
      <label className="slider"><span>Alert when volume ≥ {rules.volMult}× its 20-day average</span><input type="range" min={1.5} max={5} step={0.25} value={rules.volMult} onChange={(e) => setRules({ ...rules, volMult: +e.target.value })} /></label>
      <h3 className="sub">Filing types</h3>
      <p className="small dim">Tap once to always surface, twice to mute.</p>
      <div className="chips wrap">{CATS.map((c) => {
        const st = rules.boost.includes(c) ? "on" : rules.mute.includes(c) ? "muted" : "";
        return <Chip key={c} active={!!st} tone={st === "muted" ? "mutechip" : ""} onClick={() => st === "on" ? toggle("mute", c) : st === "muted" ? setRules({ ...rules, mute: rules.mute.filter((x) => x !== c) }) : toggle("boost", c)}>
          {st === "on" ? "★ " : st === "muted" ? "⊘ " : ""}{CAT_LABEL[c]}</Chip>;
      })}</div>
    </Sheet>
  );
}
