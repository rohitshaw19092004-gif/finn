export const inr = (n: number | null | undefined, dp = 0) =>
  n == null || Number.isNaN(n) ? "—" : n.toLocaleString("en-IN", { maximumFractionDigits: dp, minimumFractionDigits: dp });

export const crore = (n: number | null | undefined) => {
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 100000) return `₹${(n / 100000).toFixed(a >= 1000000 ? 1 : 2)}L Cr`;
  return `₹${inr(n)} Cr`;
};

export const pct = (n: number | null | undefined, dp = 0, sign = true) =>
  n == null || Number.isNaN(n) ? "—" : `${sign && n > 0 ? "+" : ""}${n.toFixed(dp)}%`;

export const tone = (n: number | null | undefined) => (n == null ? "" : n > 0 ? "up" : n < 0 ? "down" : "");

/** 'Sep 2026' -> 'Q2 FY27' (Indian fiscal year Apr–Mar) */
export function fq(period: string | null | undefined): string {
  if (!period) return "";
  const [mon, yr] = period.split(" ");
  const m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].indexOf(mon) + 1;
  const y = parseInt(yr, 10);
  if (!m || !y) return period;
  const fy = m >= 4 ? y + 1 : y;
  const q = m >= 4 && m <= 6 ? 1 : m >= 7 && m <= 9 ? 2 : m >= 10 ? 3 : 4;
  return `Q${q} FY${String(fy).slice(2)}`;
}

export const parseTs = (ts: string) => new Date(ts.replace(/\.\d+$/, "").replace(" ", "T") + (ts.includes("+") ? "" : "+05:30"));

export function ago(ts: string, now: Date): string {
  const d = (now.getTime() - parseTs(ts).getTime()) / 36e5;
  if (d < 1) return `${Math.max(1, Math.round(d * 60))}m ago`;
  if (d < 24) return `${Math.round(d)}h ago`;
  const days = Math.round(d / 24);
  if (days < 14) return `${days}d ago`;
  return parseTs(ts).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export const shortDate = (s: string) => new Date(s).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

export const monthsBetween = (a: string, b: Date) => {
  const d = new Date(a);
  return (b.getFullYear() - d.getFullYear()) * 12 + (b.getMonth() - d.getMonth());
};

export const CAT_LABEL: Record<string, string> = {
  results: "Results", "M&A": "M&A", fund_raise: "Fund raise", management_change: "Management", litigation: "Legal",
  insider_trading: "Insider", earnings_call: "Earnings call", investor_meetings: "Investor meet", credit_rating: "Rating",
  dividend: "Dividend", bonus_split: "Bonus/split", capex: "Capex", press_release: "News", postal_ballot: "Vote",
  agm_egm: "AGM/EGM", pledging: "Pledge", unclassified: "Routine",
};

export const cls = (...xs: (string | false | null | undefined)[]) => xs.filter(Boolean).join(" ");

export function store<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem("finn:" + key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}
export function save(key: string, v: unknown) {
  try { localStorage.setItem("finn:" + key, JSON.stringify(v)); } catch { /* private mode / sandbox */ }
}
