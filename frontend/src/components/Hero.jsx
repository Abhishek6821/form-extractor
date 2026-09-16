import { useRef, useState } from "react";

const STEPS = ["Preprocess", "Read text (OCR)", "Form gate", "Hill-climb pass 1", "Hill-climb pass 2", "AI validation", "Normalize"];

/** Empty-state drop zone + what the pipeline does. Shown until a document is loaded. */
export default function Hero({ onFile, busy, onOpenCriteria, providerLabel, llmAvailable, onOpenSettings }) {
  const [drag, setDrag] = useState(false);
  const ref = useRef();
  return (
    <div className="mx-auto max-w-5xl px-4 py-10 fade-up">
      <div className="mb-8 text-center">
        <h1 className="text-3xl font-semibold tracking-tight">Turn any form into structured fields</h1>
        <p className="muted mx-auto mt-2 max-w-2xl text-[15px]">
          Upload a form in any language — PDF, photo or scan. Two hill-climbing passes group the text into fields and drop the junk,
          then a single AI call validates them. Drag the result into a new layout and export it.
        </p>
      </div>

      <div
        ref={ref}
        className="dropzone flex cursor-pointer flex-col items-center justify-center gap-3 px-6 py-14 text-center"
        data-drag={drag}
        onClick={() => !busy && document.getElementById("hero-file").click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); e.dataTransfer.files[0] && onFile(e.dataTransfer.files[0]); }}
      >
        <input id="hero-file" type="file" className="hidden" accept=".pdf,.png,.jpg,.jpeg,.jp2,.tif,.tiff,.bmp,.gif,.webp,.xps,.epub,.svg,.txt" onChange={(e) => { e.target.files[0] && onFile(e.target.files[0]); e.target.value = ""; }} />
        <div className="grid h-14 w-14 place-items-center rounded-2xl bg-brand-50 text-brand-600 dark:bg-brand-500/15">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V4m0 0l-4 4m4-4l4 4" /><path d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" /></svg>
        </div>
        {busy ? (
          <div className="text-[15px] font-medium">Processing…</div>
        ) : (
          <>
            <div className="text-[15px] font-medium">Drop a form here, or <span className="text-brand-600 underline decoration-brand-300 underline-offset-2">browse</span></div>
            <div className="muted text-xs">PDF · PNG · JPG · GIF · TIFF · WebP · XPS · EPUB · SVG · TXT — up to 25 MB · any language</div>
          </>
        )}
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2 text-xs">
          <button type="button" className="chip hover:border-slate-400/60" onClick={(e) => { e.stopPropagation(); onOpenCriteria(); }}>? What counts as a form</button>
          {llmAvailable ? (
            <span className="chip"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> {providerLabel} validation on</span>
          ) : (
            <button type="button" className="chip text-brand-700 hover:border-brand-300" onClick={(e) => { e.stopPropagation(); onOpenSettings(); }}>+ Enable AI in Settings</button>
          )}
        </div>
      </div>

      <ol className="progress-steps mt-8 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4 lg:grid-cols-7">
        {STEPS.map((s, i) => (
          <li key={s} className="panel flex items-center gap-2 px-3 py-2">
            <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand-50 text-[10px] font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-200">{i + 1}</span>
            <span className="truncate">{s}</span>
          </li>
        ))}
      </ol>

      <div className="mt-8 grid gap-4 md:grid-cols-3">
        {[
          ["No OCR dump to the model", "The AI only sees one line per genuine field — the prompt is bounded by the form, not the page."],
          ["Language-independent", "Grouping and junk pruning use geometry and separators, so Hindi, Arabic, Chinese or Tamil forms all work."],
          ["Inspectable", "Every run exposes both passes' data files, search statistics and token savings in the ⛰ Hill climbing dialog."],
        ].map(([t, d]) => (
          <div key={t} className="panel p-4">
            <div className="font-medium">{t}</div>
            <p className="muted mt-1 text-xs leading-relaxed">{d}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
