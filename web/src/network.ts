/**
 * The Network layer. Runs entirely on the device: the investor's contacts are never sent to a
 * server or a model. Inputs are the private network + public data (filings, people in filings,
 * org registry). Everything here is deterministic and explainable — each match carries the
 * evidence a human would want before picking up the phone.
 */
import type { Contact, FiledPerson, Network, Registry, Stint, Story, Filing } from "./types";

const ym = (s: string | null | undefined, end = false): number | null => {
  if (!s) return null;
  const [y, m] = s.split("-").map(Number);
  if (!y) return null;
  return y * 12 + (m ? m - 1 : end ? 11 : 0);
};
const NOW = (asOf: Date) => asOf.getFullYear() * 12 + asOf.getMonth();
const span = (s: Stint, asOf: Date): [number | null, number | null] => [ym(s.from), s.to ? ym(s.to, true) : s.from ? NOW(asOf) : null];
const yrs = (s: Stint) => `${s.from ? s.from.slice(0, 4) : "?"}–${s.to ? s.to.slice(0, 4) : s.from ? "now" : "?"}`;

export interface Evidence { kind: "colleague" | "group" | "alumni-org" | "classmate" | "alma-mater"; text: string; short: string; weight: number; org?: string }
export interface Path { contact: Contact; via?: Contact; evidence: Evidence[]; strength: number; label: string }
export interface CallPick { contact: Contact; reason: string; score: number; flag?: string; relation: "insider" | "peer" | "supplier" | "customer" | "theme" | "group" }

/** Some events need a specialist more than an insider. */
const EVENT_THEMES: Record<string, string[]> = {
  litigation: ["Corporate & insolvency law"],
  "M&A": ["Corporate & insolvency law", "Real estate / REITs", "Strategy consulting"],
  credit_rating: ["Credit risk"], fund_raise: ["Capital markets"], pledging: ["Credit risk"],
};
const EVENT_WORDS: Record<string, RegExp> = { litigation: /insolven|nclt|nclat|litig|dispute|restructur/i, "M&A": /m&a|merger|real estate|transaction/i };
const EVENT_NOUN: Record<string, string> = { litigation: "ruling", "M&A": "deal", credit_rating: "rating action", fund_raise: "raise", pledging: "pledge" };

export class NetworkIndex {
  byId = new Map<string, Contact>();
  constructor(public net: Network, public reg: Registry, public asOf: Date) {
    net.contacts.forEach((c) => this.byId.set(c.id, c));
  }

  org(id: string | null | undefined) { return id ? this.reg.orgs[id] : undefined; }
  orgName(id: string | null | undefined, fallback = "") { return this.org(id)?.name ?? fallback; }
  groupOf(id: string | null | undefined) { const o = this.org(id); return o?.is_group ? id : o?.group; }

  /** How does contact c overlap with a person named in a filing? */
  overlaps(p: FiledPerson, c: Contact): Evidence[] {
    const ev: Evidence[] = [];
    for (const t of p.career) {
      for (const s of c.career) {
        if (!t.org_id || !s.org_id) continue;
        const same = t.org_id === s.org_id;
        const tg = this.groupOf(t.org_id), sg = this.groupOf(s.org_id);
        const group = !same && tg && sg && tg === sg;
        if (!same && !group) continue;
        const [a0, a1] = span(t, this.asOf), [b0, b1] = span(s, this.asOf);
        const org = this.orgName(s.org_id, s.org);
        if (a0 != null && a1 != null && b0 != null && b1 != null) {
          const m = Math.min(a1, b1) - Math.max(a0, b0) + 1;
          if (m > 0) {
            const tOrg = this.orgName(t.org_id, t.org);
            const last = p.name.split(" ").slice(-1)[0];
            const ov = `~${Math.round(m / 12) || "<1"} yr`;
            ev.push(same
              ? { kind: "colleague", org, weight: 3 + Math.min(2, m / 24), short: `${org} ${yrs(s)} — ${ov} overlap with ${last}`,
                  text: `${c.name.split(" ")[0]} was at ${org} (${yrs(s)}, ${s.title}) while ${last} was ${t.title} (${yrs(t)}) — ${ov} overlap` }
              : { kind: "group", org, weight: 1.6, short: `${org} ${yrs(s)} — same group as ${last}'s ${tOrg}`,
                  text: `Overlapping years in the ${this.orgName(tg!)} — ${c.name.split(" ")[0]} at ${org} (${yrs(s)}), ${last} at ${tOrg} (${yrs(t)})` });
          } else if (same) {
            ev.push({ kind: "alumni-org", org, weight: 0.8, short: `${org} alumni, different years`, text: `Both ${org} alumni, different years (${yrs(s)} vs ${yrs(t)})` });
          }
        } else if (same) {
          ev.push({ kind: "alumni-org", org, weight: 1.4, short: `${org} ${yrs(s)} — dates undisclosed`,
            text: `Both worked at ${org} — ${p.name.split(" ").slice(-1)[0]}'s dates not disclosed (${c.name.split(" ")[0]}: ${yrs(s)})` });
        }
      }
    }
    for (const e of p.education) {
      for (const f of c.education) {
        if (!e.school_id || e.school_id !== f.school_id) continue;
        const school = this.reg.schools[e.school_id]?.name ?? e.school ?? "";
        const a0 = ym(e.from ?? null), a1 = ym(e.to ?? null, true), b0 = ym(f.from ?? null), b1 = ym(f.to ?? null, true);
        if (a0 && a1 && b0 && b1 && Math.min(a1, b1) >= Math.max(a0, b0)) ev.push({ kind: "classmate", weight: 2.5, short: `${school}, same years`, text: `Overlapped at ${school}` });
        else ev.push({ kind: "alma-mater", weight: e.exec ? 0.4 : 0.9, short: `${school} alumni${e.exec ? " (exec programme)" : ""}`, text: `Same alma mater: ${school}${e.exec ? " (exec programme)" : ""}` });
      }
    }
    // keep the best piece of evidence per org/school; a direct colleague overlap makes the group-level one redundant
    const best = new Map<string, Evidence>();
    for (const x of ev) { const k = x.org ?? x.text; if (!best.has(k) || best.get(k)!.weight < x.weight) best.set(k, x); }
    const hasColleague = [...best.values()].some((x) => x.kind === "colleague");
    return [...best.values()].filter((x) => !(hasColleague && x.kind === "group")).sort((a, b) => b.weight - a.weight);
  }

  /** Direct lines and warm-intro paths from the investor to a person named in a filing. */
  pathsTo(p: FiledPerson): Path[] {
    const out: Path[] = [];
    for (const c of this.net.contacts) {
      const ev = this.overlaps(p, c);
      if (!ev.length) continue;
      const evw = ev[0].weight + ev.slice(1).reduce((a, b) => a + b.weight * 0.3, 0);
      out.push({ contact: c, evidence: ev, strength: evw * (0.5 + c.tie / 5), label: c.tie >= 3 ? "You know them well" : "Weak tie" });
      // warm intro: a strong tie of yours who knows this weak-tie contact
      if (c.tie <= 2) {
        for (const b of this.net.contacts) {
          const k = b.knows.find((x) => x.id === c.id);
          if (b.id !== c.id && k && b.tie >= 4 && k.s >= 3) {
            out.push({ contact: c, via: b, evidence: ev, strength: evw * (0.4 + Math.min(b.tie, k.s) / 6), label: `Warm intro via ${b.name}` });
          }
        }
      }
    }
    const intro = new Set(out.filter((x) => x.via).map((x) => x.contact.id));
    return out.filter((x) => x.via || !intro.has(x.contact.id) || x.contact.tie >= 3).sort((a, b) => b.strength - a.strength);
  }

  related(sym: string): { insider: string[]; peers: string[]; suppliers: string[]; customers: string[]; group?: string; themes: string[] } {
    const o = this.org(sym);
    const peers = new Set<string>(o?.peers ?? []);
    Object.entries(this.reg.orgs).forEach(([id, x]) => x.peers?.includes(sym) && peers.add(id));
    const subs = o?.subsidiaries ?? [];
    return { insider: [sym, ...subs], peers: [...peers], suppliers: o?.suppliers ?? [], customers: o?.customers ?? [], group: o?.group, themes: o?.themes ?? [] };
  }

  /** Who should I call about company `sym` (optionally about a kind of event)? Ranked, with the reason and any compliance flag. */
  whoToCall(sym: string, limit = 3, category?: string): CallPick[] {
    const r = this.related(sym);
    const name = this.orgName(sym, sym);
    const picks: CallPick[] = [];
    for (const c of this.net.contacts) {
      let best: CallPick | null = null;
      const consider = (p: CallPick) => { if (!best || p.score > best.score) best = p; };
      for (const s of c.career) {
        if (!s.org_id) continue;
        const current = !s.to;
        const yearsIn = ((ym(s.to, true) ?? NOW(this.asOf)) - (ym(s.from) ?? NOW(this.asOf))) / 12;
        const recency = s.to ? Math.max(0, 1 - (NOW(this.asOf) - (ym(s.to, true) ?? 0)) / 120) : 1;
        const senior = /head|director|chief|vp|president|lead|gm|partner/i.test(s.title) ? 0.6 : 0;
        if (r.insider.includes(s.org_id)) {
          consider({ contact: c, relation: "insider", score: 5 + Math.min(1.5, yearsIn / 5) + recency + senior,
            reason: `${current ? "Works at" : "Spent " + Math.max(1, Math.round(yearsIn)) + " yrs at"} ${this.orgName(s.org_id)} — ${s.title} (${yrs(s)})`,
            flag: current ? "Current employee — stick to public information" : undefined });
        } else if (r.peers.includes(s.org_id)) {
          consider({ contact: c, relation: "peer", score: 3 + recency + senior * 0.5,
            reason: `${current ? "Now at" : "Was at"} competitor ${this.orgName(s.org_id)} — ${s.title} (${yrs(s)})`,
            flag: current ? `Currently at a competitor (${this.orgName(s.org_id)}) — avoid anything confidential` : undefined });
        } else if (r.suppliers.includes(s.org_id) || r.customers.includes(s.org_id)) {
          const sup = r.suppliers.includes(s.org_id);
          consider({ contact: c, relation: sup ? "supplier" : "customer", score: 2.6 + recency,
            reason: `${sup ? "Supplier" : "Customer"}-side view: ${s.title} at ${this.orgName(s.org_id)} (${yrs(s)})` });
        } else if (r.group && this.groupOf(s.org_id) === r.group) {
          consider({ contact: c, relation: "group", score: 1.6 + recency * 0.5,
            reason: `Same group (${this.orgName(r.group)}): ${s.title} at ${this.orgName(s.org_id)} (${yrs(s)})` });
        }
      }
      if (!best) {
        const shared = c.expertise.filter((t) => r.themes.includes(t));
        if (shared.length) consider({ contact: c, relation: "theme", score: 1.4 + shared.length * 0.3, reason: `Go-to on ${shared.join(", ").toLowerCase()}` });
      }
      // regulatory cases at a pharma company need a drug-regulation specialist, not a lawyer
      const themes = category ? [...(EVENT_THEMES[category] ?? []), ...(category === "litigation" ? r.themes.filter((t) => /regulation/i.test(t)) : [])] : [];
      const spec = themes.filter((t) => c.expertise.includes(t));
      const exact = category && EVENT_WORDS[category]?.test(c.headline + " " + c.career.map((x) => x.title).join(" ")) ? 1.5 : 0;
      if (spec.length) consider({ contact: c, relation: "theme", score: 5.2 + c.tie * 0.15 + exact,
        reason: `Specialist (${spec[0].toLowerCase()}) — can read the ${EVENT_NOUN[category!] ?? "event"} for you` });
      if (best) { const b = best as CallPick; b.score *= 0.6 + c.tie * 0.1; picks.push(b); }
    }
    void name;
    return picks.sort((a, b) => b.score - a.score).slice(0, limit);
  }

  /** Expertise map: theme -> people, scored by stated expertise + years in orgs carrying that theme. */
  expertise(): { theme: string; people: { contact: Contact; score: number; why: string }[] }[] {
    const map = new Map<string, Map<string, { contact: Contact; score: number; why: [string, number][] }>>();
    const add = (theme: string, c: Contact, w: number, why: string) => {
      if (!map.has(theme)) map.set(theme, new Map());
      const m = map.get(theme)!;
      const cur = m.get(c.id) ?? { contact: c, score: 0, why: [] };
      cur.score += w; if (!cur.why.some((x) => x[0] === why)) cur.why.push([why, why === "self-described" ? 0 : w]); m.set(c.id, cur);
    };
    for (const c of this.net.contacts) {
      c.expertise.forEach((t) => add(t, c, 1, "self-described"));
      for (const s of c.career) {
        const o = this.org(s.org_id); if (!o?.themes) continue;
        const y = ((ym(s.to, true) ?? NOW(this.asOf)) - (ym(s.from) ?? NOW(this.asOf))) / 12;
        o.themes.forEach((t) => add(t, c, Math.min(2, y / 4), `${Math.max(1, Math.round(y))} yrs at ${o.name}`));
      }
    }
    return [...map.entries()].map(([theme, m]) => ({
      theme, people: [...m.values()].map((x) => {
        const ws = x.why.sort((a, b) => b[1] - a[1]);
        const why = (ws.filter((w) => w[1] > 0).length ? ws.filter((w) => w[1] > 0) : ws).slice(0, 2).map((w) => w[0]).join(" · ");
        return { contact: x.contact, score: x.score * (0.7 + x.contact.tie * 0.06), why: why === "self-described" ? x.contact.headline : why };
      })
        .sort((a, b) => b.score - a.score),
    })).sort((a, b) => b.people.length - a.people.length);
  }

  daysSince(c: Contact) { return Math.round((this.asOf.getTime() - new Date(c.last_contact).getTime()) / 864e5); }

  /** Coverage of a set of companies: direct insiders, competitor views, nothing. */
  coverage(symbols: string[]) {
    return symbols.map((sym) => {
      const picks = this.whoToCall(sym, 10);
      return { sym, insiders: picks.filter((p) => p.relation === "insider"), peers: picks.filter((p) => p.relation === "peer" || p.relation === "supplier" || p.relation === "customer"), other: picks.filter((p) => p.relation === "theme" || p.relation === "group") };
    });
  }

  /** Natural reasons to reconnect: a dormant contact whose (ex-)company or competitor is in the news. */
  reconnect(stories: Story[], filings: Map<string, Filing>, minDays = 120) {
    const out: { contact: Contact; story: Story; filing: Filing; relation: string; days: number }[] = [];
    const used = new Map<string, number>();
    const ranked = [...stories].sort((a, b) => b.score - a.score);
    for (const c of [...this.net.contacts].sort((a, b) => b.tie - a.tie)) {
      const days = this.daysSince(c);
      if (days < minDays) continue;
      for (const st of ranked) {
        if (st.tier === "routine" || (used.get(st.symbol) ?? 0) >= 1) continue;
        const pick = this.whoToCall(st.symbol, 20).find((p) => p.contact.id === c.id && (p.relation === "insider" || p.relation === "peer"));
        if (pick) { used.set(st.symbol, 1); out.push({ contact: c, story: st, filing: filings.get(st.lead)!, relation: pick.reason, days }); break; }
      }
    }
    // a close contact you've let go quiet is the better nudge
    return out.sort((a, b) => (b.contact.tie * 20 + b.story.score) - (a.contact.tie * 20 + a.story.score));
  }
}
