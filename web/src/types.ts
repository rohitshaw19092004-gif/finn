export type Tier = "act" | "glance" | "routine";

export interface Metric { label: string; value: number | null; prev: number | null; yago: number | null; qoq: number | null; yoy: number | null }
export interface ResultsCard {
  period: string; prev_period: string | null; yago_period: string | null; lender: boolean; unit: string;
  metrics: Metric[]; margin?: { now: number; qoq_pp: number | null; yoy_pp: number | null }; flags: string[];
  headline: string; source: string; verified_against_filing?: boolean;
}

export interface Filing {
  id: string; symbol: string; exchange: string; ts: string; date: string; subject: string; headline: string;
  exch_category: string; exch_subcategory: string; critical: boolean; attachment: string | null; url: string | null;
  size: number | null; category: string; kind: string; class_method: string; signals: Record<string, any>;
  score: number; tier: Tier; reasons: string[]; summary?: string; summary_by?: string; results?: ResultsCard;
  people?: string[]; doc_excerpt?: string;
}
export interface Story { id: string; symbol: string; category: string; lead: string; score: number; tier: Tier; latest: string; first: string; filings: string[]; why: string }

export interface Stint { org: string; org_id: string | null; title: string; from: string | null; to: string | null; function?: string; approx?: boolean; source?: string }
export interface Edu { school: string | null; school_id: string | null; degree: string; from?: string | null; to?: string | null; exec?: boolean }

export interface FiledPerson {
  id: string; name: string; symbol: string;
  event: { role: string; change: string; effective: string; filing: string; filing_date?: string };
  summary: string; career: Stint[]; education: Edu[]; track_record?: string[]; source: string; enrichment?: string;
}

export interface Contact {
  id: string; name: string; headline: string; tie: number; how_met: string; last_contact: string; interactions_12m: number;
  career: Stint[]; education: Edu[]; expertise: string[]; knows: { id: string; s: number }[];
}
export interface Network { investor: { id: string; name: string; headline: string; career: Stint[]; education: Edu[] }; contacts: Contact[] }

export interface Org { name: string; aliases: string[]; ticker?: string; group?: string; is_group?: boolean; themes?: string[]; peers?: string[]; suppliers?: string[]; customers?: string[]; subsidiaries?: string[] }
export interface Registry { orgs: Record<string, Org>; schools: Record<string, { name: string; aliases: string[] }> }

export interface Holding {
  symbol: string; name: string; held: boolean; weight: number | null; sector: string | null; industry: string | null;
  mcap_cr: number | null; dates: string[]; close: number[]; volume: (number | null)[]; price_source: string;
}

export interface Meta {
  generated_at: string; as_of: string | null; window_days: number; filings: number; stories: number;
  classification: Record<string, number>; doc_pass: number; llm: Record<string, any>; models: Record<string, string | string[]>;
  offline: boolean; sources: Record<string, string>;
  run?: { health: "ok" | "degraded" | "failed"; warnings: string[]; notes?: string[]; sources: Record<string, Record<string, string>>;
    documents: Record<string, number>; research: Record<string, { status: string; coverage?: string }> };
}

export type AnalysisStatus = "complete" | "partial" | "seeded" | "deferred" | "unavailable" | "failed" | "numbers_only";
export interface Analysis {
  status: AnalysisStatus; source: "live" | "seed" | "none"; as_of: string; coverage: string;
  transcripts: { period: string; url: string; status: string; model?: string | null; verified?: number; rejected?: number; error?: string }[];
  sections?: Record<string, { status: string; source: string; model?: string | null; error?: string }>;
  verified_quotes?: number; rejected?: { statement?: string; quote?: string; reason: string }[]; notes: string[];
}

export interface Note { tone: "up" | "down" | "flat"; text: string }
export interface Dossier {
  symbol: string; name: string;
  generated_by: { numbers: string; prose: string; models?: any };
  analysis?: Analysis;
  sources: { transcripts: { period: string; url: string }[]; annual_reports?: { t: string; h: string }[]; statements: string };
  snapshot: { name: string; symbol: string; basis: string; sector: string[]; about: string | null; mcap_cr: number | null; price: number | null;
    pe: number | null; roce: number | null; roe: number | null; div_yield: number | null; book_value: number | null; high_low: string | null;
    ttm_revenue: number | null; ttm_pat: number | null; opm: number | null; lender: boolean; latest_quarter: ResultsCard | null };
  trajectory: { years: string[]; revenue: (number | null)[]; operating_profit: (number | null)[]; pat: (number | null)[]; opm: (number | null)[];
    eps: (number | null)[]; cagr: Record<string, Record<string, number | null>>; notes: Note[] };
  balance_sheet: { cols: string[]; equity: number[]; debt: (number | null)[]; cwip: (number | null)[]; de: (number | null)[];
    wc: Record<string, (number | null)[]>; ratio_cols: string[]; notes: Note[] };
  cash: { cols: string[]; cfo: (number | null)[]; pat: (number | null)[]; fcf: (number | null)[]; cfo_ebitda: (number | null)[]; notes: Note[]; cfo_pat_5y?: number };
  shareholding: { cols: string[]; rows: Record<string, (number | null)[]>; notes: Note[] };
  red_flags: Note[];
  quarters: { cols: string[]; rows: Record<string, (number | null)[]> } | null;
  business_mix: { what_it_does: string; segments: { name: string; share_pct: number | null; note?: string }[]; source?: string } | null;
  guidance: { said_in: string; metric: string; statement: string; target?: string; horizon: string; quote: string; speaker?: string; kind: string;
    quote_check?: "verbatim" | "near"; page?: number; model?: string }[];
  promises: { promises: { said_in: string; metric: string; promise: string; quote?: string; outcome: string; evidence?: string; verdict: string;
      quote_check?: string; evidence_check?: "traced" | "partly traced" | "untraced" | "no figures"; verdict_note?: string }[];
    narrative_vs_numbers: { theme: string; management_says: string; numbers_say: string; agree: boolean }[]; credibility: string } | null;
  bull_bear: { bull: string[]; bear: string[]; what_would_change_my_mind?: string; untraced?: string[] } | null;
}

export interface Rules {
  windowHours: number;
  priceMode: "pct" | "sigma"; pricePct: number; sigma: number; volMult: number;
  boost: string[];   // categories I always want surfaced
  mute: string[];    // categories I never want above routine
}
