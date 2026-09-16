import { useRef, useState } from "react";
import OcrMenu from "./OcrMenu";
import { Stat } from "./ui";

/** Toolbar row: upload, OCR reader, AI toggle, criteria — plus the current document's summary chips. */
export default function UploadPanel({ onUpload, busy, doc, llmAvailable, providerLabel, onOpenSettings, onOpenCriteria, compact }) {
  const inputRef = useRef();
  const [useLlm, setUseLlm] = useState(true);
  const [ocr, setOcr] = useState(() => { try { return localStorage.getItem("ocrBackend") || "auto"; } catch { return "auto"; } });
  const gate = doc?.gate;
  const setOcrPersist = (v) => { setOcr(v); try { localStorage.setItem("ocrBackend", v); } catch {} };
  const pick = (file) => file && onUpload(file, { useLlm: llmAvailable ? useLlm : false, ocrBackend: ocr });
  // The hero has its own drop zone; this exposes the same picker for the toolbar.
  UploadPanel.pick = pick;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input ref={inputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.jp2,.tif,.tiff,.bmp,.gif,.webp,.xps,.epub,.svg,.txt" className="hidden" onChange={(e) => { pick(e.target.files[0]); e.target.value = ""; }} />
      <button className="btn btn-primary" disabled={busy} onClick={() => inputRef.current.click()} title="Upload any file — it is checked for being a form">
        {busy ? <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" /> Extracting…</> : <>↑ Upload form</>}
      </button>
      <OcrMenu value={ocr} onChange={setOcrPersist} disabled={busy} usedBackend={doc?.ocr_backend} />
      {llmAvailable ? (
        <label className="chip cursor-pointer select-none" title="One batched validation call per document">
          <input type="checkbox" className="accent-brand-600" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          {providerLabel} validation
        </label>
      ) : (
        <button className="chip text-brand-700 hover:border-brand-300" onClick={onOpenSettings} type="button">+ Enable AI</button>
      )}
      {!compact && <button className="chip hover:border-slate-400/60" type="button" onClick={onOpenCriteria}>? What counts as a form</button>}
      {doc && doc.status === "done" && (
        <div className="ml-1 flex flex-wrap items-center gap-1.5">
          <span className="muted max-w-[12rem] truncate text-xs" title={doc.filename}>{doc.filename}</span>
          <Stat label="form" value={`${Math.round((gate?.confidence || 0) * 100)}%`} tone="green" />
          <Stat label="fields" value={doc.fields.length} tone="brand" />
          <Stat label="junk removed" value={doc.qa?.junk_candidates_removed ?? 0} />
          <Stat label="review" value={doc.fields.filter((f) => f.needs_review).length} tone={doc.fields.some((f) => f.needs_review) ? "amber" : "slate"} />
          <Stat label={doc.llm_used ? doc.llm_provider : "ai"} value={doc.llm_used ? `${doc.llm_input_tokens}+${doc.llm_output_tokens} tok` : "off"} />
          {doc.hill_climb && <Stat label="hill-climb" value={doc.hill_climb.enabled ? `${doc.hill_climb.pass1.evaluations + doc.hill_climb.pass2.evaluations} evals` : "off"} tone={doc.hill_climb.enabled ? "slate" : "amber"} />}
        </div>
      )}
    </div>
  );
}
