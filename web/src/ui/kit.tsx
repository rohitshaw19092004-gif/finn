import { ReactNode, useEffect } from "react";
import { cls } from "../util";

export function Spark({ data, w = 64, h = 20, stroke, fluid }: { data: number[]; w?: number; h?: number; stroke?: string; fluid?: boolean }) {
  const xs = data.filter((x) => x != null && !Number.isNaN(x));
  if (xs.length < 2) return <svg width={w} height={h} />;
  const min = Math.min(...xs), max = Math.max(...xs), r = max - min || 1;
  const pts = xs.map((v, i) => `${((i / (xs.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / r) * (h - 4)).toFixed(1)}`).join(" ");
  const up = xs[xs.length - 1] >= xs[0];
  return (
    <svg width={fluid ? "100%" : w} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio={fluid ? "none" : undefined} aria-hidden className="spark">
      <polyline points={pts} fill="none" stroke={stroke ?? (up ? "var(--up)" : "var(--down)")} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function Bars({ labels, series, height = 96, fmt }: {
  labels: string[]; series: { name: string; values: (number | null)[]; color: string }[]; height?: number; fmt?: (n: number) => string;
}) {
  const all = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  const max = Math.max(1, ...all.map(Math.abs));
  const hasNeg = all.some((v) => v < 0);
  const zero = hasNeg ? height / 2 : height;
  const n = labels.length, gw = 100 / n, bw = (gw * 0.72) / series.length;
  return (
    <div className="bars">
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ height }} aria-hidden>
        <line x1="0" x2="100" y1={zero} y2={zero} stroke="var(--rule)" strokeWidth="0.4" vectorEffect="non-scaling-stroke" />
        {labels.map((_, i) => series.map((s, k) => {
          const v = s.values[i];
          if (v == null) return null;
          const hh = (Math.abs(v) / max) * (hasNeg ? height / 2 - 2 : height - 2);
          return <rect key={i + "-" + k} x={i * gw + gw * 0.14 + k * bw} width={bw * 0.92} y={v >= 0 ? zero - hh : zero} height={hh} fill={s.color} rx="0.6" />;
        }))}
      </svg>
      <div className="bars-x">{labels.map((l, i) => <span key={i}>{l}</span>)}</div>
      {fmt && <div className="bars-legend">{series.map((s) => <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>)}</div>}
    </div>
  );
}

export function Chip({ children, active, onClick, tone }: { children: ReactNode; active?: boolean; onClick?: () => void; tone?: string }) {
  return <button className={cls("chip", active && "on", tone)} onClick={onClick} type="button">{children}</button>;
}

export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title?: ReactNode; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", k); document.body.style.overflow = ""; };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="sheet-wrap" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal>
        <div className="sheet-grip" />
        <div className="sheet-head"><div className="sheet-title">{title}</div><button className="x" onClick={onClose} aria-label="Close">✕</button></div>
        <div className="sheet-body">{children}</div>
      </div>
    </div>
  );
}

export function Tie({ n }: { n: number }) {
  return <span className="tie" title={`Tie strength ${n}/5`}>{[1, 2, 3, 4, 5].map((i) => <i key={i} className={i <= n ? "on" : ""} />)}</span>;
}

const VERDICT: Record<string, [string, string]> = {
  delivered: ["Delivered", "up"], partly: ["Partly", "warn"], missed: ["Missed", "down"],
  pending: ["Pending", "muted"], "moved goalposts": ["Moved goalposts", "warn"], unknown: ["Unknown", "muted"],
};
export const Verdict = ({ v }: { v: string }) => { const [t, c] = VERDICT[v] ?? [v, "muted"]; return <span className={cls("verdict", c)}>{t}</span>; };

export function Avatar({ name, size = 28 }: { name: string; size?: number }) {
  const ini = name.replace(/^(Dr\.|Prof\.)\s*/, "").split(" ").map((x) => x[0]).slice(0, 2).join("");
  let h = 0; for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.38, background: `hsl(${h} 22% 20%)`, color: `hsl(${h} 50% 78%)` }}>{ini}</span>;
}

export function Empty({ children }: { children: ReactNode }) { return <div className="empty">{children}</div>; }

const ICONS: Record<string, string> = {
  brief: "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z",
  ask: "M11 4a7 7 0 1 0 0 14a7 7 0 0 0 0-14zM20 20l-4.3-4.3",
  people: "M9 11a4 4 0 1 0 0-8a4 4 0 0 0 0 8zM2 21c0-3.9 3.1-7 7-7s7 3.1 7 7M17 11a3 3 0 1 0 0-6M22 21c0-3-1.8-5.5-4.5-6.5",
  rules: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M16 4v4M10 10v4M18 16v4",
  play: "M7 4l13 8l-13 8z", stop: "M6 6h12v12H6z",
  collapse: "M15 6l-6 6l6 6M20 4v16", expand: "M9 6l6 6l-6 6M4 4v16",
  ext: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  health: "M3 12h4l3-8l4 16l3-8h4",
  spark4: "M12 2c.6 4.6 2.4 6.8 7 7.5c-4.6.7-6.4 2.9-7 7.5c-.6-4.6-2.4-6.8-7-7.5c4.6-.7 6.4-2.9 7-7.5zM19 15c.3 2 1 3 3 3.3c-2 .3-2.7 1.3-3 3.3c-.3-2-1-3-3-3.3c2-.3 2.7-1.3 3-3.3z",
  plus: "M12 5v14M5 12h14", bell: "M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8M10 20a2 2 0 0 0 4 0",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  motion: "M4 12c2-6 6-6 8 0s6 6 8 0", up: "M7 17L17 7M9 7h8v8", chart: "M4 19V5M4 19h16M8 15l3-4l3 2l5-6",
  bot: "M12 3v3M7 9h10a3 3 0 0 1 3 3v4a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-4a3 3 0 0 1 3-3zM9 14h.01M15 14h.01",
};
export function Icon({ name, size = 16 }: { name: keyof typeof ICONS | string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="ico">
    <path d={ICONS[name] ?? ""} fill={name === "play" || name === "stop" || name === "spark4" ? "currentColor" : "none"} /></svg>;
}

/** Dashboard panel: title row (with optional count and right-side controls) over a body. */
export function Panel({ title, count, right, className, children, area, i = 0 }: { title?: ReactNode; count?: number; right?: ReactNode; className?: string; children: ReactNode; area?: string; i?: number }) {
  return <section className={cls("panel", className)} style={{ ...(area ? { gridArea: area } : {}), ["--i" as string]: i }}>
    {(title || right) && <div className="panel-head"><h2 className="panel-title">{title}{count != null && <span className="count">{count}</span>}</h2>{right}</div>}
    <div className="panel-body">{children}</div>
  </section>;
}

export function Seg<T extends string | number>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return <div className="seg" role="tablist">{options.map(([v, l]) => <button key={String(v)} role="tab" aria-selected={v === value} className={cls(v === value && "on")} onClick={() => onChange(v)}>{l}</button>)}</div>;
}
