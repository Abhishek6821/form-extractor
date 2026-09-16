// Thin client for the FastAPI backend (proxied under /api in dev and on Netlify).
const BASE = import.meta.env.VITE_API_BASE || "/api";

async function check(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res;
}

const json = (method, body, extra = {}) => ({ method, headers: { "Content-Type": "application/json", ...extra }, body: JSON.stringify(body) });

export async function health() {
  return (await check(await fetch(`${BASE}/health`))).json();
}

export async function uploadDocument(file, { useLlm, ocrBackend, hillClimb } = {}) {
  const fd = new FormData();
  fd.append("file", file);
  const q = new URLSearchParams({ sync: "true" });
  if (useLlm !== undefined) q.set("use_llm", String(useLlm));
  if (ocrBackend) q.set("ocr_backend", ocrBackend);
  if (hillClimb) {
    q.set("hill_climb", String(!!hillClimb.enabled));
    q.set("restarts", String(hillClimb.restarts ?? 6));
    q.set("max_iterations", String(hillClimb.maxIterations ?? 150));
  }
  return (await check(await fetch(`${BASE}/documents?${q}`, { method: "POST", body: fd }))).json();
}

export async function patchField(docId, fieldId, patch) {
  return (await check(await fetch(`${BASE}/documents/${docId}/fields/${fieldId}`, json("PATCH", patch)))).json();
}

export async function saveForm(layout, formId) {
  const url = formId ? `${BASE}/forms/${formId}` : `${BASE}/forms`;
  return (await check(await fetch(url, json(formId ? "PUT" : "POST", layout)))).json();
}

export async function exportLayout(layout, format) {
  const res = await check(await fetch(`${BASE}/export?format=${format}`, json("POST", layout)));
  const blob = await res.blob();
  const name = { pdf: "form.pdf", html: "form.html", json: "form.schema.json" }[format];
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

const adminHeaders = (t) => (t ? { "X-Admin-Token": t } : {});

export async function getSettings() {
  return (await check(await fetch(`${BASE}/settings`))).json();
}

export async function saveSettings(patch, adminToken) {
  return (await check(await fetch(`${BASE}/settings`, json("PUT", patch, adminHeaders(adminToken))))).json();
}

export async function testSettings(adminToken) {
  return (await check(await fetch(`${BASE}/settings/test`, { method: "POST", headers: adminHeaders(adminToken) }))).json();
}

export async function listModels() {
  return (await check(await fetch(`${BASE}/settings/models`))).json();
}
