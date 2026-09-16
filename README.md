# Multilingual Form Field Extractor + Drag-and-Drop Form Editor

**Live:** https://form-extractor-qbgs.onrender.com · API: https://form-extractor-api.onrender.com/docs
(Older mirror on Netlify: https://form-field-extractor.netlify.app)

Implementation of [`form-extractor-implementation-plan.md`](./form-extractor-implementation-plan.md):
a PDF/image goes through preprocessing → OCR → a **form gate** → two **hill-climbing passes**
(field grouping, then Q&A synthesis + junk pruning) → **one** batched LLM call → a FastAPI
backend → a React + dnd-kit editor with live preview and fillable-PDF / HTML / JSON-Schema export.

```
PDF/Image ─► [1] preprocess ─► [2] OCR ─► [3] form gate ─► [4] HC pass 1 ─► [5] HC pass 2 ─► [6] Q&A JSON
                                             │ reject                                            │
                                             ▼                                                   ▼
                                       "not a form"                            [7] single LLM call ─► [8] fields
                                                                                                       │
                                                                     [10] React editor ◄── [9] FastAPI ◄┘
```

## Quick start

```bash
./dev.sh                      # API on :8000 (docs at /docs), editor on :5173 (or next free port)
```
or step by step:
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload            # http://localhost:8000/docs
cd ../frontend && npm install && npm run dev        # http://localhost:5173
```
Then open **⚙ Settings** in the editor, pick a provider (**Gemini** or **Claude**), paste its API key and
click *Test connection*. (`GEMINI_API_KEY` / `ANTHROPIC_API_KEY` env vars work too.) Without a key the
pipeline still runs end-to-end on the template output (`llm_used: false`). The output schema is identical
for both providers — switching them never changes the shape of the fields you get back.

Docker (API + Celery worker + Redis + nginx-served editor):
```bash
docker compose up --build       # editor on http://localhost:8080, API on :8000
```

## Verification

```bash
cd backend
.venv/bin/python -m pytest -q             # 106 tests: gate, both passes, templates, LLM merge, export, API e2e, preprocessing
.venv/bin/python eval/make_fixtures.py    # regenerate the eval set (13 multilingual forms + 15 non-forms)
.venv/bin/python eval/run_eval.py -v      # Phase 10 metrics
```
Current eval numbers (synthetic born-digital fixtures — a tuning set, not a production accuracy claim):

| metric | value |
|---|---|
| form-gate accuracy (0 false accepts / 0 false rejects) | 1.000 |
| Pass 1 grouping recall | 1.000 |
| Pass 2 pruning recall / precision | 1.000 / 1.000 |
| template hit-rate (canonical question without any model) | 0.960 |
| answer accuracy on pre-filled values (templates only, no LLM) | 1.000 |

Scripts covered by the fixtures: Latin (en/es/fr/de/pt), Devanagari, Chinese, Japanese, Arabic (RTL), Cyrillic, Tamil, Telugu.

## Where each phase lives

| Phase | File(s) | Notes |
|---|---|---|
| 0 taxonomy / eval data | `backend/app/schemas.py` (`FieldType`), `backend/eval/make_fixtures.py` | `text, date, checkbox, signature, number, multiple-choice, table-cell` |
| 1 preprocessing | `backend/app/pipeline/preprocess.py` | PyMuPDF @300 DPI, Hough deskew, adaptive threshold, rule-line detection |
| 2 OCR | `backend/app/pipeline/ocr.py` | PDF text layer → **PaddleOCR-VL** (local package or remote `/layout-parsing` server) → macOS Vision → LLM vision; selectable in Settings |
| 3 form gate | `backend/app/pipeline/form_gate.py` | language-independent structural score; ambiguous band → one tiny classifier call on a 120-word summary |
| 4 HC pass 1 | `backend/app/pipeline/grouping.py`, `hillclimb.py` | state = per-row split boundaries; moves = split/merge/shift; random-restart steepest ascent |
| 5 HC pass 2 | `backend/app/pipeline/templates.py`, `pruning.py` | 70+ multilingual label templates (+ fuzzy fallback for OCR misspellings); state = kept subset; moves = drop/add/merge; junk features for headers, footers, page numbers, instructions, noise, duplicates |
| 6 single LLM call | `backend/app/pipeline/llm.py`, `backend/app/providers/` | prompt = one line per pruned field; provider-agnostic (`ClaudeProvider` / `GeminiProvider`, same JSON schema); exactly one request per document |
| 6b normalisation | `backend/app/pipeline/normalize.py` | dates → ISO, Devanagari/Arabic digits → ASCII, phones, emails, checkbox → true/false, choice → canonical option; `raw_value` kept |
| 7 API | `backend/app/main.py`, `storage.py` | `POST /documents`, `GET /documents/{id}/fields`, `PATCH .../fields/{field_id}` (corrections stored as tuning data), `POST /forms`, `GET /forms/{id}/preview`, `GET /forms/{id}/export` |
| 8 editor | `frontend/src/` | palette (left) → snap-to-grid canvas (center) with real inputs → settings (right) |
| 9 preview & export | `frontend/src/components/Preview.jsx`, `backend/app/pipeline/export.py` | fillable AcroForm PDF (PyMuPDF widgets, verified with PyPDF), HTML form, JSON Schema |
| 10 testing & tuning | `backend/tests/`, `backend/eval/` | metrics per stage; cost-function weights were tuned against them |
| 11 deployment | `docker-compose.yml`, `backend/app/worker.py`, Dockerfiles | separate API / Celery worker / Redis / frontend services |

## Deploy a public link (Render)

Both halves run on Render for free: the React editor as a **static site** (`frontend/`, `npm run build`,
`VITE_API_BASE` = the API URL) and the Python API (OpenCV, PyMuPDF) as a **Docker web service**
(`render.yaml`). The browser calls the API directly (CORS is open), which avoids proxy timeouts.
Netlify also works (`netlify.toml`) but its ~30 s proxy timeout means `VITE_API_BASE` must be set there too.

1. Push this folder to a GitHub repo.
2. **Render** → *New → Blueprint* → pick the repo (it reads `render.yaml`). Set `ANTHROPIC_API_KEY`
   when asked; `FORM_ADMIN_TOKEN` is generated for you — copy it from the service's *Environment* tab.
   Wait for the deploy, note the URL (e.g. `https://form-extractor-api.onrender.com`) and check `/health`.
3. **Netlify** → *Add new site → Import from Git* → pick the repo (it reads `netlify.toml`).
   Under *Site configuration → Environment variables* add `BACKEND_URL` = the Render URL. Deploy.
4. Share the Netlify link. To change settings on the public site, open ⚙ Settings and enter the admin token.

Notes for the hosted version:
- Scanned images are read by Claude there (macOS Vision only exists on a Mac), so `ANTHROPIC_API_KEY` is needed for scans; digital PDFs work without it.
- Render's free plan sleeps after inactivity — the first upload can take ~30 s to wake up.
- Everyone using your link uses **your** API key; keep `FORM_ADMIN_TOKEN` set so visitors cannot change or remove it.

## What happens on upload (v1.1)

1. `POST /documents` returns **202 in well under a second**; the UI polls `GET /documents/{id}` and shows the stage.
2. Same file + same options uploaded again → served instantly from the SHA-256 cache (`no_cache=true` to bypass).
3. Any file type is accepted, but only **forms** pass the gate; other documents are rejected with a reason.
4. **AI mode `auto`** (default): the validation call is made only for fields the templates could not settle
   (unknown labels, filled-in values, low grouping score). Clean digital forms finish with **0 tokens**.
5. Scans: **one vision call** returns OCR lines + form verdict + fields; a validation call only if still needed.
6. Every model call is recorded in a ledger (purpose, model, tokens, ms) and shown in the ⛰ Hill climbing dialog
   together with *tokens saved* vs sending the raw text / the page image.

## Speed (what runs where)

| step | where | typical time |
|---|---|---|
| render + deskew + line detection (220 DPI) | CPU | 0.3–0.6 s / page |
| text: PDF text layer | CPU | ~10 ms |
| text: scanned image → **Gemini flash-lite vision** (one call returns lines **and** the form verdict) | API | 4–8 s |
| form gate + hill-climb pass 1 + pass 2 | CPU, no model | 20–150 ms |
| validation: **Gemini flash-lite**, one compact call — only fields that need it | API | 0 s (skipped) – 3 s |
| Render free instance cold start (first request after idle) | – | ~30 s |

Model choice, fallbacks and the form-check provider (Claude / Gemini / Kimi) are all in Settings.
Hosting note: the free Render instance has 0.1 CPU and sleeps when idle — the first request after a pause takes
~30 s and the search is capped (`FORM_MAX_RESTARTS`, `FORM_MAX_ITERATIONS`, `FORM_CPU_YIELD_MS`).

## Hill climbing from the UI

The **⛰ Hill climbing** button in the editor opens a dialog to enable/disable both passes (off = baseline:
split at big gaps, keep candidates under a junk threshold), tune random restarts / max iterations, see each
pass's search statistics (evaluations, iterations, final cost, candidates in → out, time) and inspect or
download the plan's data files for the current document:

| file | phase | contents |
|---|---|---|
| `GET /documents/{id}/pass1.data.json` | 4 · field grouping | candidates (label tokens, value region, separator kind, grouping score) + search stats |
| `GET /documents/{id}/pass2.data.json` | 5 · Q&A synthesis + pruning | the optimized Q&A JSON (`question`, `original_label`, `expected_answer_type`, `bbox`, `grouping_score`, `junk_candidates_removed`) |
| `GET /documents/{id}/schema.json` | 7 · final schema | fields after AI validation + normalisation |

Upload params: `hill_climb=true|false`, `restarts=1..12`, `max_iterations=10..1000`.
Reference samples from a real run live in `backend/samples/` (regenerate with `python eval/make_samples.py`).

## API cheat-sheet

```bash
curl -F file=@form.pdf "localhost:8000/documents"                 # sync; add ?sync=false to queue
curl localhost:8000/documents/<id>/fields
curl -X PATCH localhost:8000/documents/<id>/fields/f_003 -H 'content-type: application/json' -d '{"label":"DOB","type":"date"}'
curl -X POST localhost:8000/forms -H 'content-type: application/json' -d @layout.json
curl localhost:8000/forms/<form_id>/export?format=pdf -o form.pdf
curl -X POST localhost:8000/documents/tokens -d @tokens.json      # run gate + passes on pre-OCR'd tokens
```
A non-form returns `status: "rejected"` with `gate.confidence` and no grouping work is performed.

## Scanned images (OCR)

Choose the reader in Settings (or leave *Automatic*):
1. **PDF text layer** — exact word boxes, free (born-digital PDFs).
2. **PaddleOCR-VL** — 0.9B vision-language OCR, 109 languages. Either install it next to the backend
   (`pip install "paddleocr[doc-parser]" paddlepaddle`, ~2 GB of models, ≥4 GB RAM) or run it as a service
   anywhere (`paddlex --install serving && paddlex --serve --pipeline PaddleOCR-VL`) and paste the URL
   in Settings / `PADDLE_OCR_URL`. The backend calls `POST /layout-parsing` and converts the returned
   layout blocks into word boxes.
3. **macOS Vision** — built in when the backend runs on a Mac (30 languages).
4. **LLM vision** — the selected provider reads the page image (any script), one call per page.

## Providers & Settings API

`GET /settings` (keys masked), `PUT /settings` (`provider`, `gemini_api_key`, `anthropic_api_key`,
`gemini_model`, `claude_model`, `llm_enabled`, `vision_ocr_enabled`, `ocr_backend`, `paddle_server_url`),
`POST /settings/test` (validates the active key with a free token-count request).
Adding a provider = one class in `backend/app/providers/` implementing `complete_json()`.

## Environment variables

| var | default | purpose |
|---|---|---|
| `FORM_LLM_PROVIDER` | `gemini` | default provider (`gemini` / `claude`) |
| `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` | – | fallback keys when none is saved on the Settings page |
| `PADDLE_OCR_URL` | – | PaddleOCR-VL service URL (fallback for the Settings value) |
| `FORM_LLM_DISABLED` | – | `1` forces template-only output |
| `FORM_LLM_MODEL` | – | overrides the model chosen in Settings |
| `FORM_QUEUE` | `inprocess` | `celery` to dispatch `?sync=false` uploads to the worker |
| `FORM_DB_PATH`, `FORM_UPLOAD_DIR` | `backend/data/…` | storage locations |
| `FORM_MAX_UPLOAD_MB` | 25 | upload limit |
| `FORM_ADMIN_TOKEN` | – | when set, changing Settings requires this token (use on public deployments) |
