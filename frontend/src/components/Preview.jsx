import { useState } from "react";
import FieldInput from "./FieldInput";
import { GRID_COLS } from "./Canvas";

// Live preview: the arranged fields rendered as a real fillable form.
export default function Preview({ layout }) {
  const [values, setValues] = useState({});
  const [submitted, setSubmitted] = useState(null);
  const sorted = [...layout.fields].sort((a, b) => a.y - b.y || a.x - b.x);
  return (
    <div className="panel mx-auto max-w-3xl p-8 fade-up" style={{ boxShadow: "0 24px 60px -30px rgba(15,23,42,.35)" }}>
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">{layout.title}</h1>
      <p className="muted mb-6 text-sm">Live preview — this is how the exported form behaves.</p>
      <form
        className="grid gap-x-4 gap-y-3"
        style={{ gridTemplateColumns: `repeat(${GRID_COLS}, minmax(0, 1fr))` }}
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(values);
        }}
      >
        {sorted.map((f) => (
          <label key={f.field_id} className="flex flex-col gap-1 text-sm" style={{ gridColumn: `span ${Math.min(f.w, GRID_COLS)}` }}>
            <span className="font-medium">
              {f.label}
              {f.required && <span className="text-rose-500"> *</span>}
            </span>
            <FieldInput field={f} value={values[f.field_id]} onChange={(v) => setValues({ ...values, [f.field_id]: v })} />
          </label>
        ))}
        <div className="col-span-full flex gap-2 mt-2">
          <button className="btn btn-primary" type="submit">
            Submit
          </button>
          <button className="btn" type="button" onClick={() => setValues({})}>
            Reset
          </button>
        </div>
      </form>
      {submitted && (
        <pre className="mt-4 overflow-x-auto rounded-xl bg-slate-900 p-4 text-xs text-slate-100">{JSON.stringify(submitted, null, 2)}</pre>
      )}
    </div>
  );
}
