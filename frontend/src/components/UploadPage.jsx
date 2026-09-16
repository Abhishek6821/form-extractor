import { useEffect, useRef, useState } from "react";
import OcrMenu from "./OcrMenu";
import { Toggle } from "./ui";

const BASE = import.meta.env.VITE_API_BASE || "/api";
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.jp2,.tif,.tiff,.bmp,.gif,.webp,.xps,.epub,.svg,.txt";

/** Upload page: drop zone, per-upload options, acceptance criteria, recent documents. */
export default function UploadPage({ onUpload, busy, llmAvailable, providerLabel, onOpenCriteria, onOpenSettings, onOpenHillClimb, hcConfig, onReopen }) {
  const [drag, setDrag] = useState(false);
  const [useLlm, setUseLlm] = useState(true);
  const [ocr, setOcr] = useState(() => { try { return localStorage.getItem("ocrBackend") || "auto"; } catch { return "auto"; } });
  const [recent, setRecent] = useState([]);
  const inputRef = useRef();
  const setOcrPersist = (v) => { setOcr(v); try { localStorage.setItem("ocrBackend", v); } catch {} };
  const pick = (file) => file && onUpload(file, { useLlm: llmAvailable ? useLlm : false, ocrBackend: ocr });

  useEffect(() => {
    fetch(`${BASE}/documents`).then((r) => r.json()).then((d) => setRecent((Array.isArray(d) ? d : []).filter((x) => x.status === "done").slice(0, 6))).catch(() => {});
  }, [busy]);

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 fade-up">
      <div className="mb-5">
        <h1 className="text-2xl font-semibold tracking-tight">Upload a form</h1>
        <p className="muted mt-1 text-sm">Any file type. It is checked for being a fillable form first; other documents are rejected.</p>
      </div>

      <div className="dropzone flex cursor-pointer flex-col items-center justify-center gap-3 px-6 py-14 text-center" data-drag={drag}
        onClick={() => !busy && inputRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}>
        <input ref={inputRef} type="file" className="hidden" accept={ACCEPT} onChange={(e) => { pick(e.target.files[0]); e.target.value = ""; }} />
        <div className="grid h-14 w-14 place-items-center rounded-2xl bg-brand-50 text-brand-600 dark:bg-brand-500/15">
          {busy ? <span className="h-6 w-6 animate-spin rounded-full border-2 border-brand-300 border-t-brand-600" /> : (
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4m0 0l-4 4m4-4l4 4" /><path d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" /></svg>
          )}
        </div>
        <div className="text-[15px] font-medium">{busy ? "Extracting fields…" : <>Drop a form here, or <span className="text-brand-600 underline decoration-brand-300 underline-offset-2">browse</span></>}</div>
        <div className="muted text-xs">PDF · PNG · JPG · GIF · TIFF · WebP · XPS · EPUB · SVG · TXT — up to 25 MB · any language</div>
      </div>

      <div className="panel mt-4 grid gap-4 p-4 sm:grid-cols-3">
        <div>
          <div className="panel-title mb-2">Text reader</div>
          <OcrMenu value={ocr} onChange={setOcrPersist} disabled={busy} />
        </div>
        <div>
          <div className="panel-title mb-2">AI validation</div>
          {llmAvailable ? (
            <div className="flex items-center gap-2 text-sm"><Toggle on={useLlm} onChange={setUseLlm} label="AI validation" /> {providerLabel} · one call</div>
          ) : (
            <button className="btn btn-sm" onClick={onOpenSettings}>+ Enable AI in Settings</button>
          )}
        </div>
        <div>
          <div className="panel-title mb-2">Hill climbing</div>
          <button className={`btn btn-sm ${hcConfig.enabled ? "" : "border-amber-300 bg-amber-50 text-amber-800"}`} onClick={onOpenHillClimb}>
            ⛰ {hcConfig.enabled ? `on · ${hcConfig.restarts} restarts` : "off (baseline)"}
          </button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <button className="chip hover:border-slate-400/60" onClick={onOpenCriteria}>? What counts as a form</button>
        <span className="muted">Non-forms (letters, receipts, photos of scenes…) are rejected before extraction.</span>
      </div>

      {recent.length > 0 && (
        <section className="mt-8">
          <div className="panel-title mb-2">Recent documents</div>
          <div className="grid gap-2 sm:grid-cols-2">
            {recent.map((d) => (
              <button key={d.document_id} className="panel flex items-center justify-between gap-3 px-4 py-3 text-left hover:border-brand-500/60" onClick={() => onReopen(d)}>
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{d.filename}</div>
                  <div className="muted text-xs">{d.fields.length} fields · {d.qa?.junk_candidates_removed ?? 0} junk removed{d.llm_used ? ` · ${d.llm_model}` : ""}</div>
                </div>
                <span className="muted text-xs">Open →</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
