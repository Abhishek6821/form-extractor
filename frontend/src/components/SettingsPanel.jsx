import { FIELD_TYPES } from "../fieldTypes";

export default function SettingsPanel({ field, onChange, onRemove, onPersistCorrection }) {
  if (!field) {
    return (
      <aside>
        <h2 className="panel-title">Field settings</h2>
        <p className="mt-3 rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400">Select a field on the canvas to edit it.</p>
      </aside>
    );
  }
  const set = (patch) => onChange(field.field_id, patch);
  return (
    <aside className="flex flex-col gap-3 text-sm">
      <h2 className="panel-title">Field settings</h2>
      <Labeled label="Label"><input className="input" value={field.label} onChange={(e) => set({ label: e.target.value })} /></Labeled>
      {field.label_original_language && <div className="text-xs text-slate-500">Original: <span className="font-medium text-slate-700">{field.label_original_language}</span></div>}
      <Labeled label="Question"><textarea className="input" rows={2} value={field.question || ""} onChange={(e) => set({ question: e.target.value })} /></Labeled>
      <Labeled label="Type">
        <select className="input" value={field.type} onChange={(e) => set({ type: e.target.value })}>
          {FIELD_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </Labeled>
      {field.type === "multiple-choice" && (
        <Labeled label="Options (one per line)">
          <textarea className="input" rows={3} value={(field.options || []).join("\n")} onChange={(e) => set({ options: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })} />
        </Labeled>
      )}
      <Labeled label="Placeholder"><input className="input" value={field.placeholder || ""} onChange={(e) => set({ placeholder: e.target.value })} /></Labeled>
      <label className="flex items-center gap-2"><input type="checkbox" checked={!!field.required} onChange={(e) => set({ required: e.target.checked })} /> Required</label>
      <div className="grid grid-cols-2 gap-2">
        <Labeled label="Width (cols)"><input type="number" min={2} max={12} className="input" value={field.w} onChange={(e) => set({ w: Math.max(2, Math.min(12, +e.target.value || 2)) })} /></Labeled>
        <Labeled label="Height (rows)"><input type="number" min={1} max={6} className="input" value={field.h} onChange={(e) => set({ h: Math.max(1, Math.min(6, +e.target.value || 1)) })} /></Labeled>
      </div>
      {field.source_document_id && (
        <button className="btn" onClick={() => onPersistCorrection(field)} title="Send this label/type back to the backend as a correction">Save correction to document</button>
      )}
      <button className="btn btn-danger" onClick={() => onRemove(field.field_id)}>Remove from canvas</button>
    </aside>
  );
}

const Labeled = ({ label, children }) => (
  <label className="flex flex-col gap-1">
    <span className="text-xs text-slate-500">{label}</span>
    {children}
  </label>
);
