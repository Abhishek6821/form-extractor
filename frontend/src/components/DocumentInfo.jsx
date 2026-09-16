import { useState } from "react";

/** What the document is: type, title, language, summary and full text — shown for every upload. */
export default function DocumentInfo({ doc }) {
  const [open, setOpen] = useState(false);
  const info = doc?.info;
  if (!info) return null;
  return (
    <section className="panel p-4 fade-up">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="panel-title">Document</div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span className="badge bg-brand-100 text-brand-700">{info.document_type}</span>
            {info.language && <span className="chip">{info.language}</span>}
            {doc.pages > 1 && <span className="chip">{doc.pages} pages</span>}
            {info.title && <span className="truncate text-sm font-medium" title={info.title}>{info.title}</span>}
          </div>
        </div>
        <button className="btn btn-sm" onClick={() => setOpen(!open)}>{open ? "Hide text" : "Full text"}</button>
      </div>
      {info.summary && <p className="mt-2 text-sm text-slate-600">{info.summary}</p>}
      {!doc.is_form && (
        <p className="mt-2 text-xs text-slate-500">
          Not a fillable form, so its key facts were extracted instead — drag any of them onto the canvas to build a form from this document.
        </p>
      )}
      {open && (
        <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-xs leading-relaxed text-slate-700">{info.full_text || "(no text)"}</pre>
      )}
    </section>
  );
}
