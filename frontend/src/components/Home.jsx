const STEPS = [
  ["Preprocess", "Render, deskew, detect rule lines"],
  ["Read text", "PDF layer · PaddleOCR-VL · macOS · AI vision"],
  ["Form gate", "Is this even a form? Non-forms are rejected"],
  ["Hill-climb 1", "Group tokens into label + value candidates"],
  ["Hill-climb 2", "Canonical questions, junk pruned"],
  ["One AI call", "Validate, translate, normalise"],
];

/** Landing page. */
export default function Home({ onStart, onSettings, backend, providerLabel }) {
  return (
    <div className="fade-up">
      <section className="mx-auto max-w-5xl px-4 pb-10 pt-16 text-center">
        <span className="chip mx-auto mb-4">Multilingual · any file type · one AI call per form</span>
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">Turn any form into clean, structured fields</h1>
        <p className="muted mx-auto mt-4 max-w-2xl text-[16px] leading-relaxed">
          Upload a form in Hindi, Arabic, Chinese, Tamil or English — PDF, photo or scan. Two hill-climbing passes group the text into
          fields and remove OCR junk; a single AI call validates them. Build a new form from the result and export it as PDF, HTML or JSON.
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          <button className="btn btn-primary px-5 py-2.5 text-[15px]" onClick={onStart}>Upload a form →</button>
          <button className="btn px-5 py-2.5 text-[15px]" onClick={onSettings}>⚙ Settings</button>
        </div>
        <div className="muted mt-4 flex flex-wrap items-center justify-center gap-3 text-xs">
          <span className="chip"><span className={`h-1.5 w-1.5 rounded-full ${backend.llm_available ? "bg-emerald-500" : "bg-amber-500"}`} /> {backend.llm_available ? `${providerLabel} ready` : "AI not configured"}</span>
          <span className="chip">readers: {(backend.ocr_backends || []).join(", ") || "…"}</span>
          {backend.version && <span className="chip">API v{backend.version}</span>}
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-4 pb-12">
        <div className="panel-title mb-3 text-center">How it works</div>
        <ol className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {STEPS.map(([t, d], i) => (
            <li key={t} className="panel p-4">
              <div className="mb-2 grid h-6 w-6 place-items-center rounded-full bg-brand-50 text-[11px] font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-200">{i + 1}</div>
              <div className="text-sm font-medium">{t}</div>
              <div className="muted mt-1 text-xs leading-relaxed">{d}</div>
            </li>
          ))}
        </ol>
      </section>

      <section className="mx-auto max-w-5xl px-4 pb-16">
        <div className="grid gap-4 md:grid-cols-3">
          {[
            ["Token-efficient by design", "The model never sees the OCR dump or the image for a digital form — only one line per genuine field. The ⛰ Hill climbing dialog shows exactly what was saved."],
            ["Language-independent core", "Grouping and pruning use geometry and separators (: ____ ☐), so Devanagari, Arabic (RTL), CJK and Latin forms all go through the same code."],
            ["Inspectable & switchable", "Claude, Gemini or Kimi; PaddleOCR-VL, macOS Vision or AI vision for scans; pass-1 / pass-2 data files downloadable for every run."],
          ].map(([t, d]) => (
            <div key={t} className="panel p-5">
              <div className="font-medium">{t}</div>
              <p className="muted mt-1.5 text-sm leading-relaxed">{d}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
