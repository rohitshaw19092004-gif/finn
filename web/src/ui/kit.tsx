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
  return <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.38, background: `hsl(${h} 28% 86%)`, color: `hsl(${h} 35% 28%)` }}>{ini}</span>;
}

export function Empty({ children }: { children: ReactNode }) { return <div className="empty">{children}</div>; }
