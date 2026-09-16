import { useMemo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { TYPE_COLORS } from "../fieldTypes";

function PaletteCard({ field, placed }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `palette:${field.field_id}`, data: { source: "palette", field } });
  const pct = Math.round((field.confidence || 0) * 100);
  return (
    <div ref={setNodeRef} {...listeners} {...attributes}
      className={`field-card card-glow ${isDragging ? "opacity-40" : ""} ${placed ? "border-brand-500/50 bg-brand-500/15" : ""}`} title={field.question}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{field.label}</div>
          {field.label_original_language && field.label_original_language !== field.label && (
            <div className="truncate text-xs text-neutral-400">{field.label_original_language}</div>
          )}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className={`badge ${TYPE_COLORS[field.type] || ""}`}>{field.type}</span>
          {field.needs_review && <span className="badge bg-amber-500/20 text-amber-200">review</span>}
          {placed && <span className="badge bg-brand-500/20 text-brand-200">placed</span>}
        </div>
      </div>
      <div className="mt-1 line-clamp-2 text-xs text-neutral-400">{field.question}</div>
      {field.value && (
        <div className="mt-1.5 truncate rounded-md px-2 py-1 text-xs" style={{ background: "var(--surface-2)" }} title={field.raw_value && field.raw_value !== field.value ? `raw: ${field.raw_value}` : ""}>
          <span className="text-neutral-500">value</span> {field.value}
        </div>
      )}
      <div className="mt-2 flex items-center gap-2">
        <div className="h-1 flex-1 rounded bg-white/10">
          <div className={`h-1 rounded ${pct >= 60 ? "bg-emerald-400" : "bg-amber-400"}`} style={{ width: `${pct}%` }} />
        </div>
        <span className="text-[10px] text-neutral-500">{pct}%</span>
      </div>
    </div>
  );
}

export default function FieldPalette({ fields, placedIds, onAddAll }) {
  const [q, setQ] = useState("");
  const [onlyReview, setOnlyReview] = useState(false);
  const shown = useMemo(() => fields.filter((f) => (!onlyReview || f.needs_review) && (!q || `${f.label} ${f.label_original_language} ${f.question}`.toLowerCase().includes(q.toLowerCase()))), [fields, q, onlyReview]);
  return (
    <aside className="flex h-full flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="panel-title">Extracted fields <span className="text-neutral-500">({fields.length})</span></h2>
        <button className="btn btn-sm" onClick={onAddAll} disabled={!fields.length}>Add all</button>
      </div>
      {fields.length > 0 && (
        <div className="flex gap-2">
          <input className="input py-1.5" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className={`btn btn-sm ${onlyReview ? "btn-primary" : ""}`} onClick={() => setOnlyReview(!onlyReview)} title="Only fields flagged for review">⚑</button>
        </div>
      )}
      <div className="flex flex-col gap-2 overflow-y-auto pr-1">
        {shown.map((f) => <PaletteCard key={f.field_id} field={f} placed={placedIds.has(f.field_id)} />)}
        {!fields.length && (
          <div className="muted rounded-xl border border-dashed p-6 text-center text-sm" style={{ borderColor: "var(--border)" }}>
            Upload a form to extract its fields, then drag them onto the canvas.
          </div>
        )}
      </div>
    </aside>
  );
}
