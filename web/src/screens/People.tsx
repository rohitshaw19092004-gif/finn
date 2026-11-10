import { useMemo, useRef, useState } from "react";
import { useSnap } from "../data";
import { useNav } from "../nav";
import { Avatar, Chip, Tie } from "../ui/kit";
import { cls, monthsBetween } from "../util";
import { ThemeAnswer } from "./Ask";
import type { Contact, Network } from "../types";

export function People() {
  const snap = useSnap();
  const nav = useNav();
  const { idx } = snap;
  const [theme, setTheme] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const held = snap.holdings.filter((h) => h.held).map((h) => h.symbol);
  const themes = useMemo(() => idx.expertise(), [idx]);
  const cov = useMemo(() => idx.coverage(held), [idx]); // eslint-disable-line
  const recent = snap.stories.filter((s) => (snap.asOf.getTime() - new Date(s.latest).getTime()) / 864e5 <= 14);
  const nudges = useMemo(() => idx.reconnect(recent, snap.byId), [idx]); // eslint-disable-line
  const reach = useMemo(() => snap.people.map((p) => ({ p, paths: idx.pathsTo(p) })).filter((x) => x.paths.length)
    .sort((a, b) => b.paths[0].strength - a.paths[0].strength), [snap.people, idx]);
  const blind = cov.filter((c) => !c.insiders.length);
  const shown = snap.network.contacts.filter((c) => !filter || (c.name + c.headline + c.career.map((s) => s.org).join(" ")).toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="screen people">
      <header className="top">
        <div className="eyebrow">Network · {snap.network.contacts.length} people · stays on this device</div>
        <h1 className="headline">What your network noticed.</h1>
      </header>

      {reach.length > 0 && <section className="block">
        <h2 className="section">Lines into this month's leadership changes</h2>
        {reach.slice(0, 4).map(({ p, paths }) => (
          <button key={p.id} className="notice" onClick={() => nav.filedPerson(p.id)}>
            <Avatar name={p.name} />
            <span><b>{p.name}</b> <span className="dim">· {p.event.role}, {p.symbol}</span><br />
              <span className="small">{paths[0].via ? <>Warm intro via <b>{paths[0].via.name}</b> → {paths[0].contact.name}. </> : <><b>{paths[0].contact.name}</b>: </>}{paths[0].evidence[0].short}.</span></span>
          </button>))}
      </section>}

      {nudges.length > 0 && <section className="block">
        <h2 className="section">Natural reasons to reconnect</h2>
        {nudges.slice(0, 5).map((n) => (
          <button key={n.contact.id} className="notice" onClick={() => nav.contact(n.contact.id)}>
            <Avatar name={n.contact.name} />
            <span><b>{n.contact.name}</b> <span className="dim">· quiet for {Math.round(n.days / 30)} months</span><br />
              <span className="small">{n.story.symbol}: {(n.filing.results?.headline ? `results — ${n.filing.results.headline}` : n.filing.summary ?? n.filing.headline).replace(/\.$/, "")}. <span className="dim">{n.relation}.</span></span></span>
          </button>))}
      </section>}

      <section className="block">
        <h2 className="section">Portfolio coverage</h2>
        <div className="coverage">{cov.map((c) => (
          <button key={c.sym} className={cls("cov", c.insiders.length ? "in" : c.peers.length ? "peer" : "none")} onClick={() => nav.ask(`who knows ${c.sym}`)}>
            <b>{c.sym}</b><span>{c.insiders.length ? `${c.insiders.length} insider${c.insiders.length > 1 ? "s" : ""}` : c.peers.length ? "peer view" : "blind spot"}</span>
          </button>))}</div>
        {blind.length > 0 && <p className="small">
          <b>Blind spots:</b> nobody you know has worked at {blind.map((b) => b.sym).join(", ")}. {blind.filter((b) => b.peers.length).slice(0, 2).map((b) => `Closest on ${b.sym}: ${b.peers[0].contact.name} (${b.peers[0].reason.toLowerCase()})`).join(". ")}.
        </p>}
      </section>

      <section className="block">
        <h2 className="section">Expertise map</h2>
        <div className="chips wrap">{themes.filter((t) => t.people.length > 1).slice(0, 16).map((t) => (
          <Chip key={t.theme} active={theme === t.theme} onClick={() => setTheme(theme === t.theme ? null : t.theme)}>{t.theme} <span className="dim">{t.people.length}</span></Chip>))}</div>
        {theme && <div className="answer"><ThemeAnswer theme={theme} /></div>}
      </section>

      <section className="block">
        <div className="row between"><h2 className="section">Everyone</h2>
          <span className="row gap">
            <button className="link small" onClick={() => fileRef.current?.click()}>Import LinkedIn CSV</button>
            {hasOwn() && <button className="link small" onClick={() => { try { localStorage.removeItem("finn:network"); } catch { /* */ } location.reload(); }}>Reset demo</button>}
          </span></div>
        <input ref={fileRef} type="file" accept=".csv,.json" hidden onChange={(e) => e.target.files?.[0] && importNetwork(e.target.files[0], snap.network, snap.registry)} />
        <input className="filter" placeholder="Filter by name, company…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <ul className="people-list">{shown.map((c) => (
          <li key={c.id}><button onClick={() => nav.contact(c.id)}>
            <Avatar name={c.name} /><span className="pl-main"><b>{c.name}</b> <Tie n={c.tie} /><span className="small dim">{c.headline}</span></span>
            <span className="tiny dim">{monthsBetween(c.last_contact, snap.asOf)}mo</span>
          </button></li>))}</ul>
        <p className="tiny dim">Demo network is synthetic (fictional people, real employers) so overlaps with real filings can be shown. Your own network never leaves this device.</p>
      </section>
    </div>
  );
}

/** LinkedIn 'Connections.csv' export -> FINN contacts (consented, ToS-friendly way to seed a real network). */
async function importNetwork(file: File, current: Network, reg: { orgs: Record<string, { name: string; aliases: string[] }> }) {
  const text = await file.text();
  let next: Network;
  if (file.name.endsWith(".json")) next = JSON.parse(text);
  else {
    const lines = text.split(/\r?\n/).filter((l) => l.trim());
    const hi = lines.findIndex((l) => /first name/i.test(l));
    const head = parseCsv(lines[hi]);
    const col = (n: string) => head.findIndex((h) => h.toLowerCase() === n);
    const resolve = (company: string) => {
      const c = company.toLowerCase().replace(/\b(ltd|limited|pvt|private|inc)\b\.?/g, "").trim();
      for (const [id, o] of Object.entries(reg.orgs)) if ([o.name, ...o.aliases].some((a) => a.toLowerCase() === c)) return id;
      return null;
    };
    const contacts: Contact[] = lines.slice(hi + 1).map((l, i) => {
      const r = parseCsv(l);
      const company = r[col("company")] ?? "";
      return { id: "li" + i, name: `${r[col("first name")] ?? ""} ${r[col("last name")] ?? ""}`.trim(), headline: `${r[col("position")] ?? ""}${company ? ", " + company : ""}`,
        tie: 2, how_met: "LinkedIn connection", last_contact: new Date(r[col("connected on")] || Date.now()).toISOString().slice(0, 10), interactions_12m: 0,
        career: company ? [{ org: company, org_id: resolve(company), title: r[col("position")] ?? "", from: null, to: null }] : [], education: [], expertise: [], knows: [] };
    }).filter((c) => c.name);
    next = { investor: current.investor, contacts };
  }
  try { localStorage.setItem("finn:network", JSON.stringify(next)); location.reload(); }
  catch { alertBox("This browser blocks local storage, so an imported network can't be kept here."); }
}

const hasOwn = () => { try { return !!localStorage.getItem("finn:network"); } catch { return false; } };
const alertBox = (msg: string) => { const d = document.createElement("div"); d.className = "toast"; d.textContent = msg; document.body.appendChild(d); setTimeout(() => d.remove(), 4000); };

function parseCsv(line: string): string[] {
  const out: string[] = []; let cur = "", q = false;
  for (const ch of line) { if (ch === '"') q = !q; else if (ch === "," && !q) { out.push(cur); cur = ""; } else cur += ch; }
  out.push(cur);
  return out.map((s) => s.trim());
}
