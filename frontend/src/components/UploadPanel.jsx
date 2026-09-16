import { useRef, useState } from "react";
import SamplesMenu from "./SamplesMenu";
import { Stat } from "./ui";

export default function UploadPanel({ onUpload, busy, doc, llmAvailable, providerLabel, onOpenSettings, onOpenCriteria }) {
  const inputRef = useRef();
  const [useLlm, setUseLlm] = useState(true);
  const [drag, setDrag] = useState(false);
  const gate = doc?.gate;
  const pick = (file) => file && onUpload(file, { useLlm: llmAvailable ? useLlm : false });
  return (
    <div className="flex flex-wrap items-center gap-3">
      <input ref={inputRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.jp2,.tif,.tiff,.bmp,.gif,.webp,.pnm,.xps,.oxps,.epub,.mobi,.fb2,.cbz,.svg,.txt" className="hidden" onChange={(e) => { pick(e.target.files[0]); e.target.value = ""; }} />
      <button
        className={`btn btn-primary ${drag ? "ring-4 ring-brand-500/30" : ""}`}
        disabled={busy}
        onClick={() => inputRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}
        title="Upload any file (PDF, image, XPS, EPUB, SVG, TXT…) — it is checked for being a form; non-forms are rejected."
      >
        {busy ? (
          <><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" /> Extracting…</>
        ) : (
          <>↑ Upload any file</>
        )}
      </button>
      <SamplesMenu disabled={busy} onPick={(file) => pick(file)} />
      <button className="chip hover:bg-slate-50" type="button" onClick={onOpenCriteria} title="Which documents are accepted as forms">? What counts as a form</button>
      {llmAvailable ? (
        <label className="chip cursor-pointer">
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          {providerLabel} validation
        </label>
      ) : (
        <button className="chip text-brand-700 hover:bg-brand-50" onClick={onOpenSettings} type="button">
          + Enable AI in Settings
        </button>
      )}
      {doc && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="max-w-[14rem] truncate text-xs text-slate-500" title={doc.filename}>{doc.filename}</span>
          {doc.status === "rejected" ? (
            <Stat label="not a form" value={`${Math.round((gate?.confidence || 0) * 100)}%`} tone="rose" />
          ) : doc.status === "error" ? (
            <span className="text-xs text-rose-700">
              {doc.error}{" "}
              {/Settings/.test(doc.error || "") && <button className="underline" onClick={onOpenSettings} type="button">Open Settings</button>}
            </span>
          ) : (
            <>
              <Stat label="form" value={`${Math.round((gate?.confidence || 0) * 100)}%`} tone="green" />
              <Stat label="fields" value={doc.fields.length} tone="brand" />
              <Stat label="junk removed" value={doc.qa?.junk_candidates_removed ?? 0} />
              {doc.hill_climb && <Stat label="hill-climb" value={doc.hill_climb.enabled ? `${doc.hill_climb.pass1.evaluations + doc.hill_climb.pass2.evaluations} evals` : "off"} tone={doc.hill_climb.enabled ? "slate" : "amber"} />}
              <Stat label="review" value={doc.fields.filter((f) => f.needs_review).length} tone={doc.fields.some((f) => f.needs_review) ? "amber" : "slate"} />
              <Stat label={doc.llm_used ? doc.llm_provider : "ai"} value={doc.llm_used ? `${doc.llm_input_tokens}+${doc.llm_output_tokens} tok` : "off · templates"} />
            </>
          )}
        </div>
      )}
    </div>
  );
}
