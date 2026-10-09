# CatalogChat Architecture

## What This Project Does

CatalogChat is an AI-powered tool that lets a user point it at any catalog website — a film index, a product listing, a database of records — and automatically extract all the structured data from it into a clean, usable format.

**The problem it solves:** Catalog websites (film databases, product directories, event listings, etc.) contain valuable structured data but present it as human-readable HTML across multiple pages and nesting levels. Manually scraping this data requires writing custom code per site, understanding its DOM structure, and handling multi-level navigation (e.g., index → category → detail page). This is tedious, brittle, and requires technical expertise.

**What the user-facing product does:** A non-technical user enters a URL. The AI analyzes the page structure, infers what fields exist (title, description, price, director, etc.), determines whether the catalog is flat or nested (does clicking an item reveal more detail?), and guides the user through confirming the structure. The user then gets a preview of the extracted data and can download everything as structured records. The whole flow takes minutes instead of hours.

---

## High-Level Architecture

The system is organized into three layers:

```
┌─────────────────────────────────────────────────────┐
│               User Interface Layer                  │
│   Streamlit UI  │  CLI  │  n8n Workflow UI          │
└──────────────────────────┬──────────────────────────┘
                           │ HTTP / direct import
┌──────────────────────────▼──────────────────────────┐
│               API Layer (FastAPI)                   │
│   api/server.py — thin HTTP adapter, state mgmt    │
└──────────────────────────┬──────────────────────────┘
                           │ Python imports
┌──────────────────────────▼──────────────────────────┐
│               Core Library (catalog/)               │
│  discovery · extraction · schema · plan · state     │
└─────────────────────────────────────────────────────┘
```

All business logic lives in the `catalog/` package. The API and CLI are thin adapters — they handle I/O but delegate everything else to the library.

---

## Components

### 1. Core Library (`catalog/`)

The heart of the project. All schema inference, discovery state, and data extraction live here.

| File | Purpose |
|---|---|
| `types.py` | All domain dataclasses: `CatalogPlan`, `DiscoveryState`, `ExtractionPlan`, `Field`, `LevelSchema`, `Decision` |
| `discovery.py` | Discovery state machine: `start_discovery()`, `advance_discovery()` |
| `schema.py` | LLM-powered DOM analysis: `summarize_dom()`, `infer_schema()`, `analyze_nesting()`, `correct_field_selector()` |
| `extraction.py` | Scraping engine: `build_extraction_plan()`, `scrape_sample()`, `scrape_all()`, `apply_field_fix()` |
| `plan.py` | Plan creation and schema edit helpers |
| `state.py` | File-based persistence: save/load plans to `results/` as JSON keyed by URL hash |
| `util.py` | HTTP fetching (`fetch_html`), URL normalization, OpenAI client wrapper (`call_llm`) |

#### Key Concepts

**Discovery state machine** — Discovery is modeled as a resumable state machine. `advance_discovery()` fetches a page, infers its schema, and either completes or returns a `Decision` object requesting human input (e.g., "should we drill deeper into this link?"). The caller responds with `user_input` and calls `advance_discovery()` again. This design makes the core logic usable from CLI, API, and UI without changes.

**Decision objects** — Instead of blocking for input, the library returns `Decision` objects with a stable `id` (e.g., `confirm_drilling`, `select_link`, `fix_field`) and a set of valid `options`. The interface layer (CLI, API, UI) is responsible for presenting these to the user.

**CatalogPlan** — The primary domain object. Represents a catalog's structure: root URL, nesting depth, and a `schema_chain` (one `LevelSchema` per navigation level). Created by discovery, consumed by extraction.

**ExtractionPlan** — Derived from a `CatalogPlan`. Contains concrete CSS selectors and navigation instructions needed to actually scrape data. Built by `build_extraction_plan()`.

**LLM backend** — The library uses OpenAI GPT models (configurable, defaults to `gpt-4o-mini`). Requires `OPENAI_API_KEY` environment variable. The model is called for schema inference, nesting analysis, and field correction suggestions.

---

### 2. FastAPI Server (`api/`)

A thin HTTP adapter over the core library. Exposes the full discovery and extraction workflow as REST endpoints. Manages in-memory `DiscoveryState` objects between requests (keyed by URL hash). Plans and extraction plans are persisted to disk in `results/`.

**Run:** `uvicorn api.server:app --reload --port 8080`  
**Docs:** `http://127.0.0.1:8080/docs` (auto-generated Swagger UI)

#### Key Endpoints

| Method | Path | What it does |
|---|---|---|
| `POST` | `/plan` | Create or load a plan for a URL |
| `GET` | `/plan` | Get existing plan by URL |
| `PUT` | `/plan` | Apply schema edits (rename/delete fields) |
| `POST` | `/plan/discovery` | Start or advance discovery; returns pending `Decision` when human input needed |
| `GET` | `/wait_response` | Poll for the current pending decision |
| `POST` | `/wait_response` | Submit a response to any pending decision (generic handler routing by `decision.id`) |
| `POST` | `/plan/extraction-plan` | Build extraction plan from completed discovery |
| `POST` | `/plan/sample` | Scrape a sample (3 rows by default) |
| `POST` | `/plan/fix-fields` | Apply CSS selector fixes |
| `POST` | `/plan/suggest-correction` | Ask AI to suggest a better field selector |
| `POST` | `/plan/scrape` | Full scrape |
| `GET` | `/health` | Health check |

The `/wait_response` endpoint is designed specifically for n8n integration — it provides a single, stable webhook target that routes responses based on `decision.id`.

---

### 3. Streamlit UI (`ui/`)

A wizard-style web UI for non-technical users. Communicates with the FastAPI server via `api_client.py`. The product name shown in the UI is **CheapTalk**.

**Run:** `python -m ui.run`  
**Requires:** FastAPI server running at `http://localhost:8080`  
**URL:** `http://localhost:8501`

#### Workflow Steps (as shown in the UI)

1. **URL** — User enters a catalog URL
2. **Navigate** — Discovery runs; UI shows AI reasoning and asks for confirmation at each nesting decision
3. **Review** — User sees the inferred schema (fields per level); can rename/delete fields
4. **Verify** — Sample data is scraped and displayed in a table; user can flag and correct wrong fields
5. **Extract** — Full scrape is triggered; results available for download

| File | Purpose |
|---|---|
| `app.py` | Main Streamlit app, step routing, session state |
| `api_client.py` | HTTP client for the FastAPI server |
| `components.py` | Reusable UI widgets (schema display, field cards, discovery trail, etc.) |
| `styles.py` | Custom CSS injected into the Streamlit page |
| `run.py` | Entrypoint that sets working directory and launches Streamlit |
| `.streamlit/config.toml` | Streamlit server configuration |

---

### 4. CLI (`cli/`)

An interactive terminal interface. Drives the same `catalog/` library directly without going through the HTTP layer. Useful for development, debugging, and batch use.

**Run:** `python -m cli.main`

The CLI prompts for a URL, lets you pick an LLM model, runs discovery with progress output, allows schema editing (rename/delete fields), shows sample data, and saves results to `results/`.

---

### 5. n8n Workflow Solution (`n8n/`)

An alternative implementation using n8n (a workflow automation tool) as the orchestration layer. This was the original approach before the FastAPI + Streamlit solution was built.

**Run n8n:** `npx n8n` → opens at `http://localhost:5678`  
**Run UI:** `npx serve n8n/ui` → opens at `http://localhost:3000`

| Path | Contents |
|---|---|
| `n8n/workflows/CatalogChat_CacheCheck.json` | `catalogchat/start`: checks for a saved plan, offers reuse |
| `n8n/workflows/CatalogChat_Discover.json` | `catalogchat/discover`: starts/advances discovery, returns the next decision or the final plan |
| `n8n/workflows/CatalogChat_Schema.json` | `catalogchat/schema`: rename/delete fields |
| `n8n/workflows/CatalogChat_Sample.json` | `catalogchat/sample`: builds the extraction plan (optional) and scrapes sample rows |
| `n8n/workflows/CatalogChat_FieldFix.json` | `catalogchat/fix/suggest` and `catalogchat/fix/apply`: AI selector correction |
| `n8n/workflows/CatalogChat_Scrape.json` | `catalogchat/scrape`: full extraction |
| `n8n/ui/` | Static UI (`index.html`, `app.js`, `styles.css`, no build step) with the same five steps as the Streamlit UI |

The workflows are stateless: each user action is one webhook call, and the FastAPI server keeps discovery state between calls, so no n8n Wait nodes are used. Every webhook returns the same envelope: `{type: "decision_required" | "next" | "result" | "error", id, step, ...}`.

---

### 6. Prototype (`prototype/`)

An earlier, monolithic version of the core logic before it was refactored into the `catalog/` library. Not used by any active interface. Kept for reference.

---

## Data Flow

```
User enters URL
      │
      ▼
POST /plan/discovery
      │
      ├─ fetch_html(url) → HTML
      ├─ summarize_dom(html) → DOM summary
      ├─ infer_schema(dom_summary) → LLM → schema
      ├─ analyze_nesting(schema, links) → LLM → nesting decision
      │
      ▼
Decision returned to UI
(e.g., "AI recommends drilling into /films/detail — confirm?")
      │
User responds: "yes, continue"
      │
      ▼
POST /wait_response  {decision.id: "confirm_drilling", action: "continue"}
      │
      ├─ Repeat for each nesting level until done
      │
      ▼
CatalogPlan saved to results/<url-hash>.json
      │
      ▼
POST /plan/extraction-plan → ExtractionPlan (CSS selectors)
      │
      ▼
POST /plan/sample → sample rows
      │
User reviews, flags wrong fields
      │
      ▼
POST /plan/suggest-correction → LLM → new selector
POST /plan/fix-fields → updated ExtractionPlan
      │
      ▼
POST /plan/scrape → all rows
```

---

## Running the Project

### Prerequisites

```bash
# Python 3.11+
pip install -r ui/requirements.txt
pip install fastapi uvicorn beautifulsoup4 requests openai

# Set your OpenAI API key
export OPENAI_API_KEY=sk-...
```

### Option A: Streamlit UI + FastAPI (recommended)

Open two terminal windows:

```bash
# Terminal 1 — API server
uvicorn api.server:app --reload --port 8080

# Terminal 2 — Streamlit UI
python -m ui.run
```

Then open `http://localhost:8501` in your browser.

### Option B: CLI only

```bash
python -m cli.main
```

### Option C: n8n workflow

```bash
# Terminal 1 — FastAPI server (required by n8n workflows)
uvicorn api.server:app --reload --port 8080

# Terminal 2 — n8n
npx n8n

# Terminal 3 — simple HTML UI
npx serve n8n/ui
```

Import the workflows with `npx n8n import:workflow --separate --input=n8n/workflows`, activate them in the n8n editor, then open `http://localhost:3000`.

---

## Persistence

Results are saved as JSON files in the `results/` directory. The filename is derived from a hash of the normalized URL, so re-running on the same URL will find and optionally reuse the previous result. Each file stores the `CatalogPlan`, `ExtractionPlan`, and optionally sample data.

The FastAPI server also maintains in-memory `DiscoveryState` objects for active (in-progress) discoveries. These are lost on server restart; completed plans survive because they are flushed to disk.

---

## Key Design Decisions

- **Library-first:** All logic lives in `catalog/`. The API, CLI, and UI are adapters. This makes the core independently testable and reusable.
- **Decision-based human-in-the-loop:** Rather than blocking on user input, functions return `Decision` objects. This allows the same core logic to be driven by a CLI prompt, an HTTP polling loop, or a streaming UI without modification.
- **URL-keyed state:** Everything is keyed by a normalized, hashed URL. This makes caching, resumption, and API correlation simple without a database.
- **OpenAI for inference:** Schema inference, nesting analysis, and field correction all use GPT via the OpenAI API. The model is configurable at runtime (`gpt-4o-mini` default).
