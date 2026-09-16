import { useEffect } from "react";

export function Toggle({ on, onChange, disabled, label }) {
  return (
    <button type="button" role="switch" aria-checked={!!on} aria-label={label} className="toggle" data-on={!!on} disabled={disabled} onClick={() => onChange(!on)}>
      <span />
    </button>
  );
}

export function Toast({ toast, onClose }) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onClose, toast.ok === false ? 7000 : 3500);
    return () => clearTimeout(t);
  }, [toast, onClose]);
  if (!toast) return null;
  const cls = toast.ok === false ? "bg-rose-600 text-white" : "bg-slate-900 text-white";
  return (
    <div className={`toast fade-up ${cls}`} role="status">
      <div className="flex items-start gap-3">
        <span className="flex-1">{toast.text}</span>
        <button className="opacity-70 hover:opacity-100" onClick={onClose} aria-label="Dismiss">✕</button>
      </div>
    </div>
  );
}

export function Stat({ label, value, tone = "slate" }) {
  const tones = { slate: "bg-slate-100 text-slate-700", green: "bg-emerald-100 text-emerald-800", amber: "bg-amber-100 text-amber-800", rose: "bg-rose-100 text-rose-800", brand: "bg-brand-100 text-brand-700" };
  return (
    <span className={`badge ${tones[tone]}`}>
      <span className="opacity-70 font-normal normal-case tracking-normal">{label}</span> {value}
    </span>
  );
}

export const Logo = () => (
  <div className="flex items-center gap-2">
    <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-white shadow-sm">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9h6M7 13h10M7 17h4" /></svg>
    </div>
    <div className="leading-tight">
      <div className="text-sm font-semibold tracking-tight">Form Extractor</div>
      <div className="text-[10px] text-slate-500">multilingual · hill-climb · one LLM call</div>
    </div>
  </div>
);
