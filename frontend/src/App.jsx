import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DndContext, DragOverlay, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import { exportLayout, getSettings, health, patchField, saveForm, uploadDocument } from "./api";
import { DEFAULT_WIDTH } from "./fieldTypes";
import Canvas, { GRID_COLS, ROW_H } from "./components/Canvas";
import FieldPalette from "./components/FieldPalette";
import Home from "./components/Home";
import UploadPage from "./components/UploadPage";
import CriteriaPanel from "./components/CriteriaPanel";
import HillClimbDialog from "./components/HillClimbDialog";
import Preview from "./components/Preview";
import SettingsPage from "./components/SettingsPage";
import SettingsPanel from "./components/SettingsPanel";
import UploadPanel from "./components/UploadPanel";
import { Logo, Toast } from "./components/ui";

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const PROVIDER_LABEL = { claude: "Claude", gemini: "Gemini", kimi: "Kimi" };

function toLayoutField(f, x, y) {
  const w = DEFAULT_WIDTH[f.type] || 6;
  return {
    field_id: f.field_id, label: f.label, type: f.type,
    x: clamp(x, 0, GRID_COLS - w), y: Math.max(0, y), w, h: 1,
    required: !!f.required, placeholder: "", options: f.options || [], value: f.value || "",
    // editor-only metadata (stripped before saving)
    question: f.question, label_original_language: f.label_original_language, source_document_id: f.source_document_id,
  };
}

const nextFreeRow = (fields) => (fields.length ? Math.max(...fields.map((f) => f.y + f.h)) : 0);

/** Push overlapping fields down so nothing sits on top of another. */
function resolveOverlaps(fields, movedId) {
  const out = fields.map((f) => ({ ...f }));
  const moved = out.find((f) => f.field_id === movedId);
  if (!moved) return out;
  const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  for (const f of out) if (f.field_id !== movedId && overlaps(moved, f)) f.y = moved.y + moved.h;
  return out;
}

export default function App() {
  const [doc, setDoc] = useState(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState({ stage: "", ms: 0 });
  const [layout, setLayout] = useState({ title: "Untitled form", grid_columns: GRID_COLS, fields: [] });
  const [selectedId, setSelectedId] = useState(null);
  const ROUTES = ["home", "upload", "edit", "preview", "settings"];
  const readRoute = () => { const h = (window.location.hash || "").replace(/^#\/?/, ""); return ROUTES.includes(h) ? h : "home"; };
  const [mode, setModeState] = useState(readRoute); // home | upload | edit | preview | settings
  const setMode = (m) => { setModeState(m); if (window.location.hash !== `#/${m}`) window.location.hash = `#/${m}`; };
  useEffect(() => {
    const onHash = () => setModeState(readRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const [active, setActive] = useState(null);
  const [savedId, setSavedId] = useState(null);
  const [toast, setToast] = useState(null);
  const [backend, setBackend] = useState({ llm_available: false, provider: "gemini" });
  const [hcOpen, setHcOpen] = useState(false);
  const [criteriaOpen, setCriteriaOpen] = useState(false);
  const [hcConfig, setHcConfig] = useState(() => {
    try { return { enabled: true, restarts: 6, maxIterations: 150, ...JSON.parse(localStorage.getItem("hillClimb") || "{}") }; } catch { return { enabled: true, restarts: 6, maxIterations: 150 }; }
  });
  const updateHc = (c) => { setHcConfig(c); try { localStorage.setItem("hillClimb", JSON.stringify(c)); } catch {} };
  const canvasRef = useRef(null);
  const [colWidth, setColWidth] = useState(80);
  const notify = useCallback((t) => setToast({ ...t, id: Date.now() }), []);

  useEffect(() => {
    health().then(setBackend).catch(() => notify({ ok: false, text: "Backend is not reachable. Start the API or check the deployment." }));
  }, []);

  useEffect(() => {
    const measure = () => canvasRef.current && setColWidth(canvasRef.current.clientWidth / GRID_COLS);
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [mode, doc]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const fields = doc?.fields || [];
  const placedIds = useMemo(() => new Set(layout.fields.map((f) => f.field_id)), [layout]);
  const selected = layout.fields.find((f) => f.field_id === selectedId) || null;

  async function onUpload(file, opts) {
    setBusy(true);
    setProgress({ stage: "uploading", ms: 0 });
    try {
      const d = await uploadDocument(file, { ...opts, hillClimb: hcConfig, onProgress: (stage, ms) => setProgress({ stage, ms }) });
      d.fields = (d.fields || []).map((f) => ({ ...f, source_document_id: d.document_id }));
      setDoc(d);
      setLayout({ title: file.name.replace(/\.[^.]+$/, ""), grid_columns: GRID_COLS, fields: [] });
      setSavedId(null);
      setSelectedId(null);
      if (d.status === "done") setMode("edit");
      if (d.status === "done") notify({ ok: true, text: `${d.cached ? "Instant (already processed) · " : ""}${d.fields.length} fields extracted · ${d.qa?.junk_candidates_removed ?? 0} junk removed${d.hill_climb?.enabled ? "" : " (hill climbing off)"}${d.llm_used ? ` · ${PROVIDER_LABEL[d.llm_provider] || d.llm_provider}` : " · no AI call needed"}` });
      else if (d.status === "rejected") notify({ ok: false, text: "This document doesn't look like a form, so no fields were extracted." });
      else if (d.status === "error") notify({ ok: false, text: d.error });
    } catch (e) {
      // 422 = not a form: keep the previous document on screen, just explain.
      const msg = e.message.replace(/^\d{3}:\s*/, "");
      notify({ ok: false, text: msg });
    } finally {
      setBusy(false);
      setProgress({ stage: "", ms: 0 });
    }
  }

  function reopen(d) {
    d.fields = (d.fields || []).map((f) => ({ ...f, source_document_id: d.document_id }));
    setDoc(d);
    setLayout({ title: (d.filename || "form").replace(/\.[^.]+$/, ""), grid_columns: GRID_COLS, fields: [] });
    setSavedId(null);
    setSelectedId(null);
    setMode("edit");
  }

  function addField(f, x, y) {
    setLayout((l) => {
      if (l.fields.some((g) => g.field_id === f.field_id)) return l;
      const nf = toLayoutField(f, x, y);
      return { ...l, fields: resolveOverlaps([...l.fields, nf], nf.field_id) };
    });
    setSelectedId(f.field_id);
  }

  function addAll() {
    setLayout((l) => {
      let y = nextFreeRow(l.fields), x = 0;
      const out = [...l.fields];
      for (const f of fields) {
        if (out.some((g) => g.field_id === f.field_id)) continue;
        const w = DEFAULT_WIDTH[f.type] || 6;
        if (x + w > GRID_COLS) { x = 0; y += 1; }
        out.push(toLayoutField(f, x, y));
        x += w;
      }
      return { ...l, fields: out };
    });
  }

  function updateField(id, patch) {
    setLayout((l) => ({ ...l, fields: resolveOverlaps(l.fields.map((f) => (f.field_id === id ? { ...f, ...patch, x: clamp(patch.x ?? f.x, 0, GRID_COLS - (patch.w ?? f.w)) } : f)), id) }));
  }

  function removeField(id) {
    setLayout((l) => ({ ...l, fields: l.fields.filter((f) => f.field_id !== id) }));
    if (selectedId === id) setSelectedId(null);
  }

  function onDragEnd(event) {
    setActive(null);
    const { active, over, delta } = event;
    if (!over || over.id !== "canvas" || !canvasRef.current) return;
    const data = active.data.current;
    const rect = canvasRef.current.getBoundingClientRect();
    const translated = active.rect.current.translated;
    if (data.source === "palette") {
      addField(data.field, Math.round((translated.left - rect.left) / colWidth), Math.round((translated.top - rect.top) / ROW_H));
    } else if (data.source === "canvas") {
      const f = data.field;
      updateField(f.field_id, { x: clamp(Math.round(f.x + delta.x / colWidth), 0, GRID_COLS - f.w), y: Math.max(0, Math.round(f.y + delta.y / ROW_H)) });
    }
  }

  const cleanLayout = () => ({
    title: layout.title, source_document_id: doc?.document_id || null, grid_columns: GRID_COLS,
    fields: layout.fields.map(({ question, label_original_language, source_document_id, ...f }) => f),
  });

  async function onSave() {
    try {
      const saved = await saveForm(cleanLayout(), savedId);
      setSavedId(saved.form_id);
      notify({ ok: true, text: `Saved as form ${saved.form_id}` });
    } catch (e) { notify({ ok: false, text: e.message }); }
  }

  async function onExport(fmt) {
    try { await exportLayout(cleanLayout(), fmt); } catch (e) { notify({ ok: false, text: e.message }); }
  }

  async function persistCorrection(f) {
    try {
      await patchField(f.source_document_id, f.field_id, { label: f.label, type: f.type, required: f.required, question: f.question, options: f.options });
      notify({ ok: true, text: `Correction saved for ${f.field_id}` });
    } catch (e) { notify({ ok: false, text: e.message }); }
  }

  const providerLabel = PROVIDER_LABEL[backend.provider] || "AI";

  return (
    <div className="flex min-h-screen flex-col">
      {/* Top bar: logo · nav · actions */}
      <header className="topbar sticky top-0 z-20">
        <div className="grid h-14 grid-cols-[1fr_auto_1fr] items-center gap-4 px-4">
          <div className="flex items-center gap-2 justify-self-start">
            {mode !== "home" && (
              <button className="btn btn-ghost btn-sm" onClick={() => { if (window.history.length > 1) window.history.back(); else setMode("home"); }} title="Go back" aria-label="Back">← Back</button>
            )}
            <button onClick={() => setMode("home")} aria-label="Home"><Logo /></button>
          </div>
          <nav className="seg justify-self-center">
            {[["home", "Home"], ["upload", "Upload"], ["edit", "Editor"], ["preview", "Preview"], ["settings", "Settings"]].map(([id, l]) => (
              <button key={id} data-active={mode === id} onClick={() => setMode(id)} disabled={(id === "edit" || id === "preview") && !doc} className="disabled:opacity-40">{l}</button>
            ))}
          </nav>
          <div className="flex items-center gap-2 justify-self-end">
            <span className="chip hidden md:inline-flex" title={backend.llm_available ? "AI validation available" : "Add an API key in Settings"}>
              <span className={`h-1.5 w-1.5 rounded-full ${backend.llm_available ? "bg-emerald-400" : "bg-amber-400"}`} />
              {providerLabel}
            </span>
            <button className={`btn btn-sm ${hcConfig.enabled ? "" : "border-amber-500/50 text-amber-200"}`} onClick={() => setHcOpen(true)} title="Hill-climb passes: enable/disable, tune, inspect data files and token savings">
              ⛰ Hill climbing{hcConfig.enabled ? "" : " · off"}
            </button>
            {mode !== "upload" && <button className="btn btn-primary btn-sm" onClick={() => setMode("upload")}>↑ Upload</button>}
          </div>
        </div>
        {(mode === "edit" || mode === "preview") && doc && (
          <div className="flex flex-wrap items-center gap-2 border-t px-4 py-2" style={{ borderColor: "var(--border)" }}>
            <input className="input w-56 py-1.5" value={layout.title} onChange={(e) => setLayout({ ...layout, title: e.target.value })} aria-label="Form title" placeholder="Form title" />
            <UploadPanel onUpload={onUpload} busy={busy} doc={doc} llmAvailable={backend.llm_available} providerLabel={providerLabel}
              onOpenSettings={() => setMode("settings")} onOpenCriteria={() => setCriteriaOpen(true)} compact statsOnly />
            <div className="ml-auto flex items-center gap-1.5">
              <span className="muted mr-1 text-xs">{layout.fields.length} on canvas</span>
              <button className="btn btn-sm" onClick={onSave} disabled={!layout.fields.length}>{savedId ? "Save changes" : "Save form"}</button>
              <div className="seg" title="Export the form you built on the canvas">
                {[["pdf", "PDF"], ["html", "HTML"], ["json", "Schema"]].map(([f, label]) => (
                  <button key={f} disabled={!layout.fields.length} onClick={() => onExport(f)} className="disabled:opacity-40">{label}</button>
                ))}
              </div>
            </div>
          </div>
        )}
      </header>

      {mode === "settings" ? (
        <main className="flex-1">
          <SettingsPage notify={notify} onChanged={(st) => setBackend((b) => ({ ...b, provider: st.provider, llm_available: st.llm_enabled && st.providers[st.provider].has_api_key }))} />
        </main>
      ) : mode === "preview" ? (
        <main className="flex-1 p-6"><Preview layout={layout} /></main>
      ) : mode === "home" ? (
        <main className="flex-1"><Home onStart={() => setMode("upload")} onSettings={() => setMode("settings")} backend={backend} providerLabel={providerLabel} /></main>
      ) : mode === "upload" || !doc ? (
        <main className="flex-1"><UploadPage onUpload={onUpload} busy={busy} progress={progress} llmAvailable={backend.llm_available} providerLabel={providerLabel}
          onOpenCriteria={() => setCriteriaOpen(true)} onOpenSettings={() => setMode("settings")} onOpenHillClimb={() => setHcOpen(true)} hcConfig={hcConfig} onReopen={reopen} /></main>
      ) : (
        <DndContext sensors={sensors} onDragStart={(e) => setActive(e.active.data.current)} onDragEnd={onDragEnd} onDragCancel={() => setActive(null)}>
          <main className="grid flex-1 gap-4 p-4" style={{ gridTemplateColumns: "300px minmax(0, 1fr) 300px" }}>
            <div className="panel max-h-[calc(100vh-8.5rem)] overflow-hidden p-3"><FieldPalette fields={fields} placedIds={placedIds} onAddAll={addAll} isForm={doc ? doc.is_form : true} /></div>
            <div className="overflow-auto"><Canvas layout={layout} selectedId={selectedId} onSelect={setSelectedId} onRemove={removeField} canvasRef={canvasRef} colWidth={colWidth} /></div>
            <div className="panel p-3"><SettingsPanel field={selected} onChange={updateField} onRemove={removeField} onPersistCorrection={persistCorrection} /></div>
          </main>
          <DragOverlay>
            {active?.source === "palette" && (
              <div className="field-card w-64 border-brand-500 shadow-xl">
                <div className="font-medium">{active.field.label}</div>
                <div className="muted text-xs">{active.field.type}</div>
              </div>
            )}
          </DragOverlay>
        </DndContext>
      )}

      <footer className="muted mt-auto flex flex-wrap items-center gap-3 border-t px-4 py-2 text-[11px]" style={{ borderColor: "var(--border)" }}>
        <span>API {backend.version ? `v${backend.version}` : "…"}</span>
        <span>· provider <b className="font-medium" style={{ color: "var(--text)" }}>{providerLabel}</b>{backend.llm_available ? "" : " (no key)"}</span>
        <span>· readers {(backend.ocr_backends || []).join(", ") || "…"}</span>
        {backend.limits && backend.limits.max_restarts < 12 && <span>· search capped at {backend.limits.max_restarts} restarts on this server</span>}
        <span className="ml-auto">Drag <span className="kbd">⠿</span> to move · <span className="kbd">Esc</span> closes dialogs</span>
      </footer>

      <CriteriaPanel open={criteriaOpen} onClose={() => setCriteriaOpen(false)} />
      <HillClimbDialog open={hcOpen} onClose={() => setHcOpen(false)} config={hcConfig} onConfigChange={updateHc} doc={doc} notify={notify} limits={backend.limits} />
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}
