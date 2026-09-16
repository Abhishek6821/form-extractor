import { useDraggable, useDroppable } from "@dnd-kit/core";
import FieldInput from "./FieldInput";

export const ROW_H = 72; // px per grid row
export const GRID_COLS = 12;

function CanvasField({ field, selected, onSelect, colWidth, onRemove }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `canvas:${field.field_id}`,
    data: { source: "canvas", field },
  });
  const style = {
    left: field.x * colWidth,
    top: field.y * ROW_H,
    width: field.w * colWidth - 8,
    height: field.h * ROW_H - 8,
    transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
    opacity: isDragging ? 0.6 : 1,
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`absolute rounded-xl border bg-white p-2 shadow-sm transition-shadow ${
        selected ? "border-brand-600 ring-2 ring-brand-500/25 shadow-md" : "border-slate-200 hover:shadow-md"
      }`}
      onMouseDown={() => onSelect(field.field_id)}
    >
      <div className="flex items-center justify-between gap-1 mb-1">
        <div className="flex items-center gap-1 min-w-0">
          <button
            className="cursor-grab text-slate-400 hover:text-slate-600 px-1"
            title="Drag to move"
            {...listeners}
            {...attributes}
          >
            ⠿
          </button>
          <span className="text-xs font-medium truncate">
            {field.label}
            {field.required && <span className="text-rose-500"> *</span>}
          </span>
        </div>
        <button
          className="text-slate-400 hover:text-rose-600 text-xs px-1"
          title="Remove"
          onClick={(e) => {
            e.stopPropagation();
            onRemove(field.field_id);
          }}
        >
          ✕
        </button>
      </div>
      <FieldInput field={field} value={field.value} onChange={() => {}} />
    </div>
  );
}

export default function Canvas({ layout, selectedId, onSelect, onRemove, canvasRef, colWidth }) {
  const { setNodeRef, isOver } = useDroppable({ id: "canvas" });
  const rows = Math.max(8, ...layout.fields.map((f) => f.y + f.h + 2));
  return (
    <div
      ref={(el) => {
        setNodeRef(el);
        canvasRef.current = el;
      }}
      className={`relative w-full rounded-2xl border-2 bg-white transition-colors ${
        isOver ? "border-brand-500 bg-brand-50/30" : "border-dashed border-slate-300"
      }`}
      style={{
        height: rows * ROW_H,
        backgroundImage:
          "linear-gradient(to right, rgba(148,163,184,.18) 1px, transparent 1px), linear-gradient(to bottom, rgba(148,163,184,.18) 1px, transparent 1px)",
        backgroundSize: `${colWidth}px ${ROW_H}px`,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onSelect(null);
      }}
    >
      {!layout.fields.length && (
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-1 text-slate-400">
          <div className="text-3xl">⤵</div>
          <div className="text-sm">Drop extracted fields here to build your form</div>
          <div className="text-xs">snaps to a {GRID_COLS}-column grid · drag ⠿ to move · click to edit</div>
        </div>
      )}
      {layout.fields.map((f) => (
        <CanvasField
          key={f.field_id}
          field={f}
          selected={f.field_id === selectedId}
          onSelect={onSelect}
          onRemove={onRemove}
          colWidth={colWidth}
        />
      ))}
    </div>
  );
}
