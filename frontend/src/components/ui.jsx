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
    const t = setTimeout(onClose, toast.ok === false ? 8000 : 3500);
    return () => clearTimeout(t);
  }, [toast, onClose]);
  if (!toast) return null;
  const cls = toast.ok === false ? "bg-rose-600 text-white" : "bg-slate-900 text-white dark:bg-white dark:text-slate-900";
  return (
    <div className={`toast fade-up ${cls}`} role="status">
      <div className="flex items-start gap-3">
        <span className="mt-0.5">{toast.ok === false ? "⚠" : "✓"}</span>
        <span className="flex-1">{toast.text}</span>
        <button className="opacity-70 hover:opacity-100" onClick={onClose} aria-label="Dismiss">✕</button>
      </div>
    </div>
  );
}

export function Stat({ label, value, tone = "slate" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700 dark:bg-white/10 dark:text-slate-200",
    green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200",
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-200",
    rose: "bg-rose-100 text-rose-800 dark:bg-rose-500/20 dark:text-rose-200",
    brand: "bg-brand-100 text-brand-700 dark:bg-brand-500/20 dark:text-brand-200",
  };
  return (
    <span className={`badge ${tones[tone]}`}>
      <span className="opacity-70 font-normal normal-case tracking-normal">{label}</span> {value}
    </span>
  );
}

export const Logo = ({ compact }) => (
  <div className="flex items-center gap-2.5">
    <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-[0_6px_16px_-8px_rgba(79,70,229,.8)]">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M7 9h6M7 13h10M7 17h4" /></svg>
    </div>
    {!compact && (
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight">Form Extractor</div>
        <div className="muted text-[11px]">multilingual · hill-climb passes · one AI call</div>
      </div>
    )}
  </div>
);

/** Modal frame used by all dialogs: Esc closes, click outside closes. */
export function Modal({ open, onClose, title, subtitle, children, width = "max-w-4xl" }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/55 p-4 backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`panel flex max-h-[92vh] w-full ${width} flex-col overflow-hidden fade-up`} role="dialog" aria-modal="true" aria-label={title}>
        <header className="flex items-start justify-between gap-4 border-b px-6 py-4" style={{ borderColor: "var(--border)" }}>
          <div>
            <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
            {subtitle && <p className="muted mt-0.5 text-sm">{subtitle}</p>}
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">✕ <span className="kbd">Esc</span></button>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
      </div>
    </div>
  );
}
