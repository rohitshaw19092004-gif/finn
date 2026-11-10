import { useCallback, useEffect, useMemo, useState } from "react";
import { loadSnapshot, SnapCtx, Snapshot } from "./data";
import { NavCtx, Tab } from "./nav";
import type { Rules } from "./types";
import { save, store } from "./util";
import { Brief } from "./screens/Brief";
import { Ask } from "./screens/Ask";
import { People } from "./screens/People";
import { Dossier } from "./screens/Dossier";
import { ContactSheet, FiledPersonSheet, RulesSheet } from "./screens/Sheets";

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

  return (
    <SnapCtx.Provider value={snap}>
      <NavCtx.Provider value={nav}>
        <main className="app">
          {company ? <Dossier sym={company} onBack={() => { setCompany(null); try { history.back(); } catch { /* ok */ } }} />
            : tab === "brief" ? <Brief rules={rules} setRules={setRules} openRules={() => setRulesOpen(true)} />
              : tab === "ask" ? <Ask initial={askQ} />
                : <People />}
        </main>
        <nav className="tabbar">
          {([["brief", "Brief", "◉"], ["ask", "Ask", "⌕"], ["people", "People", "◎"]] as const).map(([k, l, i]) => (
            <button key={k} className={tab === k && !company ? "on" : ""} onClick={() => nav.tab(k)}><span className="ti">{i}</span>{l}</button>
          ))}
        </nav>
        <ContactSheet id={contact} onClose={closeContact} />
        <FiledPersonSheet id={filed} onClose={closeFiled} />
        <RulesSheet open={rulesOpen} onClose={() => setRulesOpen(false)} rules={rules} setRules={setRules} />
      </NavCtx.Provider>
    </SnapCtx.Provider>
  );
}
