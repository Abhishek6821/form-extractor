import { useEffect, useState } from "react";

const BASE = import.meta.env.VITE_API_BASE || "/api";
const LANG = { en: "English", hi: "Hindi", es: "Spanish", fr: "French", de: "German", zh: "Chinese", ja: "Japanese", ar: "Arabic", ru: "Russian / Portuguese", ta: "Tamil / Telugu" };

/** "Try a sample form" — fetches one of the bundled multilingual forms and uploads it. */
export default function SamplesMenu({ onPick, disabled }) {
  const [samples, setSamples] = useState([]);
  useEffect(() => {
    fetch(`${BASE}/samples`).then((r) => r.json()).then(setSamples).catch(() => {});
  }, []);
  if (!samples.length) return null;
  return (
    <select
      className="input w-44 py-1.5 text-xs"
      value=""
      disabled={disabled}
      onChange={async (e) => {
        const name = e.target.value;
        if (!name) return;
        const blob = await (await fetch(`${BASE}/samples/${name}`)).blob();
        onPick(new File([blob], name, { type: "application/pdf" }));
      }}
      title="Upload one of the bundled sample forms"
    >
      <option value="">Try a sample form…</option>
      {samples.map((s) => (
        <option key={s.name} value={s.name}>{LANG[s.language] || s.language} · {s.name.replace(/^[a-z]{2}_/, "").replace(".pdf", "").replace(/_/g, " ")}</option>
      ))}
    </select>
  );
}
