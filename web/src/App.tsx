import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { loadSnapshot, SnapCtx, Snapshot } from "./data";
import { NavCtx, Tab } from "./nav";
import type { Rules } from "./types";
import { save, store } from "./util";
import { Brief } from "./screens/Brief";
import { Ask } from "./screens/Ask";
import { People } from "./screens/People";
import { Dossier } from "./screens/Dossier";
import { ContactSheet, FiledPersonSheet, RulesSheet } from "./screens/Sheets";
import { Icon } from "./ui/kit";
import { Ticker } from "./ui/charts";
import { Spark } from "./ui/kit";
import { dayChange } from "./alerts";
import { cls, pct, tone } from "./util";

const DEFAULT_RULES: Rules = { windowHours: 24, priceMode: "pct", pricePct: 4, sigma: 2.5, volMult: 2, boost: [], mute: [] };

export default function App() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(() => (location.hash.slice(1) as Tab) || "brief");
  const [company, setCompany] = useState<string | null>(null);
  const [contact, setContact] = useState<string | null>(null);
  const [filed, setFiled] = useState<string | null>(null);
  const [askQ, setAskQ] = useState<string | undefined>();
  const [rulesOpen, setRulesOpen] = useState(false);
  const [rules, setRulesState] = useState<Rules>(() => ({ ...DEFAULT_RULES, ...store("rules", {}) }));
  const [collapsed, setCollapsed] = useState<boolean>(() => store("sideCollapsed", false));
  const [q, setQ] = useState("");
  const [motion, setMotion] = useState<boolean>(() => store("motion", true));
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => { document.documentElement.classList.toggle("no-motion", !motion); save("motion", motion); }, [motion]);
  useEffect(() => {   // ⌘K / Ctrl+K focuses search
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); searchRef.current?.focus(); } };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  const setRules = (r: Rules) => { setRulesState(r); save("rules", r); };

  useEffect(() => { loadSnapshot().then(setSnap).catch((e) => setErr(String(e))); }, []);
  useEffect(() => { try { history.replaceState(null, "", "#" + tab); } catch { /* sandboxed frame */ } }, [tab]);
  useEffect(() => {
    const onPop = () => { setCompany(null); setContact(null); setFiled(null); };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const push = () => { try { history.pushState(null, "", location.hash); } catch { /* sandboxed frame */ } };
  const nav = useMemo(() => ({
    tab: (t: Tab) => { setCompany(null); setContact(null); setFiled(null); setTab(t); window.scrollTo(0, 0); },
    company: (s: string) => { push(); setContact(null); setFiled(null); setCompany(s); },
    contact: (id: string) => { setFiled(null); setContact(id); },
    filedPerson: (id: string) => { setContact(null); setFiled(id); },
    ask: (q: string) => { setCompany(null); setTab("ask"); setAskQ(q + " "); },
  }), []);
  const closeContact = useCallback(() => setContact(null), []);
  const closeFiled = useCallback(() => setFiled(null), []);

  if (err) return <div className="boot">Couldn't load FINN's data: {err}</div>;
  if (!snap) return <div className="boot"><div className="logo">FINN</div><div className="pulse" /></div>;

  const TABS = [["brief", "Brief", "brief"], ["ask", "Ask", "ask"], ["people", "People", "people"]] as const;
  const run = snap.meta.run;
  const title = company ? company : TABS.find((t) => t[0] === tab)?.[1];
  const research = snap.holdings.filter((h) => !h.held);
  const recentAct = snap.stories.filter((s) => s.tier === "act" && (snap.asOf.getTime() - new Date(s.latest.slice(0, 10)).getTime()) / 864e5 <= 3).length;
  const ist = new Date(Date.now() + (330 + new Date().getTimezoneOffset()) * 60000);
  const mins = ist.getHours() * 60 + ist.getMinutes();
  const open = ist.getDay() > 0 && ist.getDay() < 6 && mins >= 555 && mins <= 930;
  const view = company ? "d-" + company : tab;
  return (
    <SnapCtx.Provider value={snap}>
      <NavCtx.Provider value={nav}>
        <div className={collapsed ? "shell collapsed" : "shell"}>
          <aside className="side">
            <div className="side-logo"><span className="mark"><Icon name="spark4" size={18} /></span><span className="side-label">FINN</span>
              <button className="side-collapse" onClick={() => { setCollapsed(!collapsed); save("sideCollapsed", !collapsed); }} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
                <Icon name={collapsed ? "expand" : "collapse"} size={15} /></button></div>
            <nav className="side-nav">
              {TABS.map(([k, l, i]) => (
                <button key={k} className={tab === k && !company ? "on" : ""} onClick={() => nav.tab(k)} title={l}><Icon name={i} /><span className="side-label">{l}</span>
                  {k === "brief" && recentAct > 0 && <span className="side-badge side-label">{recentAct}</span>}</button>))}
              <div className="side-group side-label"><Icon name="folder" /><span>Research list</span></div>
              <div className="side-tree side-label">{research.map((h) => <button key={h.symbol} className={company === h.symbol ? "on" : ""} onClick={() => nav.company(h.symbol)}>{h.symbol}</button>)}</div>
            </nav>
            <div className="side-sep" />
            <nav className="side-nav">
              <button onClick={() => setRulesOpen(true)} title="Watch rules"><Icon name="rules" /><span className="side-label">Watch rules</span></button>
            </nav>
            <div className="side-card side-label">
              <div className="row gap"><Icon name="health" size={15} /><b>Data refresh</b></div>
              <div className={cls("small", run?.health === "ok" ? "up" : run ? "warn-t" : "dim")}>{run ? run.health.toUpperCase() : "—"} · {snap.asOf.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</div>
              <div className="tiny dim">{snap.meta.filings} filings · {snap.holdings.filter((h) => h.held).length} holdings · network stays on this device</div>
            </div>
            <label className="side-toggle side-label"><span className="row gap"><Icon name="motion" size={15} />Motion</span>
              <input type="checkbox" checked={motion} onChange={(e) => setMotion(e.target.checked)} /><i /></label>
          </aside>
          <div className="main">
            <div className="market-bar">
              <span className={cls("mkt", open ? "open" : "closed")}><i />{open ? "Market is open" : "Market is closed"}<span className="dim"> · EOD {snap.meta.as_of ?? "—"}</span></span>
              <Ticker seconds={Math.max(40, snap.holdings.length * 3)}>
                {snap.holdings.map((h) => { const ch = dayChange(h); return (
                  <button key={h.symbol} className="tick" onClick={() => nav.company(h.symbol)}>
                    <b>{h.symbol}</b><Spark data={h.close.slice(-20)} w={42} h={14} /><span className={cls("num", tone(ch))}>{ch != null ? pct(ch * 100, 2) : ""}</span>
                  </button>); })}
              </Ticker>
            </div>
            <header className="topbar">
              <div className="crumbs"><span className="dim">FINN</span><span className="dim">/</span><b>{title}</b></div>
              <span className="chip-stat"><Icon name="brief" size={13} /><span className="dim">Book</span><b>{snap.holdings.filter((h) => h.held).length} stocks</b></span>
              <button className="sq violet" title="Ask FINN" onClick={() => nav.tab("ask")}><Icon name="plus" size={15} /></button>
              <button className="sq" title="People" onClick={() => nav.tab("people")}><Icon name="people" size={15} /></button>
              <form className="top-search" onSubmit={(e) => { e.preventDefault(); if (q.trim()) { nav.ask(q.trim()); setQ(""); searchRef.current?.blur(); } }}>
                <Icon name="ask" size={14} /><input ref={searchRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search a company, person or theme…" aria-label="Ask FINN" />
                <kbd>⌘K</kbd>
              </form>
              <button className="sq bell" title={`${recentAct} stories need you (last 3 days)`} onClick={() => nav.tab("brief")}><Icon name="bell" size={15} />{recentAct > 0 && <i>{recentAct}</i>}</button>
              <span className="who"><span className="avatar-sm">DI</span>Demo investor</span>
            </header>
            <main className="app" key={view}>
              {company ? <Dossier sym={company} onBack={() => { setCompany(null); try { history.back(); } catch { /* ok */ } }} />
                : tab === "brief" ? <Brief rules={rules} setRules={setRules} openRules={() => setRulesOpen(true)} />
                  : tab === "ask" ? <Ask initial={askQ} />
                    : <People />}
            </main>
          </div>
        </div>
        <nav className="tabbar">
          {TABS.map(([k, l, i]) => (
            <button key={k} className={tab === k && !company ? "on" : ""} onClick={() => nav.tab(k)}><span className="ti"><Icon name={i} size={19} /></span>{l}</button>
          ))}
        </nav>
        <ContactSheet id={contact} onClose={closeContact} />
        <FiledPersonSheet id={filed} onClose={closeFiled} />
        <RulesSheet open={rulesOpen} onClose={() => setRulesOpen(false)} rules={rules} setRules={setRules} />
      </NavCtx.Provider>
    </SnapCtx.Provider>
  );
}
