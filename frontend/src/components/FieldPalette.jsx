import { useDraggable } from "@dnd-kit/core";
import { TYPE_COLORS } from "../fieldTypes";

function PaletteCard({ field, placed }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `palette:${field.field_id}`,
    data: { source: "palette", field },
  });
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={`field-card ${isDragging ? "opacity-40" : ""} ${placed ? "border-indigo-300 bg-indigo-50/40" : ""}`}
      title={field.question}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium truncate">{field.label}</div>
          {field.label_original_language && field.label_original_language !== field.label && (
            <div className="text-xs text-slate-500 truncate">{field.label_original_language}</div>
          )}
          <div className="text-xs text-slate-500 line-clamp-2">{field.question}</div>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <span className={`badge ${TYPE_COLORS[field.type] || ""}`}>{field.type}</span>
          {field.needs_review && <span className="badge bg-orange-100 text-orange-800">review</span>}
          {placed && <span className="badge bg-indigo-100 text-indigo-700">placed</span>}
        </div>
      </div>
      {field.value && <div className="mt-1 text-xs text-slate-600">value: {field.value}</div>}
      <div className="mt-1 h-1 rounded bg-slate-100">
        <div className="h-1 rounded bg-emerald-400" style={{ width: `${Math.round((field.confidence || 0) * 100)}%` }} />
      </div>
    </div>
  );
}

export default function FieldPalette({ fields, placedIds, onAddAll }) {
  return (
    <aside className="flex flex-col gap-2 h-full">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-600">Extracted fields ({fields.length})</h2>
        <button className="btn text-xs" onClick={onAddAll} disabled={!fields.length}>
          Add all
        </button>
      </div>
      <p className="text-xs text-slate-500">Drag a field onto the canvas.</p>
      <div className="flex flex-col gap-2 overflow-y-auto pr-1">
        {fields.map((f) => (
          <PaletteCard key={f.field_id} field={f} placed={placedIds.has(f.field_id)} />
        ))}
        {!fields.length && <div className="text-sm text-slate-400 italic">Upload a form to extract its fields.</div>}
      </div>
    </aside>
  );
}
