import { useEffect, useMemo, useState } from "react";
import { useSnap, searchCompanies, apiBase } from "../data";
import { useNav } from "../nav";
import { canListen, listen } from "../speech";
import { Avatar, Chip, Tie } from "../ui/kit";
import { CallLine } from "./Brief";
import { cls, pct, tone } from "../util";
import { dayChange } from "../alerts";

type Answer =
  | { kind: "company-people"; sym: string; name: string; category?: string }
  | { kind: "theme"; theme: string }
  | { kind: "search"; q: string; hits: { name: string; symbol: string }[] }
  | { kind: "none"; q: string };

const EXAMPLES = [
  "Who knows HDFC Bank's new CEO?",
  "Asian Paints",
  "Who do I call on specialty chemicals?",
  "Clean Science",
  "Who can explain the Polycab NCLAT case?",
  "Rural lending experts",
];

export function Ask({ initial }: { initial?: string }) {
  const snap = useSnap();
  const nav = useNav();
  const [q, setQ] = useState(initial ?? "");
  const [ans, setAns] = useState<Answer | null>(null);
  const [mic, setMic] = useState<null | (() => void)>(null);
  const themes = useMemo(() => snap.idx.expertise(), [snap]);

  useEffect(() => { if (initial) run(initial); }, [initial]); // eslint-disable-line

  // Every company FINN can name: holdings, research list, registry orgs with tickers.
  const companies = useMemo(() => {
    const m = new Map<string, string[]>();
    snap.holdings.forEach((h) => m.set(h.symbol, [h.symbol, h.name ?? ""]));
    Object.entries(snap.registry.orgs).forEach(([id, o]) => { if (o.ticker) m.set(o.ticker, [...(m.get(o.ticker) ?? [o.ticker]), o.name, ...o.aliases]); void id; });
    return m;
  }, [snap]);

  function findCompany(text: string): string | null {
    const t = " " + text.toLowerCase().replace(/[^a-z0-9& ]/g, " ") + " ";
    let best: [string, number] | null = null;
    for (const [sym, names] of companies) for (const n of names) {
      const k = n.toLowerCase().replace(/\b(ltd|limited|industries|international|company|technology)\b/g, "").replace(/[^a-z0-9& ]/g, " ").trim();
      if (k.length >= 3 && t.includes(" " + k + " ") && (!best || k.length > best[1])) best = [sym, k.length];
    }
    return best?.[0] ?? null;
  }

  async function run(text: string) {
    const t = text.trim();
    if (!t) return;
    const low = t.toLowerCase();
    const peopleQ = /\b(who|call|knows?|expert|contact|introduc|path|network|people)\b/.test(low);
    if (/\b(what changed|this week|today|digest|brief|news)\b/.test(low)) { nav.tab("brief"); return; }
    // a person named in a filing?
    const fp = snap.people.find((p) => low.includes(p.name.toLowerCase().split(" ").slice(-1)[0]) && low.includes(p.name.toLowerCase().split(" ")[0]));
    if (fp) { nav.filedPerson(fp.id); return; }
    // a role at a company: "HDFC Bank's new CEO"
    const sym = findCompany(t);
    if (sym && /\b(ceo|md|cfo|chairman|new (ceo|md|cfo|chair))\b/.test(low)) {
      const p = snap.people.find((x) => x.symbol === sym && /appoint|assum/i.test(x.event.change + x.event.role) && x.career.length) ?? snap.people.find((x) => x.symbol === sym);
      if (p) { nav.filedPerson(p.id); return; }
    }
    // someone in my network?
    const c = snap.network.contacts.find((x) => low.includes(x.name.toLowerCase()) || (x.name.split(" ").length > 1 && low.includes(x.name.toLowerCase().split(" ").slice(-1)[0]) && low.includes(x.name.toLowerCase().split(" ")[0])));
    if (c) { nav.contact(c.id); return; }
    const category = /nclat|nclt|court|legal|case|insolven|litigation|ruling|order against/.test(low) ? "litigation"
      : /deal|merger|acqui|divest|demerger/.test(low) ? "M&A" : /rating/.test(low) ? "credit_rating" : undefined;
    if (sym) { if (peopleQ || category) setAns({ kind: "company-people", sym, name: companies.get(sym)?.[1] ?? sym, category }); else nav.company(sym); return; }
    const th = themes.find((x) => low.includes(x.theme.toLowerCase().split(/[ /(]/)[0]) && x.theme.length > 3)
      ?? themes.find((x) => x.theme.toLowerCase().split(/[^a-z]+/).some((w) => w.length > 4 && low.includes(w)));
    if (th) { setAns({ kind: "theme", theme: th.theme }); return; }
    if (apiBase) { const hits = await searchCompanies(t); if (hits.length) { setAns({ kind: "search", q: t, hits }); return; } }
    if (/^[A-Za-z&]{2,15}$/.test(t) && apiBase) { nav.company(t.toUpperCase()); return; }
    setAns({ kind: "none", q: t });
  }

  const voice = () => {
    if (mic) { mic(); setMic(null); return; }
    const stop = listen((txt, fin) => { setQ(txt); if (fin) { run(txt); } }, () => setMic(null));
    setMic(() => stop);
  };

  return (
    <div className="screen ask">
      <header className="top">
        <div className="eyebrow">Pull · primary sources only</div>
        <h1 className="headline">Ask about any company, person or theme.</h1>
      </header>
      <form className="askbar" onSubmit={(e) => { e.preventDefault(); run(q); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Asian Paints · who knows HAL's new director?" aria-label="Ask FINN" />
        {canListen() && <button type="button" className={cls("mic", mic && "on")} onClick={voice} aria-label="Speak">{mic ? "●" : "🎙"}</button>}
        <button type="submit" className="go" aria-label="Ask">→</button>
      </form>
      <div className="chips wrap examples">{EXAMPLES.map((e) => <Chip key={e} onClick={() => { setQ(e); run(e); }}>{e}</Chip>)}</div>

      {ans && <section className="answer">
        {ans.kind === "company-people" && <>
          <h2 className="section">Who to call about {ans.name}{ans.category ? ` (${ans.category === "litigation" ? "the legal case" : ans.category})` : ""}</h2>
          <CallLine sym={ans.sym} limit={4} category={ans.category} />
          <button className="link" onClick={() => nav.company(ans.sym)}>Open the {ans.sym} dossier →</button>
        </>}
        {ans.kind === "theme" && <ThemeAnswer theme={ans.theme} />}
        {ans.kind === "search" && <>
          <h2 className="section">Companies matching “{ans.q}”</h2>
          <ul className="list">{ans.hits.map((h) => <li key={h.symbol}><button className="link" onClick={() => nav.company(h.symbol)}>{h.name} <span className="dim">{h.symbol}</span></button></li>)}</ul>
        </>}
        {ans.kind === "none" && <p className="dim">Nothing matched “{ans.q}”. {apiBase ? "" : "In this preview the live research engine is off, so try a company below, a person in the news, or a theme."}</p>}
      </section>}

      <section className="block">
        <h2 className="section">Research list</h2>
        <CompanyGrid syms={snap.holdings.filter((h) => !h.held).map((h) => h.symbol)} />
        <h2 className="section">Portfolio</h2>
        <CompanyGrid syms={snap.holdings.filter((h) => h.held).map((h) => h.symbol)} />
        {apiBase && <p className="small dim">Any other NSE symbol works too — FINN reads its filings and calls on demand.</p>}
      </section>
    </div>
  );
}

function CompanyGrid({ syms }: { syms: string[] }) {
  const snap = useSnap();
  const nav = useNav();
  return <div className="cgrid">{syms.map((s) => {
    const h = snap.holdings.find((x) => x.symbol === s)!;
    const ch = dayChange(h);
    return <button key={s} className="ctile" onClick={() => nav.company(s)}>
      <b>{s}</b><span className={cls("small num", tone(ch))}>{ch != null ? pct(ch * 100, 1) : ""}</span>
      <span className="tiny dim">{h.industry ?? h.sector}</span>
    </button>;
  })}</div>;
}

export function ThemeAnswer({ theme }: { theme: string }) {
  const snap = useSnap();
  const nav = useNav();
  const t = snap.idx.expertise().find((x) => x.theme === theme);
  if (!t) return null;
  return <>
    <h2 className="section">Your go-to people on {theme.toLowerCase()}</h2>
    <ul className="people-list">{t.people.slice(0, 6).map((p) => (
      <li key={p.contact.id}><button onClick={() => nav.contact(p.contact.id)}>
        <Avatar name={p.contact.name} /><span className="pl-main"><b>{p.contact.name}</b> <Tie n={p.contact.tie} /><span className="small dim">{p.why}</span></span>
      </button></li>))}</ul>
  </>;
}
