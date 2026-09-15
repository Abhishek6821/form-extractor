import { useEffect, useState } from "react";
import { getSettings, saveSettings, testSettings } from "../api";

export default function SettingsPage({ onChanged }) {
  const [s, setS] = useState(null);
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null); // {ok, text}
  const [admin, setAdmin] = useState(() => {
    try {
      return sessionStorage.getItem("adminToken") || "";
    } catch {
      return "";
    }
  });

  useEffect(() => {
    getSettings().then(setS).catch((e) => setMsg({ ok: false, text: e.message }));
  }, []);

  if (!s) return <div className="p-6 text-sm text-slate-500">Loading settings…</div>;

  async function persist(patch) {
    setBusy(true);
    setMsg(null);
    try {
      const next = await saveSettings(patch, admin);
      setS(next);
      onChanged?.(next);
      return next;
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function onSaveKey() {
    const next = await persist({ anthropic_api_key: key });
    if (next) {
      setKey("");
      setMsg({ ok: true, text: "API key saved. Click “Test connection” to verify it." });
    }
  }

  async function onTest() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await testSettings(admin);
      setMsg(r.ok ? { ok: true, text: `Connected — model ${r.model} is reachable.` } : { ok: false, text: r.error });
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl p-6 flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-sm text-slate-500 mt-1">
          Add your Anthropic API key to enable Claude: it validates and translates extracted fields in one call per
          document, and reads scanned images/photos that have no text layer.
        </p>
      </div>

      {s.admin_required && (
        <section className="rounded-xl bg-amber-50 border border-amber-200 p-4 flex flex-col gap-2">
          <h2 className="font-medium text-amber-900">Admin token</h2>
          <p className="text-xs text-amber-800">
            This is a shared deployment: only the owner can change these settings. Enter the admin token
            (the server's <code>FORM_ADMIN_TOKEN</code>).
          </p>
          <input
            className="input font-mono"
            type="password"
            placeholder="admin token"
            value={admin}
            onChange={(e) => {
              setAdmin(e.target.value);
              try {
                sessionStorage.setItem("adminToken", e.target.value);
              } catch {}
            }}
          />
        </section>
      )}

      <section className="rounded-xl bg-white border border-slate-200 p-4 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="font-medium">Anthropic API key</h2>
          {s.has_api_key ? (
            <span className="badge bg-emerald-100 text-emerald-800">
              key set {s.api_key_hint} ({s.key_source === "env" ? "from environment" : "saved"})
            </span>
          ) : (
            <span className="badge bg-amber-100 text-amber-800">no key</span>
          )}
        </div>
        <div className="flex gap-2">
          <input
            className="input font-mono"
            type={showKey ? "text" : "password"}
            placeholder="sk-ant-…"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="off"
          />
          <button className="btn" onClick={() => setShowKey(!showKey)} type="button">
            {showKey ? "Hide" : "Show"}
          </button>
          <button className="btn btn-primary" disabled={busy || !key.trim()} onClick={onSaveKey}>
            Save key
          </button>
        </div>
        <div className="flex gap-2">
          <button className="btn" disabled={busy || !s.has_api_key} onClick={onTest}>
            Test connection
          </button>
          {s.has_api_key && s.key_source === "settings" && (
            <button className="btn text-rose-600" disabled={busy} onClick={() => persist({ anthropic_api_key: "" })}>
              Remove key
            </button>
          )}
        </div>
        <p className="text-xs text-slate-500">
          The key is stored on the backend only and never sent back to the browser in full. Get one at console.anthropic.com.
        </p>
      </section>

      <section className="rounded-xl bg-white border border-slate-200 p-4 flex flex-col gap-3">
        <h2 className="font-medium">Claude features</h2>
        <label className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm font-medium">Enable Claude</div>
            <div className="text-xs text-slate-500">Single batched validation call per document (labels, types, values, review flags).</div>
          </div>
          <input type="checkbox" className="h-5 w-5" checked={s.llm_enabled} disabled={busy} onChange={(e) => persist({ llm_enabled: e.target.checked })} />
        </label>
        <label className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm font-medium">Read scanned images with Claude</div>
            <div className="text-xs text-slate-500">
              Used when a page has no text layer and the built-in OS reader can't read it (any language / script).
            </div>
          </div>
          <input type="checkbox" className="h-5 w-5" checked={s.vision_ocr_enabled} disabled={busy || !s.llm_enabled} onChange={(e) => persist({ vision_ocr_enabled: e.target.checked })} />
        </label>
        <label className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm font-medium">Model</div>
            <div className="text-xs text-slate-500">Opus for best accuracy; Sonnet / Haiku are cheaper.</div>
          </div>
          <select className="input w-56" value={s.model} disabled={busy} onChange={(e) => persist({ model: e.target.value })}>
            {s.models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="rounded-xl bg-slate-50 border border-slate-200 p-4 text-xs text-slate-600">
        <div className="font-medium text-slate-700 mb-1">How documents are read</div>
        <ul className="list-disc pl-4 space-y-1">
          <li>PDFs with a text layer: read directly — free, no key needed.</li>
          <li>Scanned PDFs / images: the built-in OS text reader is tried first (macOS), then Claude if enabled.</li>
          <li>Everything else (form detection, field grouping, junk pruning, question templates) runs locally with no model calls.</li>
        </ul>
      </section>

      {msg && (
        <div className={`rounded-md px-3 py-2 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-rose-50 text-rose-800"}`}>{msg.text}</div>
      )}
    </div>
  );
}
