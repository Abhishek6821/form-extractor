// Renders an actual editable input matching the field type (used on the canvas and in preview).
export default function FieldInput({ field, value, onChange, disabled }) {
  const common = { disabled, className: "input", value: value ?? "", onChange: (e) => onChange?.(e.target.value) };
  switch (field.type) {
    case "date":
      return <input type="date" {...common} />;
    case "number":
      return <input type="number" {...common} placeholder={field.placeholder} />;
    case "checkbox":
      return (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            disabled={disabled}
            checked={value === "true" || value === true}
            onChange={(e) => onChange?.(String(e.target.checked))}
          />
          <span>{field.placeholder || "Yes"}</span>
        </label>
      );
    case "multiple-choice":
      return (
        <select {...common}>
          <option value="">—</option>
          {(field.options || []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      );
    case "signature":
      return (
        <div className="h-12 rounded border border-dashed border-slate-400 bg-slate-50 text-xs text-slate-400 flex items-center justify-center">
          Sign here
        </div>
      );
    case "table-cell":
      return <input type="text" {...common} className="input font-mono" placeholder={field.placeholder} />;
    default:
      return <input type="text" {...common} placeholder={field.placeholder} />;
  }
}
