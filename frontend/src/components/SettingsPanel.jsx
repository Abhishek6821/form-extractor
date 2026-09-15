import { FIELD_TYPES } from "../fieldTypes";

export default function SettingsPanel({ field, onChange, onRemove, onPersistCorrection }) {
  if (!field) {
    return (
      <aside className="text-sm text-slate-400 italic">Select a field on the canvas to edit its settings.</aside>
    );
  }
  const set = (patch) => onChange(field.field_id, patch);
  return (
    <aside className="flex flex-col gap-3 text-sm">
      <h2 className="text-sm font-semibold text-slate-600">Field settings</h2>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-slate-500">Label</span>
        <input className="input" value={field.label} onChange={(e) => set({ label: e.target.value })} />
      </label>
      {field.label_original_language && (
        <div className="text-xs text-slate-500">
          Original: <span className="font-medium text-slate-700">{field.label_original_language}</span>
        </div>
      )}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-slate-500">Question</span>
        <textarea className="input" rows={2} value={field.question || ""} onChange={(e) => set({ question: e.target.value })} />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-slate-500">Type</span>
        <select className="input" value={field.type} onChange={(e) => set({ type: e.target.value })}>
          {FIELD_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>
      {field.type === "multiple-choice" && (
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-500">Options (one per line)</span>
          <textarea
            className="input"
            rows={3}
            value={(field.options || []).join("\n")}
            onChange={(e) => set({ options: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })}
          />
        </label>
      )}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-slate-500">Placeholder</span>
        <input className="input" value={field.placeholder || ""} onChange={(e) => set({ placeholder: e.target.value })} />
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={!!field.required} onChange={(e) => set({ required: e.target.checked })} />
        <span>Required</span>
      </label>
      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-500">Width (cols)</span>
          <input type="number" min={2} max={12} className="input" value={field.w} onChange={(e) => set({ w: Math.max(2, Math.min(12, +e.target.value || 2)) })} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-slate-500">Height (rows)</span>
          <input type="number" min={1} max={6} className="input" value={field.h} onChange={(e) => set({ h: Math.max(1, Math.min(6, +e.target.value || 1)) })} />
        </label>
      </div>
      {field.source_document_id && (
        <button className="btn" onClick={() => onPersistCorrection(field)} title="Send this label/type back to the backend as a correction">
          Save correction to document
        </button>
      )}
      <button className="btn text-rose-600" onClick={() => onRemove(field.field_id)}>
        Remove from canvas
      </button>
    </aside>
  );
}
