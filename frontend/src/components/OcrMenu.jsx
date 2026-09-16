import { useEffect, useRef, useState } from "react";

const BASE = import.meta.env.VITE_API_BASE || "/api";
const OPTIONS = [
  { id: "auto", label: "Auto", help: "PDF text → PaddleOCR-VL → macOS → AI vision" },
  { id: "pdftext", label: "PDF text layer", help: "Digital PDFs only" },
  { id: "paddle", label: "PaddleOCR-VL", help: "109 languages · local or server" },
  { id: "apple", label: "macOS Vision", help: "Built-in on a Mac backend" },
  { id: "llm", label: "AI vision", help: "Active provider reads the image" },
];

/** OCR button: pick the text reader used for the next upload. */
export default function OcrMenu({ value, onChange, disabled, usedBackend }) {
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState(["pdftext"]);
  const ref = useRef();
  useEffect(() => {
    fetch(`${BASE}/health`).then((r) => r.json()).then((h) => setAvailable(h.ocr_backends || [])).catch(() => {});
  }, []);
  useEffect(() => {
    const close = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const current = OPTIONS.find((o) => o.id === value) || OPTIONS[0];
  return (
    <div className="relative" ref={ref}>
      <button className={`btn btn-sm ${value !== "auto" ? "border-brand-500 text-brand-200" : ""}`} disabled={disabled} onClick={() => setOpen(!open)} title="Choose how text is read from scans">
        ▤ OCR · {current.label}
      </button>
      {open && (
        <div className="absolute left-0 z-30 mt-1 w-72 rounded-xl border border-neutral-800 bg-[var(--surface)] p-2 shadow-lg fade-up">
          <div className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-neutral-400">Text reader for the next upload</div>
          {OPTIONS.map((o) => {
            const off = o.id !== "auto" && !available.includes(o.id);
            return (
              <button key={o.id} disabled={off} onClick={() => { onChange(o.id); setOpen(false); }}
                className={`flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-white/5 disabled:opacity-40 ${value === o.id ? "bg-brand-500/15 text-brand-200" : ""}`}>
                <span className="w-4">{value === o.id ? "✓" : ""}</span>
                <span className="flex-1">
                  <span className="font-medium">{o.label}</span>{off && <span className="badge ml-1 bg-white/10 text-neutral-400">not available</span>}
                  <span className="block text-xs text-neutral-400">{o.help}</span>
                </span>
              </button>
            );
          })}
          {usedBackend && <div className="mt-1 border-t border-neutral-800 px-2 pt-2 text-xs text-neutral-400">Last document read with: <b>{usedBackend}</b></div>}
        </div>
      )}
    </div>
  );
}
