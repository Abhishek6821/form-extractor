import { useEffect, useState } from "react";
import { Modal, Toggle } from "./ui";

import { API_BASE as BASE } from "../config";


function Num({ label, value }) {
  return (
    <div className="rounded-lg bg-[var(--surface)] px-3 py-2 text-center shadow-xs">
      <div className="text-lg font-semibold tabular-nums">{value ?? "–"}</div>
      <div className="text-[10px] uppercase tracking-wide text-neutral-400">{label}</div>
    </div>
  );
}

const pretty = (o) => JSON.stringify(o, null, 2);
const fmt = (n) => (n ?? 0).toLocaleString();

function Bar({ label, value, max, tone = "bg-neutral-600", note }) {
  const pct = max ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="flex items-center gap-3 text-xs">
      <div className="w-44 shrink-0 text-neutral-300">{label}</div>
      <div className="h-3 flex-1 overflow-hidden rounded bg-white/10"><div className={`h-3 ${tone}`} style={{ width: `${pct}%` }} /></div>
      <div className="w-20 shrink-0 text-right font-medium tabular-nums">{fmt(value)}</div>
      {note && <div className="w-24 shrink-0 text-right text-emerald-300">{note}</div>}
    </div>
  );
}

function Combined({ hc, doc }) {
  const t = hc?.tokens || {};
  const q = hc?.quality || {};
  const used = (t.used_input || 0) + (t.used_output || 0);
  const pct = (saved, base) => (base ? Math.round((saved / base) * 100) : 0);
  const rows = [
    { key: "pass1", name: "Pass 1 · Field grouping", what: "split / merge / shift boundaries · geometry cost", st: hc?.pass1, c0: q.pass1_cost_initial, c1: q.pass1_cost_final },
    { key: "pass2", name: "Pass 2 · Q&A synthesis + junk pruning", what: "drop / add / merge candidates · junk vs genuine", st: hc?.pass2, c0: q.pass2_cost_initial, c1: q.pass2_cost_final },
  ];
  return (
    <section className="rounded-2xl border p-4 flex flex-col gap-4" style={{ borderColor: "var(--border)", background: "var(--surface-2)" }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium">Hill climbing — result for this document</div>
        <span className={`badge ${hc?.enabled ? "bg-brand-500/20 text-brand-200" : "bg-amber-500/20 text-amber-200"}`}>{hc?.enabled ? `${hc.restarts} restarts · ${hc.max_iterations} max iterations` : "off · baseline"}</span>
      </div>

      {/* Tokens used / saved */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl p-4" style={{ background: "var(--surface)" }}>
          <div className="muted text-[10px] font-semibold uppercase tracking-wide">Tokens used</div>
          <div className="mt-1 text-3xl font-semibold tabular-nums">{fmt(t.used_total || used)}</div>
          <div className="muted mt-1 text-xs">
            {(t.calls || []).length ? `${t.calls.length} model call${t.calls.length > 1 ? "s" : ""} · ${t.calls.map((c) => c.purpose).join(", ")}` : t.skipped_reason ? `No AI call: ${t.skipped_reason} (would have cost ≈${fmt(t.estimated_if_called)})` : "AI was off for this document"}
          </div>
        </div>
        <div className="rounded-xl p-4" style={{ background: "var(--surface)" }}>
          <div className="text-[10px] font-semibold uppercase tracking-wide text-emerald-300">Tokens saved</div>
          <div className="mt-1 text-3xl font-semibold tabular-nums text-emerald-300">{fmt(t.tokens_saved || 0)} <span className="text-base font-medium">({t.saved_pct || 0}%)</span></div>
          <div className="muted mt-1 text-xs">vs {t.baseline === "image" ? "sending the page image to the model" : "sending the raw OCR text dump"} — {fmt(t.baseline === "image" ? t.prompt_image : t.prompt_raw_text)} tokens instead of {fmt(t.prompt_sent)}</div>
        </div>
      </div>
      <div className="grid gap-1.5">
        {(() => { const max = Math.max(t.prompt_sent || 0, t.prompt_unpruned || 0, t.prompt_raw_text || 0, t.prompt_image || 0, 1); return (
          <>
            <Bar label="Prompt sent (pruned fields)" value={t.prompt_sent || 0} max={max} tone="bg-brand-500" />
            <Bar label="All pass-1 candidates" value={t.prompt_unpruned || 0} max={max} tone="bg-neutral-600" note={t.saved_vs_unpruned ? `−${fmt(t.saved_vs_unpruned)}` : ""} />
            <Bar label="Raw OCR text dump" value={t.prompt_raw_text || 0} max={max} tone="bg-neutral-600" note={t.saved_vs_raw_text ? `−${fmt(t.saved_vs_raw_text)}` : ""} />
            <Bar label="Page image to the model" value={t.prompt_image || 0} max={max} tone="bg-neutral-600" note={t.saved_vs_image ? `−${fmt(t.saved_vs_image)}` : ""} />
          </>
        ); })()}
        <div className="muted text-[11px]">Estimated prompt tokens. One AI call per document; the prompt is bounded by the number of genuine fields, not the page.</div>
      </div>

      {(t.calls || []).length > 0 && (
        <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border)" }}>
          <table className="w-full text-xs">
            <thead className="muted text-[10px] uppercase tracking-wide"><tr className="text-left"><th className="px-3 py-1.5">Model call</th><th className="px-3 py-1.5">model</th><th className="px-3 py-1.5">input</th><th className="px-3 py-1.5">output</th><th className="px-3 py-1.5">time</th></tr></thead>
            <tbody>
              {t.calls.map((c, i) => (
                <tr key={i} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-3 py-1.5">{c.purpose}{c.with_image ? " · image" : ""}</td><td className="px-3 py-1.5 font-mono">{c.model}</td>
                  <td className="px-3 py-1.5 tabular-nums">{fmt(c.input_tokens)}</td><td className="px-3 py-1.5 tabular-nums">{fmt(c.output_tokens)}</td><td className="px-3 py-1.5 tabular-nums">{fmt(c.ms)} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Both passes in one table */}
      <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border)" }}>
        <table className="w-full text-xs">
          <thead className="muted text-[10px] uppercase tracking-wide">
            <tr className="text-left">
              <th className="px-3 py-2">Pass</th><th className="px-3 py-2">in → out</th><th className="px-3 py-2">cost</th><th className="px-3 py-2">evaluations</th><th className="px-3 py-2">iterations</th><th className="px-3 py-2">time</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const d = (r.c0 ?? 0) - (r.c1 ?? 0);
              return (
                <tr key={r.key} className="border-t" style={{ borderColor: "var(--border)" }}>
                  <td className="px-3 py-2"><div className="font-medium">{r.name}</div><div className="muted">{r.what}</div></td>
                  <td className="px-3 py-2 tabular-nums">{r.st ? `${r.st.candidates_in} → ${r.st.candidates_out}` : "–"}</td>
                  <td className="px-3 py-2 tabular-nums">{r.st ? <>{r.c0} → <b>{r.c1}</b>{d > 0.001 && <span className="ml-1 text-emerald-300">↓{d.toFixed(2)}</span>}</> : "–"}</td>
                  <td className="px-3 py-2 tabular-nums">{r.st ? fmt(r.st.evaluations) : "–"}</td>
                  <td className="px-3 py-2 tabular-nums">{r.st ? r.st.iterations : "–"}</td>
                  <td className="px-3 py-2 tabular-nums">{r.st ? `${Math.round(r.st.ms)} ms` : "–"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {hc ? (
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="chip">junk removed: <b>{q.junk_removed}</b></span>
          <span className="chip">fields kept: <b>{q.fields}</b>{hc.enabled && q.baseline_fields !== q.fields ? ` (baseline ${q.baseline_fields})` : ""}</span>
          <span className="chip">candidates: {q.candidates}{hc.enabled ? ` (baseline ${q.baseline_candidates})` : ""}</span>
          <span className="chip">template hit-rate: {Math.round((q.template_hit_rate || 0) * 100)}%</span>
          <span className="chip">no model calls inside the search</span>
        </div>
      ) : (
        <div className="muted text-xs italic">Upload a form to see tokens and search statistics.</div>
      )}
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
    <Modal open={open} onClose={onClose} title="⛰ Hill climbing" subtitle="Two local-search passes clean the OCR output before the single AI call — geometry first, then junk removal. No model calls inside.">
        <div className="flex flex-col gap-5">
          {/* Controls */}
          <section className="rounded-2xl border border-neutral-800 p-4 flex flex-col gap-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="font-medium">Enable hill climbing</div>
                <div className="text-xs text-neutral-400">Off = baseline: split at big gaps only and keep everything below a junk threshold (no search). Useful to compare.</div>
              </div>
              <Toggle on={config.enabled} label="Enable hill climbing" onChange={(v) => onConfigChange({ ...config, enabled: v })} />
            </div>
            <div className={`grid gap-4 sm:grid-cols-2 ${config.enabled ? "" : "opacity-50"}`}>
              <label className="flex flex-col gap-1 text-sm">
                <span className="flex justify-between text-xs text-neutral-400"><span>Random restarts</span><b>{config.restarts}</b></span>
                <input type="range" min={1} max={12} value={config.restarts} disabled={!config.enabled} onChange={(e) => onConfigChange({ ...config, restarts: +e.target.value })} />
                <span className="text-[11px] text-neutral-500">Plain hill climbing gets stuck in local optima; each restart begins from a different initial grouping (cheap CPU work).</span>
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="flex justify-between text-xs text-neutral-400"><span>Max iterations per climb</span><b>{config.maxIterations}</b></span>
                <input type="range" min={10} max={500} step={10} value={config.maxIterations} disabled={!config.enabled} onChange={(e) => onConfigChange({ ...config, maxIterations: +e.target.value })} />
                <span className="text-[11px] text-neutral-500">Steepest ascent: evaluate every neighbour, move to the best, stop at a local optimum.</span>
              </label>
            </div>
            <div className="text-xs text-neutral-400">
              Settings apply to the next upload.
              {limits && (limits.max_restarts < 12 || limits.max_iterations < 1000) && (
                <span className="ml-1 text-amber-300">This server caps the search at {limits.max_restarts} restarts / {limits.max_iterations} iterations (small CPU).</span>
              )}
            </div>
          </section>

          <Combined hc={hc} doc={doc} />

          {/* JSON data files */}
          <section className="rounded-2xl border border-neutral-800 overflow-hidden">
            <div className="flex flex-wrap items-center gap-2 border-b border-neutral-800 bg-white/5 px-3 py-2">
              {[["pass1", "Pass 1 · pass1.data.json"], ["pass2", "Pass 2 · pass2.data.json"], ["schema", "Final · schema.json"]].map(([k, l]) => (
                <button key={k} className={`btn btn-sm ${tab === k ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab(k)}>{l}</button>
              ))}
              <div className="ml-auto flex gap-1.5">
                <button className="btn btn-sm" disabled={!data[tab]} onClick={() => copy(tab)}>Copy</button>
                <button className="btn btn-sm btn-primary" disabled={!data[tab]} onClick={() => download(tab)}>↓ Download</button>
              </div>
            </div>
            <pre className="max-h-80 overflow-auto bg-black p-4 text-[11px] leading-relaxed text-white">
              {loading ? "Loading…" : data[tab] ? pretty(data[tab]) : doc?.status === "done" ? "No data." : "Upload a form to generate the data files."}
            </pre>
            <div className="border-t border-neutral-800 px-3 py-2 text-[11px] text-neutral-400">
              {tab === "pass1" && "Field candidates after grouping: label tokens, value region, separator kind, grouping score."}
              {tab === "pass2" && "The optimized Q&A JSON of the plan: canonical question, original label, expected answer type, bbox, grouping score, junk removed."}
              {tab === "schema" && "Final field schema after AI validation and normalisation — what the editor and exports consume."}
            </div>
          </section>
        </div>
    </Modal>
  );
}
