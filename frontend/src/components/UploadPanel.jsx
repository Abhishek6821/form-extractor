import { useRef, useState } from "react";

export default function UploadPanel({ onUpload, busy, doc, error, llmAvailable, onOpenSettings }) {
  const inputRef = useRef();
  const [useLlm, setUseLlm] = useState(true);
  const gate = doc?.gate;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp"
        className="hidden"
        onChange={(e) => e.target.files[0] && onUpload(e.target.files[0], { useLlm: llmAvailable ? useLlm : false })}
      />
      <button className="btn btn-primary" disabled={busy} onClick={() => inputRef.current.click()}>
        {busy ? "Extracting…" : "Upload PDF / image"}
      </button>
      {llmAvailable ? (
        <label className="flex items-center gap-1 text-xs">
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          Claude validation (1 call)
        </label>
      ) : (
        <button className="text-xs text-indigo-600 underline" onClick={onOpenSettings} type="button">
          Enable Claude in Settings
        </button>
      )}
      {doc && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-slate-500 truncate max-w-[16rem]">{doc.filename}</span>
          {doc.status === "rejected" ? (
            <span className="badge bg-rose-100 text-rose-800">not a form ({Math.round((gate?.confidence || 0) * 100)}%)</span>
          ) : doc.status === "error" ? (
            <span className="badge bg-rose-100 text-rose-800" title={doc.error}>error</span>
          ) : (
            <>
              <span className="badge bg-emerald-100 text-emerald-800">form {Math.round((gate?.confidence || 0) * 100)}%</span>
              <span className="badge bg-slate-200 text-slate-700">{doc.fields.length} fields</span>
              <span className="badge bg-slate-200 text-slate-700">{doc.qa?.junk_candidates_removed ?? 0} junk removed</span>
              <span className="badge bg-slate-200 text-slate-700">
                {doc.llm_used ? `LLM ${doc.llm_input_tokens}+${doc.llm_output_tokens} tok` : "templates only"}
              </span>
              {doc.timing_ms?.pass1_grouping !== undefined && (
                <span className="text-slate-400">
                  {Object.entries(doc.timing_ms)
                    .filter(([k]) => !k.endsWith("_evals"))
                    .map(([k, v]) => `${k} ${Math.round(v)}ms`)
                    .join(" · ")}
                </span>
              )}
            </>
          )}
          {doc.status === "error" && (
            <span className="text-rose-700">
              {doc.error}{" "}
              {/Settings/.test(doc.error || "") && (
                <button className="underline" onClick={onOpenSettings} type="button">
                  Open Settings
                </button>
              )}
            </span>
          )}
        </div>
      )}
      {error && <span className="text-xs text-rose-700">{error}</span>}
    </div>
  );
}
