import type { Holding, Rules } from "./types";

export interface Move { symbol: string; name: string; date: string; ret: number; z: number; volMult: number | null; reasons: string[]; close: number; held: boolean }

/** End-of-day triggers, evaluated on-device so the investor's own thresholds apply instantly. */
export function moves(holdings: Holding[], rules: Rules, sinceDate: string): Move[] {
  const out: Move[] = [];
  for (const h of holdings) {
    const { close: c, volume: v, dates } = h;
    for (let i = Math.max(61, c.length - 15); i < c.length; i++) {
      if (dates[i] < sinceDate) continue;
      const ret = c[i] / c[i - 1] - 1;
      const window = [];
      for (let k = i - 60; k < i; k++) window.push(c[k] / c[k - 1] - 1);
      const sd = Math.sqrt(window.reduce((a, x) => a + x * x, 0) / window.length) || 1e-9;
      const z = ret / sd;
      const raw = v.slice(i - 20, i).filter((x): x is number => x != null && x > 0);
      const med = [...raw].sort((a, b) => a - b)[Math.floor(raw.length / 2)] ?? 0;
      const vols = raw.filter((x) => x >= med * 0.25);   // drop special sessions (e.g. Diwali muhurat trading)
      const avg = vols.length ? vols.reduce((a, b) => a + b, 0) / vols.length : null;
      const vm = avg && v[i] ? (v[i] as number) / avg : null;
      const reasons: string[] = [];
      const priceHit = rules.priceMode === "pct" ? Math.abs(ret) * 100 >= rules.pricePct : Math.abs(z) >= rules.sigma;
      if (priceHit) reasons.push(rules.priceMode === "pct" ? `${(ret * 100).toFixed(1)}% day` : `${z.toFixed(1)}σ move`);
      if (vm != null && vm >= rules.volMult) reasons.push(`volume ${vm.toFixed(1)}× 20-day avg`);
      if (reasons.length) out.push({ symbol: h.symbol, name: h.name, date: dates[i], ret, z, volMult: vm, reasons, close: c[i], held: h.held });
    }
  }
  return out.sort((a, b) => (b.date > a.date ? 1 : b.date < a.date ? -1 : Math.abs(b.z) - Math.abs(a.z)));
}

export function dayChange(h: Holding) {
  const n = h.close.length;
  if (n < 2) return null;
  return h.close[n - 1] / h.close[n - 2] - 1;
}
