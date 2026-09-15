import { useEffect, useMemo, useRef, useState } from "react";
import { DndContext, DragOverlay, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import { exportLayout, health, patchField, saveForm, uploadDocument } from "./api";
import { DEFAULT_WIDTH } from "./fieldTypes";
import Canvas, { GRID_COLS, ROW_H } from "./components/Canvas";
import FieldPalette from "./components/FieldPalette";
import Preview from "./components/Preview";
import SettingsPage from "./components/SettingsPage";
import SettingsPanel from "./components/SettingsPanel";
import UploadPanel from "./components/UploadPanel";

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function toLayoutField(f, x, y) {
  const w = DEFAULT_WIDTH[f.type] || 6;
  return {
    field_id: f.field_id,
    label: f.label,
    type: f.type,
    x: clamp(x, 0, GRID_COLS - w),
    y: Math.max(0, y),
    w,
    h: 1,
    required: !!f.required,
    placeholder: "",
    options: f.options || [],
    value: f.value || "",
    // editor-only metadata (stripped before saving)
    question: f.question,
    label_original_language: f.label_original_language,
    source_document_id: f.source_document_id,
  };
}

function nextFreeRow(fields) {
  return fields.length ? Math.max(...fields.map((f) => f.y + f.h)) : 0;
}

/** Push overlapping fields down so nothing sits on top of another (simple collision resolution). */
function resolveOverlaps(fields, movedId) {
  const out = fields.map((f) => ({ ...f }));
  const moved = out.find((f) => f.field_id === movedId);
  if (!moved) return out;
  const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  for (const f of out) {
    if (f.field_id !== movedId && overlaps(moved, f)) f.y = moved.y + moved.h;
  }
  return out;
}

export default function App() {
  const [doc, setDoc] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [layout, setLayout] = useState({ title: "Untitled form", grid_columns: GRID_COLS, fields: [] });
  const [selectedId, setSelectedId] = useState(null);
  const [mode, setMode] = useState("edit"); // edit | preview | settings
  const [active, setActive] = useState(null);
  const [savedId, setSavedId] = useState(null);
  const [status, setStatus] = useState("");
  const [llmAvailable, setLlmAvailable] = useState(false);
  const canvasRef = useRef(null);
  const [colWidth, setColWidth] = useState(80);

  useEffect(() => {
    health().then((h) => setLlmAvailable(!!h.llm_available)).catch(() => {});
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
    setError("");
    try {
      const d = await uploadDocument(file, opts);
      d.fields = (d.fields || []).map((f) => ({ ...f, source_document_id: d.document_id }));
      setDoc(d);
      setLayout({ title: file.name.replace(/\.[^.]+$/, ""), grid_columns: GRID_COLS, fields: [] });
      setSavedId(null);
      setSelectedId(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
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
      let y = nextFreeRow(l.fields);
      let x = 0;
      const out = [...l.fields];
      for (const f of fields) {
        if (out.some((g) => g.field_id === f.field_id)) continue;
        const w = DEFAULT_WIDTH[f.type] || 6;
        if (x + w > GRID_COLS) {
          x = 0;
          y += 1;
        }
        out.push(toLayoutField(f, x, y));
        x += w;
      }
      return { ...l, fields: out };
    });
  }

  function updateField(id, patch) {
    setLayout((l) => ({
      ...l,
      fields: resolveOverlaps(
        l.fields.map((f) => (f.field_id === id ? { ...f, ...patch, x: clamp((patch.x ?? f.x), 0, GRID_COLS - (patch.w ?? f.w)) } : f)),
        id
      ),
    }));
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
      const x = Math.round((translated.left - rect.left) / colWidth);
      const y = Math.round((translated.top - rect.top) / ROW_H);
      addField(data.field, x, y);
    } else if (data.source === "canvas") {
      const f = data.field;
      const x = Math.round(f.x + delta.x / colWidth);
      const y = Math.round(f.y + delta.y / ROW_H);
      updateField(f.field_id, { x: clamp(x, 0, GRID_COLS - f.w), y: Math.max(0, y) });
    }
  }

  function cleanLayout() {
    return {
      title: layout.title,
      source_document_id: doc?.document_id || null,
      grid_columns: GRID_COLS,
      fields: layout.fields.map(({ question, label_original_language, source_document_id, ...f }) => f),
    };
  }

  async function onSave() {
    try {
      const saved = await saveForm(cleanLayout(), savedId);
      setSavedId(saved.form_id);
      setStatus(`Saved as form ${saved.form_id}`);
    } catch (e) {
      setStatus(e.message);
    }
  }

  async function onExport(fmt) {
    try {
      await exportLayout(cleanLayout(), fmt);
    } catch (e) {
      setStatus(e.message);
    }
  }

  async function persistCorrection(f) {
    try {
      await patchField(f.source_document_id, f.field_id, { label: f.label, type: f.type, required: f.required, question: f.question, options: f.options });
      setStatus(`Correction saved for ${f.field_id}`);
    } catch (e) {
      setStatus(e.message);
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b border-slate-200 px-4 py-3 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold mr-2">Form Field Extractor</h1>
        <UploadPanel onUpload={onUpload} busy={busy} doc={doc} error={error} llmAvailable={llmAvailable} onOpenSettings={() => setMode("settings")} />
        <div className="ml-auto flex items-center gap-2">
          <input className="input w-48" value={layout.title} onChange={(e) => setLayout({ ...layout, title: e.target.value })} />
          <button className={`btn ${mode === "edit" ? "btn-primary" : ""}`} onClick={() => setMode("edit")}>
            Edit
          </button>
          <button className={`btn ${mode === "preview" ? "btn-primary" : ""}`} onClick={() => setMode("preview")}>
            Preview
          </button>
          <button className={`btn ${mode === "settings" ? "btn-primary" : ""}`} onClick={() => setMode("settings")} title="API key & Claude options">
            ⚙ Settings
          </button>
          <button className="btn" onClick={onSave} disabled={!layout.fields.length}>
            Save
          </button>
          <div className="flex rounded-md border border-slate-300 overflow-hidden">
            {["pdf", "html", "json"].map((f) => (
              <button key={f} className="px-2 py-1.5 text-xs bg-white hover:bg-slate-50 border-r last:border-r-0 border-slate-300 disabled:opacity-50" disabled={!layout.fields.length} onClick={() => onExport(f)}>
                Export {f.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
      </header>
      {status && <div className="bg-indigo-50 text-indigo-800 text-xs px-4 py-1">{status}</div>}

      {mode === "settings" ? (
        <main className="flex-1">
          <SettingsPage onChanged={(st) => setLlmAvailable(st.llm_enabled && st.has_api_key)} />
        </main>
      ) : mode === "preview" ? (
        <main className="flex-1 p-6">
          <Preview layout={layout} />
        </main>
      ) : (
        <DndContext sensors={sensors} onDragStart={(e) => setActive(e.active.data.current)} onDragEnd={onDragEnd} onDragCancel={() => setActive(null)}>
          <main className="flex-1 grid gap-4 p-4" style={{ gridTemplateColumns: "280px minmax(0, 1fr) 280px" }}>
            <div className="rounded-xl bg-white/60 p-3 border border-slate-200 max-h-[calc(100vh-7rem)] overflow-hidden">
              <FieldPalette fields={fields} placedIds={placedIds} onAddAll={addAll} />
            </div>
            <div className="overflow-auto">
              <Canvas layout={layout} selectedId={selectedId} onSelect={setSelectedId} onRemove={removeField} canvasRef={canvasRef} colWidth={colWidth} />
            </div>
            <div className="rounded-xl bg-white/60 p-3 border border-slate-200">
              <SettingsPanel field={selected} onChange={updateField} onRemove={removeField} onPersistCorrection={persistCorrection} />
            </div>
          </main>
          <DragOverlay>
            {active?.source === "palette" && (
              <div className="field-card w-64 shadow-lg border-indigo-400">
                <div className="font-medium">{active.field.label}</div>
                <div className="text-xs text-slate-500">{active.field.type}</div>
              </div>
            )}
          </DragOverlay>
        </DndContext>
      )}
    </div>
  );
}
