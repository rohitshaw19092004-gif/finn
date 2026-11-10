/* Charts and motion primitives: count-up numbers, area chart with crosshair tooltip, stacked bars,
   distribution bar, market ticker. SVG + CSS only (no chart library); animations respect
   prefers-reduced-motion and the in-app Motion switch (html.no-motion). */
import { ReactNode, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { cls } from "../util";

export const motionOff = () =>
  typeof window !== "undefined" && (document.documentElement.classList.contains("no-motion") ||
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

/** Animated number: counts from 0 (or the previous value) to `value`. */
export function useCountUp(value: number | null | undefined, ms = 900) {
  const [v, setV] = useState<number>(motionOff() ? (value ?? 0) : 0);
  const from = useRef(0);
  useEffect(() => {
    if (value == null || Number.isNaN(value)) return;
    if (motionOff()) { setV(value); from.current = value; return; }
    const start = performance.now(), a = from.current, b = value;
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / ms), e = 1 - Math.pow(1 - k, 3);
      setV(a + (b - a) * e);
      if (k < 1) raf = requestAnimationFrame(tick); else from.current = b;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, ms]);
  return v;
}

/** Big figure with dimmed decimals, e.g. ₹2,507<span>.80</span>. */
export function Num({ value, dp = 0, prefix = "", suffix = "", className }: { value: number | null | undefined; dp?: number; prefix?: string; suffix?: string; className?: string }) {
  const v = useCountUp(value);
  if (value == null || Number.isNaN(value)) return <span className={cls("bignum", className)}>—</span>;
  const s = Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  const [int, dec] = s.split(".");
  return <span className={cls("bignum num", className)}>{v < 0 ? "−" : ""}{prefix}{int}{dec != null && <span className="dec">.{dec}</span>}{suffix && <span className="dec">{suffix}</span>}</span>;
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(ref.current);
    setW(Math.round(ref.current.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Area chart with gradient fill, line-draw animation, crosshair + tooltip, optional volume strip. */
export function AreaChart({ dates, values, height = 190, fmt = (v) => v.toFixed(1), volume, tip }: {
  dates: string[]; values: number[]; height?: number; fmt?: (v: number) => string; volume?: (number | null)[];
  tip?: (i: number) => ReactNode;
}) {
  const id = useId().replace(/:/g, "");
  const [ref, w] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const padL = 44, padR = 8, padT = 10, volH = volume ? 26 : 0, axisH = 18;
  const plotH = height - padT - volH - axisH;
  const n = values.length;
  const geo = useMemo(() => {
    if (n < 2 || !w) return null;
    const min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
    const lo = min - span * 0.08, hi = max + span * 0.08;
    const x = (i: number) => padL + (i / (n - 1)) * (w - padL - padR);
    const y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * plotH;
    const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
    const area = `${line}L${x(n - 1).toFixed(1)},${padT + plotH}L${x(0).toFixed(1)},${padT + plotH}Z`;
    const ticks = [0, 1, 2, 3].map((k) => lo + ((hi - lo) * k) / 3);
    const months: number[] = [];
    dates.forEach((d, i) => { if (i && d.slice(5, 7) !== dates[i - 1].slice(5, 7)) months.push(i); });
    const step = Math.max(1, Math.ceil(months.length / Math.max(2, Math.floor((w - padL) / 70))));
    const vs = volume ? volume.map((v) => v ?? 0).filter((v) => v > 0).sort((a, b) => a - b) : [];
    const vmax = vs.length ? vs[Math.floor(vs.length * 0.95)] * 1.05 || 1 : 1;   // ignore the odd spike so normal days stay visible
    return { x, y, line, area, ticks, months: months.filter((_, k) => k % step === 0), vmax };
  }, [values, dates, w, n, plotH, volume]); // eslint-disable-line
  const onMove = (e: React.PointerEvent) => {
    if (!geo) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left - padL) / (w - padL - padR)) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };
  const hi = hover ?? null;
  return (
    <div className="area" ref={ref} style={{ height }} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
      {geo && <svg width={w} height={height} aria-hidden>
        <defs>
          <linearGradient id={`g${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--violet)" stopOpacity="0.42" /><stop offset="100%" stopColor="var(--violet)" stopOpacity="0" />
          </linearGradient>
          <pattern id={`h${id}`} width="4" height="4" patternUnits="userSpaceOnUse"><rect width="1" height="4" fill="var(--violet)" opacity=".16" /></pattern>
        </defs>
        {geo.ticks.map((t, k) => <g key={k}><line x1={padL} x2={w - padR} y1={geo.y(t)} y2={geo.y(t)} className="grid" />
          <text x={padL - 8} y={geo.y(t) + 3} className="axis" textAnchor="end">{fmt(t)}</text></g>)}
        <path d={geo.area} fill={`url(#g${id})`} className="area-fill" />
        <path d={geo.area} fill={`url(#h${id})`} className="area-fill" />
        <path d={geo.line} className="area-line" pathLength={1} />
        {volume && volume.map((v, i) => { if (!v) return null; const hh = Math.max(1, Math.min(1, v / geo.vmax) * (volH - 4));
          return <rect key={i} x={geo.x(i) - 0.75} width={1.5} y={height - axisH - hh} height={hh} className={cls("vol", hi === i && "on")} />; })}
        {geo.months.map((i) => <text key={i} x={geo.x(i)} y={height - 4} className="axis" textAnchor="middle">{MON[+dates[i].slice(5, 7) - 1]}{dates[i].slice(5, 7) === "01" ? ` ’${dates[i].slice(2, 4)}` : ""}</text>)}
        {hi != null && <g className="xhair">
          <line x1={geo.x(hi)} x2={geo.x(hi)} y1={padT} y2={height - axisH} />
          <line x1={padL} x2={w - padR} y1={geo.y(values[hi])} y2={geo.y(values[hi])} className="dash" />
          <circle cx={geo.x(hi)} cy={geo.y(values[hi])} r={4.5} />
        </g>}
      </svg>}
      {geo && hi != null && <div className="chart-tip" style={{ left: Math.min(w - 170, Math.max(0, geo.x(hi) + 10)), top: Math.max(0, geo.y(values[hi]) - 54) }}>
        <div className="tiny dim">{new Date(dates[hi]).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</div>
        {tip ? tip(hi) : <div><b className="num">{fmt(values[hi])}</b></div>}
      </div>}
    </div>
  );
}

/** Stacked columns with value labels; columns grow in on mount (staggered). */
export function StackedBars({ labels, series, height = 150, fmt = (v: number) => String(v) }: {
  labels: string[]; series: { name: string; values: number[]; cls: string }[]; height?: number; fmt?: (v: number) => string;
}) {
  const totals = labels.map((_, i) => series.reduce((a, s) => a + (s.values[i] || 0), 0));
  const max = Math.max(1, ...totals);
  return <div className="sbars">
    <div className="sbars-cols" style={{ height }}>
      {labels.map((l, i) => <div key={l + i} className="sbar" style={{ ["--i" as string]: i }}>
        <span className="sbar-total num">{totals[i] ? fmt(totals[i]) : ""}</span>
        <div className="sbar-stack" style={{ height: `${(totals[i] / max) * 100}%` }}>
          {series.map((s) => s.values[i] ? <i key={s.name} className={s.cls} style={{ flexGrow: s.values[i] }} title={`${s.name}: ${s.values[i]}`} /> : null)}
        </div>
      </div>)}
    </div>
    <div className="sbars-x">{labels.map((l, i) => <span key={i}>{l}</span>)}</div>
  </div>;
}

/** Horizontal distribution bar (segments grow in) — e.g. portfolio weight by sector. */
export function DistBar({ parts }: { parts: { label: string; value: number; cls: string }[] }) {
  const tot = parts.reduce((a, p) => a + p.value, 0) || 1;
  return <div className="dist">{parts.map((p, i) => <span key={p.label} className={p.cls} style={{ flexGrow: p.value / tot, ["--i" as string]: i }} title={`${p.label} ${((p.value / tot) * 100).toFixed(0)}%`} />)}</div>;
}

/** Endless horizontal ticker; content is rendered twice so the loop is seamless. Pauses on hover. */
export function Ticker({ children, seconds = 60 }: { children: ReactNode; seconds?: number }) {
  return <div className="ticker" aria-label="Portfolio ticker"><div className="ticker-track" style={{ animationDuration: `${seconds}s` }}>
    <div className="ticker-set">{children}</div><div className="ticker-set" aria-hidden>{children}</div>
  </div></div>;
}
