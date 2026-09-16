import { useEffect, useState } from "react";
import { Toggle } from "./ui";

const BASE = import.meta.env.VITE_API_BASE || "/api";

const PASSES = [
  {
    key: "pass1", title: "Pass 1 · Field grouping", tag: "geometry",
    what: "Clusters raw OCR tokens into label + value candidates.",
    state: "Per-row split boundaries", moves: "split · merge · shift boundary by one token",
    cost: "label↔value distance, column alignment, separators (: ____ ☐), whitespace gaps, orphan tokens",
  },
  {
    key: "pass2", title: "Pass 2 · Q&A synthesis + junk pruning", tag: "selection",
    what: "Turns candidates into canonical questions and drops headers, footers, page numbers, noise, duplicates.",
    state: "Which candidates to keep", moves: "drop · add back · merge overlapping",
    cost: "rewards a coherent form; penalises junk evidence (position, sentence-like text, bare glyphs, low OCR confidence)",
  },
];

function Num({ label, value }) {
  return (
    <div className="rounded-lg bg-white px-3 py-2 text-center shadow-xs">
      <div className="text-lg font-semibold tabular-nums">{value ?? "–"}</div>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}

const pretty = (o) => JSON.stringify(o, null, 2);
const fmt = (n) => (n ?? 0).toLocaleString();

function Bar({ label, value, max, tone = "bg-slate-300", note }) {
  const pct = max ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="flex items-center gap-3 text-xs">
      <div className="w-44 shrink-0 text-slate-600">{label}</div>
      <div className="h-3 flex-1 overflow-hidden rounded bg-slate-100"><div className={`h-3 ${tone}`} style={{ width: `${pct}%` }} /></div>
      <div className="w-20 shrink-0 text-right font-medium tabular-nums">{fmt(value)}</div>
      {note && <div className="w-24 shrink-0 text-right text-emerald-700">{note}</div>}
    </div>
  );
}

function TokenSection({ hc, doc }) {
  const t = hc?.tokens;
  const q = hc?.quality;
  if (!t || !q) return null;
  const max = Math.max(t.prompt_sent, t.prompt_unpruned, t.prompt_raw_text, t.prompt_image, 1);
  const pctVsImage = t.prompt_image ? Math.round((t.saved_vs_image / t.prompt_image) * 100) : 0;
  const pctVsUnpruned = t.prompt_unpruned ? Math.round((t.saved_vs_unpruned / t.prompt_unpruned) * 100) : 0;
  const d1 = q.pass1_cost_initial - q.pass1_cost_final;
  const d2 = q.pass2_cost_initial - q.pass2_cost_final;
  return (
    <section className="grid gap-4 md:grid-cols-2">
      <div className="rounded-2xl border border-slate-200 p-4 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="font-medium">Token management</div>
          <span className="badge bg-emerald-100 text-emerald-800">{doc?.llm_used ? `${fmt(t.used_input + t.used_output)} tokens used` : "AI off · 0 used"}</span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Num label="input used" value={fmt(t.used_input)} />
          <Num label="output used" value={fmt(t.used_output)} />
          <Num label="LLM calls" value={doc?.llm_used ? 1 : 0} />
        </div>
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Prompt size (estimated) — what was sent vs the alternatives</div>
        <Bar label="Sent: pruned Q&A JSON" value={t.prompt_sent} max={max} tone="bg-brand-600" />
        <Bar label="All pass-1 candidates" value={t.prompt_unpruned} max={max} note={t.saved_vs_unpruned ? `−${fmt(t.saved_vs_unpruned)} (${pctVsUnpruned}%)` : ""} />
        <Bar label="Raw OCR text dump" value={t.prompt_raw_text} max={max} note={t.saved_vs_raw_text ? `−${fmt(t.saved_vs_raw_text)} (${t.saved_pct_vs_raw_text}%)` : ""} />
        <Bar label="Page image to the model" value={t.prompt_image} max={max} note={t.saved_vs_image ? `−${fmt(t.saved_vs_image)} (${pctVsImage}%)` : ""} />
        <p className="text-[11px] text-slate-500">The prompt is bounded by the number of genuine fields, not by the page. Savings grow with noisy scans (instructions, headers, footers) and with images.</p>
      </div>
      <div className="rounded-2xl border border-slate-200 p-4 flex flex-col gap-3">
        <div className="font-medium">How much hill climbing helped</div>
        <div className="grid grid-cols-3 gap-2">
          <Num label="junk removed" value={q.junk_removed} />
          <Num label="fields kept" value={`${q.fields}${hc.enabled && q.baseline_fields !== q.fields ? ` (base ${q.baseline_fields})` : ""}`} />
          <Num label="template hit-rate" value={`${Math.round(q.template_hit_rate * 100)}%`} />
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-slate-500">Pass 1 cost</dt><dd>{q.pass1_cost_initial} → <b>{q.pass1_cost_final}</b>{d1 > 0.001 && <span className="ml-1 text-emerald-700">(improved by {d1.toFixed(2)})</span>}</dd>
          <dt className="text-slate-500">Pass 2 cost</dt><dd>{q.pass2_cost_initial} → <b>{q.pass2_cost_final}</b>{d2 > 0.001 && <span className="ml-1 text-emerald-700">(improved by {d2.toFixed(2)})</span>}</dd>
          <dt className="text-slate-500">Candidates</dt><dd>{q.candidates} grouped → {q.fields} kept{hc.enabled ? ` · baseline without search: ${q.baseline_candidates} → ${q.baseline_fields}` : ""}</dd>
          <dt className="text-slate-500">Search effort</dt><dd>{fmt((hc.pass1?.evaluations || 0) + (hc.pass2?.evaluations || 0))} cost evaluations, {Math.round((hc.pass1?.ms || 0) + (hc.pass2?.ms || 0))} ms, no model calls</dd>
        </dl>
        <p className="text-[11px] text-slate-500">Lower cost = a grouping/selection that looks more like a coherent form. "Baseline" is the same pipeline with the search turned off.</p>
      </div>
    </section>
  );
}

export default function HillClimbDialog({ open, onClose, config, onConfigChange, doc, notify, limits }) {
  const [tab, setTab] = useState("pass2");
  const [data, setData] = useState({});
  const [loading, setLoading] = useState(false);
  const hc = doc?.hill_climb;

  // Fetch the three data files for the current document when the JSON tabs are shown.
  useEffect(() => {
    if (!open || !doc?.document_id || doc.status !== "done") return;
    setLoading(true);
    Promise.all(
      ["pass1.data.json", "pass2.data.json", "schema.json"].map((f) => fetch(`${BASE}/documents/${doc.document_id}/${f}`).then((r) => r.json()))
    )
      .then(([p1, p2, sc]) => setData({ pass1: p1, pass2: p2, schema: sc }))
      .catch((e) => notify?.({ ok: false, text: e.message }))
      .finally(() => setLoading(false));
  }, [open, doc?.document_id, doc?.status]);

  if (!open) return null;

  const download = (name) => {
    const payload = data[name];
    if (!payload) return;
    const fn = `${(doc.filename || "document").replace(/\.[^.]+$/, "")}.${{ pass1: "pass1.data.json", pass2: "pass2.data.json", schema: "schema.json" }[name]}`;
    const blob = new Blob([pretty(payload)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = fn;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const copy = async (name) => {
    try {
      await navigator.clipboard.writeText(pretty(data[name]));
      notify?.({ ok: true, text: "JSON copied" });
    } catch {
      notify?.({ ok: false, text: "Clipboard unavailable — use Download" });
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden fade-up" role="dialog" aria-modal="true" aria-label="Hill climbing">
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">⛰ Hill climbing</h2>
            <p className="mt-0.5 text-sm text-slate-500">
              Two local-search passes clean the OCR output before the single AI call — geometry first, then junk removal. No model calls inside.
            </p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-5">
          {/* Controls */}
          <section className="rounded-2xl border border-slate-200 p-4 flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="font-medium">Enable hill climbing</div>
                <div className="text-xs text-slate-500">Off = baseline: split at big gaps only and keep everything below a junk threshold (no search). Useful to compare.</div>
              </div>
              <Toggle on={config.enabled} label="Enable hill climbing" onChange={(v) => onConfigChange({ ...config, enabled: v })} />
            </div>
            <div className={`grid gap-4 sm:grid-cols-2 ${config.enabled ? "" : "opacity-50"}`}>
              <label className="flex flex-col gap-1 text-sm">
                <span className="flex justify-between text-xs text-slate-500"><span>Random restarts</span><b>{config.restarts}</b></span>
                <input type="range" min={1} max={12} value={config.restarts} disabled={!config.enabled} onChange={(e) => onConfigChange({ ...config, restarts: +e.target.value })} />
                <span className="text-[11px] text-slate-400">Plain hill climbing gets stuck in local optima; each restart begins from a different initial grouping (cheap CPU work).</span>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="flex justify-between text-xs text-slate-500"><span>Max iterations per climb</span><b>{config.maxIterations}</b></span>
                <input type="range" min={10} max={500} step={10} value={config.maxIterations} disabled={!config.enabled} onChange={(e) => onConfigChange({ ...config, maxIterations: +e.target.value })} />
                <span className="text-[11px] text-slate-400">Steepest ascent: evaluate every neighbour, move to the best, stop at a local optimum.</span>
              </label>
            </div>
            <div className="text-xs text-slate-500">
              Settings apply to the next upload.
              {limits && (limits.max_restarts < 12 || limits.max_iterations < 1000) && (
                <span className="ml-1 text-amber-700">This server caps the search at {limits.max_restarts} restarts / {limits.max_iterations} iterations (small CPU).</span>
              )}
            </div>
          </section>

          {/* Passes + stats */}
          <section className="grid gap-4 md:grid-cols-2">
            {PASSES.map((p) => {
              const st = hc?.[p.key];
              return (
                <div key={p.key} className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4 flex flex-col gap-3">
                  <div className="flex items-center justify-between">
                    <div className="font-medium">{p.title}</div>
                    <span className="badge bg-brand-100 text-brand-700">{p.tag}</span>
                  </div>
                  <p className="text-xs text-slate-600">{p.what}</p>
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    <dt className="text-slate-500">State</dt><dd>{p.state}</dd>
                    <dt className="text-slate-500">Moves</dt><dd>{p.moves}</dd>
                    <dt className="text-slate-500">Cost</dt><dd>{p.cost}</dd>
                  </dl>
                  {st ? (
                    <div className="grid grid-cols-3 gap-2">
                      <Num label="in → out" value={`${st.candidates_in} → ${st.candidates_out}`} />
                      <Num label="evaluations" value={st.evaluations} />
                      <Num label="restarts" value={st.enabled ? st.restarts : "off"} />
                      <Num label="iterations" value={st.iterations} />
                      <Num label="final cost" value={st.cost} />
                      <Num label="time" value={`${Math.round(st.ms)} ms`} />
                    </div>
                  ) : (
                    <div className="text-xs italic text-slate-400">Upload a form to see the search statistics.</div>
                  )}
                </div>
              );
            })}
          </section>

          {/* Tokens & improvement */}
          {hc ? <TokenSection hc={hc} doc={doc} /> : null}

          {/* JSON data files */}
          <section className="rounded-2xl border border-slate-200 overflow-hidden">
            <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2">
              {[["pass1", "Pass 1 · pass1.data.json"], ["pass2", "Pass 2 · pass2.data.json"], ["schema", "Final · schema.json"]].map(([k, l]) => (
                <button key={k} className={`btn btn-sm ${tab === k ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab(k)}>{l}</button>
              ))}
              <div className="ml-auto flex gap-1.5">
                <button className="btn btn-sm" disabled={!data[tab]} onClick={() => copy(tab)}>Copy</button>
                <button className="btn btn-sm btn-primary" disabled={!data[tab]} onClick={() => download(tab)}>↓ Download</button>
              </div>
            </div>
            <pre className="max-h-80 overflow-auto bg-slate-900 p-4 text-[11px] leading-relaxed text-slate-100">
              {loading ? "Loading…" : data[tab] ? pretty(data[tab]) : doc?.status === "done" ? "No data." : "Upload a form to generate the data files."}
            </pre>
            <div className="border-t border-slate-200 px-3 py-2 text-[11px] text-slate-500">
              {tab === "pass1" && "Field candidates after grouping: label tokens, value region, separator kind, grouping score."}
              {tab === "pass2" && "The optimized Q&A JSON of the plan: canonical question, original label, expected answer type, bbox, grouping score, junk removed."}
              {tab === "schema" && "Final field schema after AI validation and normalisation — what the editor and exports consume."}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
