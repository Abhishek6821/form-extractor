// Thin client for the FastAPI backend (proxied under /api in dev, see vite.config.js).
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

export async function uploadDocument(file, { useLlm } = {}) {
  const fd = new FormData();
  fd.append("file", file);
  const q = new URLSearchParams({ sync: "true" });
  if (useLlm !== undefined) q.set("use_llm", String(useLlm));
  const res = await check(await fetch(`${BASE}/documents?${q}`, { method: "POST", body: fd }));
  return res.json();
}

export async function getDocument(id) {
  return (await check(await fetch(`${BASE}/documents/${id}`))).json();
}

export async function patchField(docId, fieldId, patch) {
  return (
    await check(
      await fetch(`${BASE}/documents/${docId}/fields/${fieldId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      })
    )
  ).json();
}

export async function saveForm(layout, formId) {
  const url = formId ? `${BASE}/forms/${formId}` : `${BASE}/forms`;
  return (
    await check(
      await fetch(url, {
        method: formId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(layout),
      })
    )
  ).json();
}

export async function exportLayout(layout, format) {
  const res = await check(
    await fetch(`${BASE}/export?format=${format}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(layout),
    })
  );
  const blob = await res.blob();
  const name = { pdf: "form.pdf", html: "form.html", json: "form.schema.json" }[format];
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

export async function health() {
  return (await check(await fetch(`${BASE}/health`))).json();
}

export async function getSettings() {
  return (await check(await fetch(`${BASE}/settings`))).json();
}

function adminHeaders(adminToken) {
  return adminToken ? { "X-Admin-Token": adminToken } : {};
}

export async function saveSettings(patch, adminToken) {
  return (
    await check(
      await fetch(`${BASE}/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...adminHeaders(adminToken) },
        body: JSON.stringify(patch),
      })
    )
  ).json();
}

export async function testSettings(adminToken) {
  return (await check(await fetch(`${BASE}/settings/test`, { method: "POST", headers: adminHeaders(adminToken) }))).json();
}
