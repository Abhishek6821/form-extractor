import { useEffect, useState } from "react";

const BASE = import.meta.env.VITE_API_BASE || "/api";

/** "What counts as a form?" — the acceptance criteria the gate applies. */
export default function CriteriaPanel({ open, onClose }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (open) fetch(`${BASE}/criteria`).then((r) => r.json()).then(setData).catch(() => setData({ criteria: [] }));
  }, [open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel w-full max-w-xl p-6 fade-up" role="dialog" aria-modal="true">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">What counts as a form?</h2>
            <p className="mt-0.5 text-sm text-slate-500">Only files that meet these criteria are accepted. Everything else is rejected before any extraction.</p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <ol className="mt-4 flex flex-col gap-2 text-sm">
          {(data?.criteria || []).map((c, i) => (
            <li key={i} className={`flex gap-3 rounded-xl p-3 ${c.startsWith("NOT") ? "bg-rose-50 text-rose-900" : "bg-slate-50"}`}>
              <span className="font-semibold text-slate-400">{i + 1}</span>
              <span>{c}</span>
            </li>
          ))}
          {!data && <li className="text-slate-400">Loading…</li>}
        </ol>
        <div className="mt-4 text-xs text-slate-500">
          How it is checked: language-independent layout signals (separators, blanks, boxes, short label rows) first; scans and borderline cases are confirmed by the
          <b> form check provider</b>{data?.gate_provider ? ` (${data.gate_provider})` : ""} looking at the page image. Use the sample forms in the header to see accepted examples.
        </div>
      </div>
    </div>
  );
}
