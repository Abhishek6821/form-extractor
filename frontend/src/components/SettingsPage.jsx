import { useEffect, useState } from "react";
import { getSettings, listModels, saveSettings, testSettings } from "../api";
import { Toggle } from "./ui";

const PROVIDER_META = {
  claude: { blurb: "Anthropic · best accuracy on messy multilingual forms", keyPlaceholder: "sk-ant-…", keyField: "anthropic_api_key", modelField: "claude_model", console: "console.anthropic.com" },
  gemini: { blurb: "Google · generous free tier, fast", keyPlaceholder: "AIza…", keyField: "gemini_api_key", modelField: "gemini_model", console: "aistudio.google.com/apikey" },
  kimi: { blurb: "Moonshot AI · Kimi K3, strong document vision", keyPlaceholder: "sk-…", keyField: "kimi_api_key", modelField: "kimi_model", console: "platform.kimi.ai" },
};

const OCR_OPTIONS = [
  { id: "auto", label: "Automatic", help: "PDF text layer → PaddleOCR-VL (if configured) → macOS reader → LLM vision" },
  { id: "pdftext", label: "PDF text layer only", help: "Fastest; scanned images will fail" },
  { id: "paddle", label: "PaddleOCR-VL", help: "0.9B vision-language OCR, 109 languages — local package or remote server" },
  { id: "apple", label: "macOS Vision", help: "Built into macOS (30 languages); only on a Mac backend" },
  { id: "llm", label: "LLM vision", help: "The selected provider reads the page image (any script)" },
];

export default function SettingsPage({ onChanged, notify }) {
  const [s, setS] = useState(null);
  const [keys, setKeys] = useState({ claude: "", gemini: "" });
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [paddleUrl, setPaddleUrl] = useState("");
  const [models, setModels] = useState({ models: [], live: false });
  const [customModel, setCustomModel] = useState("");
  const [admin, setAdmin] = useState(() => {
    try { return sessionStorage.getItem("adminToken") || ""; } catch { return ""; }
  });

  useEffect(() => {
    getSettings().then((v) => { setS(v); setPaddleUrl(v.paddle_server_url || ""); }).catch((e) => notify({ ok: false, text: e.message }));
  }, []);

  // Live model catalogue for the active provider (re-fetched when provider / key changes).
  const keyHint = s?.providers?.[s?.provider]?.api_key_hint;
  useEffect(() => {
    if (!s) return;
    listModels().then(setModels).catch(() => setModels({ models: s.providers[s.provider].models, live: false }));
  }, [s?.provider, keyHint]);

  if (!s) return <div className="p-8 text-sm text-slate-500">Loading settings…</div>;

  async function persist(patch, okText) {
    setBusy(true);
    try {
      const next = await saveSettings(patch, admin);
      setS(next);
      onChanged?.(next);
      if (okText) notify({ ok: true, text: okText });
      return next;
    } catch (e) {
      notify({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  async function onTest() {
    setBusy(true);
    try {
      const r = await testSettings(admin);
      notify(r.ok ? { ok: true, text: `Connected — ${r.model} is reachable.` } : { ok: false, text: r.error });
    } catch (e) {
      notify({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  }

  const active = s.provider;
  const pv = s.providers[active];
  const meta = PROVIDER_META[active];

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 flex flex-col gap-6 fade-up">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-slate-500">
          Pick an AI provider for the single validation call per document (and for reading scanned pages), and choose how text is read from images.
          Field grouping, junk pruning and question templates always run locally — no model calls.
        </p>
      </header>

      {s.admin_required && (
        <section className="panel border-amber-200 bg-amber-50/60 p-4">
          <div className="text-sm font-semibold text-amber-900">Admin token</div>
          <p className="mt-1 text-xs text-amber-800">Shared deployment: only the owner can change settings. Paste the server's <code>FORM_ADMIN_TOKEN</code>.</p>
          <input className="input mt-2 font-mono" type="password" placeholder="admin token" value={admin}
            onChange={(e) => { setAdmin(e.target.value); try { sessionStorage.setItem("adminToken", e.target.value); } catch {} }} />
        </section>
      )}

      {/* Provider choice */}
      <section className="flex flex-col gap-3">
        <div className="panel-title">AI provider</div>
        <div className="grid gap-3 sm:grid-cols-3">
          {Object.entries(s.providers).map(([id, p]) => (
            <button key={id} type="button" className="provider-card" data-active={id === active} disabled={busy}
              onClick={() => id !== active && persist({ provider: id }, `Switched to ${p.label}`)}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-semibold">{p.label}</div>
                  <div className="mt-0.5 text-xs text-slate-500">{PROVIDER_META[id].blurb}</div>
                </div>
                {p.has_api_key ? <span className="badge bg-emerald-100 text-emerald-800">key {p.api_key_hint}</span> : <span className="badge bg-slate-100 text-slate-500">no key</span>}
              </div>
              <div className="mt-3 text-xs text-slate-500">model · <span className="font-medium text-slate-700">{p.model}</span></div>
              {id === active && <span className="absolute right-3 bottom-3 badge bg-brand-600 text-white">active</span>}
            </button>
          ))}
        </div>
      </section>

      {/* Who decides "is this a form?" */}
      <section className="panel p-5 flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">Form check provider</h2>
            <p className="text-xs text-slate-500">Which model confirms "is this a fillable form?" for scans and ambiguous documents. Extraction still uses the active provider above.</p>
          </div>
          <select className="input w-56" value={s.gate_provider} disabled={busy} onChange={(e) => persist({ gate_provider: e.target.value }, `Form check: ${e.target.value}`)}>
            <option value="auto">Same as active provider</option>
            {Object.entries(s.providers).map(([id, p]) => <option key={id} value={id}>{p.label}{p.has_api_key ? "" : " (no key)"}</option>)}
          </select>
        </div>
        <div className="text-xs text-slate-500">Effective now: <span className="font-medium text-slate-700">{s.providers[s.gate_provider_effective]?.label}</span>{s.gate_provider !== "auto" && s.gate_provider !== s.gate_provider_effective && <span className="text-amber-700"> — {s.gate_provider} has no key, falling back</span>}</div>
      </section>

      {/* Active provider config */}
      <section className="panel p-5 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">{pv.label} · API key</h2>
          {pv.has_api_key && <span className="text-xs text-slate-500">{pv.key_source === "env" ? "from server environment" : "saved on server"}</span>}
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input className="input font-mono" type={show ? "text" : "password"} placeholder={meta.keyPlaceholder} autoComplete="off"
            value={keys[active]} onChange={(e) => setKeys({ ...keys, [active]: e.target.value })} />
          <div className="flex gap-2">
            <button className="btn" type="button" onClick={() => setShow(!show)}>{show ? "Hide" : "Show"}</button>
            <button className="btn btn-primary" disabled={busy || !keys[active].trim()}
              onClick={async () => { const n = await persist({ [meta.keyField]: keys[active] }, "API key saved. Test the connection to verify it."); if (n) setKeys({ ...keys, [active]: "" }); }}>
              Save key
            </button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn" disabled={busy || !pv.has_api_key} onClick={onTest}>Test connection</button>
          {pv.has_api_key && pv.key_source === "settings" && (
            <button className="btn btn-danger" disabled={busy} onClick={() => persist({ [meta.keyField]: "" }, "Key removed")}>Remove key</button>
          )}
        </div>
        <div className="flex flex-col gap-2 rounded-xl bg-slate-50 p-3 sm:flex-row sm:items-center">
          <label className="flex flex-1 items-center gap-2 text-sm">
            <span className="text-slate-500">Model</span>
            <select className="input" value={pv.model} disabled={busy} onChange={(e) => persist({ [meta.modelField]: e.target.value }, `Model set to ${e.target.value}`)}>
              {!(models.models || []).includes(pv.model) && <option value={pv.model}>{pv.model}</option>}
              {(models.models?.length ? models.models : pv.models).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <span className={`badge ${models.live ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-500"}`} title={models.live ? "Listed live from your key" : "Suggestions — add a key to list your models"}>{models.live ? "live" : "suggested"}</span>
          </label>
          <div className="flex gap-2">
            <input className="input w-48 font-mono" placeholder="custom model id" value={customModel} onChange={(e) => setCustomModel(e.target.value)} />
            <button className="btn" disabled={busy || !customModel.trim()} onClick={async () => { const n = await persist({ [meta.modelField]: customModel.trim() }, `Model set to ${customModel.trim()}`); if (n) setCustomModel(""); }}>Use</button>
          </div>
        </div>
        <p className="text-xs text-slate-500">If the chosen model is overloaded (503/429) the backend automatically retries on a fallback model and reports which one answered.</p>
        <p className="text-xs text-slate-500">Keys are stored on the backend only and never returned to the browser in full. Get one at {meta.console}.</p>
      </section>

      {/* Feature toggles */}
      <section className="panel p-5 flex flex-col divide-y divide-slate-100">
        <Row title="Enable AI validation" help="One batched call per document: normalises labels, confirms values, flags fields for review. Off = template output only.">
          <Toggle on={s.llm_enabled} disabled={busy} label="Enable AI" onChange={(v) => persist({ llm_enabled: v })} />
        </Row>
        <Row title="Let the AI read scanned pages" help="Used when a page has no text layer and no other reader can handle it (any language / script).">
          <Toggle on={s.vision_ocr_enabled} disabled={busy || !s.llm_enabled} label="AI vision OCR" onChange={(v) => persist({ vision_ocr_enabled: v })} />
        </Row>
      </section>

      {/* OCR */}
      <section className="panel p-5 flex flex-col gap-4">
        <div>
          <h2 className="font-semibold">Text reader for scans (OCR)</h2>
          <p className="mt-1 text-xs text-slate-500">
            Available now: {s.ocr_backends_available.map((b) => <span key={b} className="chip ml-1">{b}</span>)}
          </p>
        </div>
        <div className="grid gap-2">
          {OCR_OPTIONS.map((o) => {
            const unavailable = o.id !== "auto" && !s.ocr_backends_available.includes(o.id);
            return (
              <label key={o.id} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm transition ${s.ocr_backend === o.id ? "border-brand-600 bg-brand-50/40" : "border-slate-200 hover:border-slate-300"}`}>
                <input type="radio" name="ocr" className="mt-1" checked={s.ocr_backend === o.id} disabled={busy}
                  onChange={() => persist({ ocr_backend: o.id }, `OCR: ${o.label}`)} />
                <div className="flex-1">
                  <div className="font-medium flex items-center gap-2">
                    {o.label}
                    {unavailable && <span className="badge bg-slate-100 text-slate-500">not available</span>}
                  </div>
                  <div className="text-xs text-slate-500">{o.help}</div>
                </div>
              </label>
            );
          })}
        </div>
        <div className="rounded-xl bg-slate-50 p-4">
          <div className="text-sm font-medium">PaddleOCR-VL</div>
          <p className="mt-1 text-xs text-slate-500">
            {s.paddle_local_available ? "Local package detected on the backend." : "Local package not installed on the backend (pip install \"paddleocr[doc-parser]\" paddlepaddle)."}
            {" "}Or point to a server started with <code>paddlex --serve --pipeline PaddleOCR-VL</code>:
          </p>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <input className="input font-mono" placeholder="http://your-ocr-host:8080" value={paddleUrl} onChange={(e) => setPaddleUrl(e.target.value)} />
            <button className="btn" disabled={busy || paddleUrl === (s.paddle_server_url || "")} onClick={() => persist({ paddle_server_url: paddleUrl }, "PaddleOCR-VL server saved")}>Save URL</button>
          </div>
        </div>
      </section>
    </div>
  );
}

function Row({ title, help, children }) {
  return (
    <div className="flex items-center justify-between gap-6 py-3 first:pt-0 last:pb-0">
      <div>
        <div className="text-sm font-medium">{title}</div>
        <div className="text-xs text-slate-500">{help}</div>
      </div>
      {children}
    </div>
  );
}
