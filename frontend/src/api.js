// Thin client for the FastAPI backend (proxied under /api in dev and on Netlify).
import { API_BASE as BASE } from "./config";

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

export async function getDocument(id) {
  return (await check(await fetch(`${BASE}/documents/${id}`))).json();
}

/** Upload (returns in well under a second), then poll until done. `onProgress(stage, elapsedMs)`. */
export async function uploadDocument(file, { useLlm, ocrBackend, hillClimb, aiMode, onProgress } = {}) {
  const fd = new FormData();
  fd.append("file", file);
  const q = new URLSearchParams({ sync: "false" });
  if (useLlm !== undefined) q.set("use_llm", String(useLlm));
  if (ocrBackend) q.set("ocr_backend", ocrBackend);
  if (aiMode) q.set("ai_mode", aiMode);
  if (hillClimb) {
    q.set("hill_climb", String(!!hillClimb.enabled));
    q.set("restarts", String(hillClimb.restarts ?? 6));
    q.set("max_iterations", String(hillClimb.maxIterations ?? 150));
  }
  const started = Date.now();
  onProgress?.("uploading", 0);
  let doc = await (await check(await fetch(`${BASE}/documents?${q}`, { method: "POST", body: fd }))).json();
  if (doc.status === "done" || doc.status === "error") return doc; // cache hit or sync
  onProgress?.("queued", Date.now() - started);
  let delay = 700;
  for (;;) {
    await new Promise((r) => setTimeout(r, delay));
    try {
      doc = await getDocument(doc.document_id);
    } catch (e) {
      if (Date.now() - started > 300000) throw e;
      continue;
    }
    if (doc.status === "done" || doc.status === "error" || doc.status === "rejected") {
      if (doc.status === "rejected") throw new Error(doc.error || "Only forms can be uploaded.");
      return doc;
    }
    onProgress?.(doc.stage || doc.status, Date.now() - started);
    if (Date.now() - started > 300000) throw new Error("Timed out waiting for the document.");
    delay = Math.min(delay + 200, 2000);
  }
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
