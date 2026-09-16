import { useEffect, useRef, useState } from "react";
import OcrMenu from "./OcrMenu";
import { Toggle } from "./ui";

import { API_BASE as BASE } from "../config";
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.jp2,.tif,.tiff,.bmp,.gif,.webp,.xps,.epub,.svg,.txt";

/** Upload page: drop zone, per-upload options, acceptance criteria, recent documents. */
const STAGES = ["uploading", "queued", "preprocessing", "reading text", "detecting form", "grouping fields (pass 1)", "pruning junk (pass 2)", "AI validation", "finishing"];

export default function UploadPage({ onUpload, busy, progress, llmAvailable, providerLabel, onOpenCriteria, onOpenSettings, onOpenHillClimb, hcConfig, onReopen }) {
  const [drag, setDrag] = useState(false);
  const [useLlm, setUseLlm] = useState(true);
  const [ocr, setOcr] = useState(() => { try { return localStorage.getItem("ocrBackend") || "auto"; } catch { return "auto"; } });
  const [recent, setRecent] = useState([]);
  const inputRef = useRef();
  const setOcrPersist = (v) => { setOcr(v); try { localStorage.setItem("ocrBackend", v); } catch {} };
  const pick = (file) => file && onUpload(file, { useLlm: llmAvailable ? useLlm : false, ocrBackend: ocr, aiMode: useLlm ? "auto" : "off" });
  const stageIdx = Math.max(0, STAGES.indexOf(progress?.stage || ""));

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
        <div className="grid h-14 w-14 place-items-center rounded-2xl bg-brand-500/15 text-brand-200 ">
          {busy ? <span className="h-6 w-6 animate-spin rounded-full border-2 border-brand-300 border-t-brand-600" /> : (
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4m0 0l-4 4m4-4l4 4" /><path d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" /></svg>
          )}
        </div>
        {busy ? (
          <div className="w-full max-w-md">
            <div className="text-[15px] font-medium">{progress?.stage === "uploading" ? "Uploading…" : `${progress?.stage || "processing"}…`}</div>
            <div className="mt-3 h-1.5 w-full overflow-hidden rounded bg-white/10"><div className="h-1.5 rounded bg-brand-500 transition-all" style={{ width: `${Math.round(((stageIdx + 1) / STAGES.length) * 100)}%` }} /></div>
            <div className="muted mt-2 flex justify-between text-xs"><span>step {stageIdx + 1} of {STAGES.length}</span><span>{((progress?.ms || 0) / 1000).toFixed(1)} s</span></div>
          </div>
        ) : (
          <>
            <div className="text-[15px] font-medium">Drop a form here, or <span className="text-brand-200 underline decoration-brand-300 underline-offset-2">browse</span></div>
            <div className="muted text-xs">PDF · PNG · JPG · GIF · TIFF · WebP · XPS · EPUB · SVG · TXT — up to 25 MB · any language</div>
          </>
        )}
      </div>

      <div className="panel mt-4 grid gap-4 p-4 sm:grid-cols-3">
        <div>
          <div className="panel-title mb-2">Text reader</div>
          <OcrMenu value={ocr} onChange={setOcrPersist} disabled={busy} />
        </div>
        <div>
          <div className="panel-title mb-2">AI validation</div>
          {llmAvailable ? (
            <div className="flex items-center gap-2 text-sm"><Toggle on={useLlm} onChange={setUseLlm} label="AI validation" /> {providerLabel} · auto (only when needed)</div>
          ) : (
            <button className="btn btn-sm" onClick={onOpenSettings}>+ Enable AI in Settings</button>
          )}
        </div>
        <div>
          <div className="panel-title mb-2">Hill climbing</div>
          <button className={`btn btn-sm ${hcConfig.enabled ? "" : "border-amber-500/50 bg-amber-500/10 text-amber-200"}`} onClick={onOpenHillClimb}>
            ⛰ {hcConfig.enabled ? `on · ${hcConfig.restarts} restarts` : "off (baseline)"}
          </button>
        </div>
      </div>

      <div className="muted mt-3 text-xs">Non-forms (letters, receipts, photos of scenes…) are rejected before extraction.</div>

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
