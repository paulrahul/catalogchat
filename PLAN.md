# Bug Fix Plan & Issue Tracker

## Primary Bug Fix: Discovery drills into navigation links instead of item detail pages

### Problem Description

Given `https://alfilm.berlin/en/program/` (a film catalog), the system recommends
`https://alfilm.berlin/en/selection/` as the next drill-down link instead of a film
detail page like `https://alfilm.berlin/en/program/behind-the-palm-trees/`. From
`/en/selection/` the AI then recommends `/en/program/` — a cycle.

### Root Cause Analysis

There are **three compounding deficiencies** that combine to cause this bug:

**Deficiency 1 — `summarize_dom()` grabs raw page links without context** (`catalog/schema.py:70`)

```python
links = [a.get("href") for a in soup.find_all("a", href=True)][:20]
```

This takes the first 20 `<a href>` tags from the *entire* document. On most sites, the
navigation bar, header, and footer appear first in the HTML and their links dominate this
list. Item-level links (e.g., film detail pages) may not appear until after the 20-link
cutoff, and they appear with no context — the LLM cannot tell them apart from nav links.

**Deficiency 2 — Nesting analysis prompt has no URL pattern guidance** (`catalog/schema.py:399–465`)

The prompt lists raw URLs without any instruction to prefer links that are "children"
of the current URL (i.e., that extend the root path). On `alfilm.berlin/en/program/`,
the correct drill-down URLs are `/en/program/<slug>/`. The LLM has no guidance to prefer
these over same-level sibling paths like `/en/selection/`.

**Deficiency 3 — Links are not scoped to item containers after schema inference**
(`catalog/discovery.py:156–158`)

```python
link_samples = state._current_dom_summary.get("link_samples", [])
resolved_links = get_resolved_links(state.current_url, link_samples)
state._unvisited_links = [link for link in resolved_links if link not in state.visited_urls]
```

By the time we reach this code, `infer_schema()` has already identified an
`item_container_selector` (e.g., `.program-item`). We know which DOM elements are the
catalog items. But we completely ignore this selector when collecting links — we use
the pre-computed `link_samples` that came from the full page scan.

The fix for item-level links is to re-parse the page HTML using the inferred
`item_container_selector` and extract links *only* from within those containers.

---

### Fix Plan

**Step 1 — Enrich link sampling with DOM context** (`catalog/schema.py:70`)

Replace the bare href list with a richer structure that includes text content, parent
element type (so the LLM knows if a link is inside `<nav>`, `<footer>`, `<article>`,
etc.), and whether the link is in a structural navigation element.

```python
# Before
links = [a.get("href") for a in soup.find_all("a", href=True)][:20]

# After
link_samples = []
for a in soup.find_all("a", href=True)[:40]:
    href = a.get("href", "")
    text = a.get_text(strip=True)[:60]
    parent = a.parent
    parent_tag = parent.name if parent else ""
    parent_cls = " ".join(parent.get("class", []))[:50] if parent else ""
    in_nav = bool(a.find_parent(["nav", "header", "footer"]))
    link_samples.append({
        "href": href,
        "text": text,
        "parent_tag": parent_tag,
        "parent_class": parent_cls,
        "in_nav": in_nav,
    })
```

The `dom_summary["link_samples"]` changes from a `list[str]` to a `list[dict]`. All
downstream callers (`get_resolved_links`, `advance_discovery`, the nesting prompt
builder) must be updated accordingly.

**Step 2 — Extract item-scoped links after schema inference** (`catalog/discovery.py`)

After `infer_schema()` identifies `item_container_selector`, extract links from within
those containers specifically and use that as the primary link pool for nesting analysis.
Keep the global link scan as a fallback.

```python
# After infer_schema(), extract item-scoped links:
item_container_sel = (
    state._current_schema.get("item_schema", {}).get("item_container_selector")
    if state._current_schema else None
)
if item_container_sel and state._current_html:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(state._current_html, "html.parser")
    item_links = []
    for container in soup.select(item_container_sel):
        for a in container.find_all("a", href=True):
            href = a.get("href", "")
            if href:
                item_links.append(href)
    if item_links:
        # Use item-scoped links instead of full-page links
        state._unvisited_links = [
            resolve_url(state.current_url, h) for h in item_links
            if is_valid_drill_link(h, state.current_url)
        ]
        state._unvisited_links = list(dict.fromkeys(  # deduplicate, preserve order
            l for l in state._unvisited_links if l not in state.visited_urls
        ))
```

**Step 3 — Add URL path-prefix heuristic** (`catalog/util.py`)

Add a function `score_drill_link(root_url, candidate_url)` that scores a link based on
whether it extends the root URL path. Links like `/en/program/film-slug/` score higher
from `/en/program/` than `/en/selection/`. Apply this scoring to sort `_unvisited_links`
before passing them to the LLM.

```python
def score_drill_link(root_url: str, candidate_url: str) -> float:
    """Score how likely a link is to be a drill-down (higher = more likely)."""
    root_parsed = urlparse(root_url)
    cand_parsed = urlparse(candidate_url)
    
    # Cross-domain links score 0
    if root_parsed.netloc != cand_parsed.netloc:
        return 0.0
    
    root_path = root_parsed.path.rstrip("/")
    cand_path = cand_parsed.path.rstrip("/")
    
    # Child URL (extends root path) — best signal
    if cand_path.startswith(root_path + "/"):
        return 1.0
    
    # Same domain, different path — neutral
    return 0.5
```

**Step 4 — Add cross-domain filtering** (`catalog/util.py:is_valid_drill_link`)

Add a `base_domain` check so links to external domains are excluded from drill-down
candidates entirely.

**Step 5 — Update nesting analysis prompt to return ranked candidates**
(`catalog/schema.py:_build_nesting_analysis_prompt`)

This step serves double duty: it fixes the primary bug and provides the data the
link-picker UI needs (see FEAT-01).

Extend the JSON output schema the LLM must return:

```json
{
  "is_final_level": false,
  "reasoning": "...",
  "recommended_link_index": 3,
  "recommended_link_reason": "...",
  "drill_down_link_selector": "...",
  "ranked_candidates": [
    {"link_index": 3,  "label": "Behind the Palm Trees", "reason": "Film detail page matching /program/<slug>/ pattern", "confidence": 0.95},
    {"link_index": 7,  "label": "On the Road",            "reason": "Film detail page",                                   "confidence": 0.88},
    {"link_index": 12, "label": "The Garden",             "reason": "Film detail page",                                   "confidence": 0.82}
  ]
}
```

Add prompt guidance:
- Prefer links whose path extends the current page's path (child URLs)
- Skip links where `in_nav: true` (flagged in enriched link context from Step 1)
- Use `text` (anchor text) as the human-readable `label`; fall back to the last path
  segment if anchor text is empty
- Return up to 8 ranked candidates; more is unhelpful

**Step 6 — Map ranked candidates to resolved URLs in `_handle_auto_mode`**
(`catalog/discovery.py`)

After `analyze_nesting()` returns, translate each `ranked_candidates[i].link_index` to
its resolved URL from `state._unvisited_links`, building a list suitable for the UI:

```python
ranked_candidates_resolved = []
for candidate in nesting_result.get("ranked_candidates", []):
    idx = candidate.get("link_index")
    if idx is not None and 0 <= idx < len(state._unvisited_links):
        ranked_candidates_resolved.append({
            "url":        state._unvisited_links[idx],
            "label":      candidate.get("label", ""),
            "reason":     candidate.get("reason", ""),
            "confidence": candidate.get("confidence", 0.0),
        })
```

Include `ranked_candidates_resolved` in the `CONFIRM_DRILLING` and
`CONFIRM_FINAL_LEVEL` decision contexts (under key `"ranked_candidates"`). Do the same
in `_handle_manual_mode` for `SELECT_LINK` decisions — in manual mode the full ranked
list gives the user informed choices even without the AI making a recommendation.

**Step 7 — Switch user response payload from `link_index` to `selected_url`**
(`catalog/discovery.py:_handle_user_input`, `api/server.py`)

Instead of passing a positional index back from the UI (which is fragile — see BUG-14),
the UI sends the chosen URL as `selected_url`. In `_handle_user_input`, resolve it back
to a position in `state._unvisited_links` with a safe fallback:

```python
# In _handle_user_input, for CONFIRM_DRILLING "continue":
selected_url = user_input.get("selected_url") or decision.context.get("recommended_url")
if selected_url and selected_url in state._unvisited_links:
    next_url = selected_url
elif "link_index" in user_input:   # backward-compat for CLI
    idx = user_input["link_index"]
    next_url = state._unvisited_links[idx] if 0 <= idx < len(state._unvisited_links) else None
else:
    next_url = state._unvisited_links[0] if state._unvisited_links else None
```

This also fixes BUG-14 as a side effect.

**Step 8 — Update `get_resolved_links` to handle both old and new link format**

Since `link_samples` will now be `list[dict]`, update the function signature and
callers. Add a compatibility shim so the CLI (which reads `dom_summary["link_samples"]`
directly) still works.

---

## FEAT-01: Link Picker — User-selectable drill-down link with ranked options

### Feature Description

During discovery, when the system asks "should we drill deeper?", the user currently
sees only the AI's single recommended link. If that link is wrong (as in the alfilm.berlin
bug), there is no way to pick a different one without cancelling discovery entirely.

The feature adds a dropdown in the discovery step that lists all plausible drill-down
candidates ranked by likelihood, with human-readable labels. The user can accept the
AI's top choice (default) or select any other candidate before confirming.

### UI Behaviour (all three decision types)

**`CONFIRM_DRILLING`** (AI recommends drilling, asks user to confirm):

```
💡 These look like individual film pages that go deeper than the index.

Drill into:   [Behind the Palm Trees  ▼]   ← selectbox, pre-selected = AI top pick
              [On the Road                ]
              [The Garden                 ]
              [Documentary Shorts         ]
              [Enter a different URL...   ]   ← optional escape hatch

[ Yes, go deeper → ]   [ Extract from this level ]
```

**`CONFIRM_FINAL_LEVEL`** (AI says final, user can override):

The "Go deeper →" button stays. When the user clicks it, the dropdown replaces the
confirmation prompt inline (rather than requiring a second round-trip). Implementation:
use a `st.session_state` flag `show_override_picker` toggled by the button click; on the
next rerun render the selectbox and a "Confirm drill" button in its place.

```
💡 This looks like a detail page — the AI thinks we're done.

[ Looks good, continue ]   [ Go deeper → ]
                                ↓ (after clicking "Go deeper")
Drill into:   [Behind the Palm Trees  ▼]
[ Confirm drill ]   [ Cancel ]
```

**`SELECT_LINK`** (manual mode — user always picks):

```
Which link should we drill into?
[Behind the Palm Trees  ▼]

[ Go deeper with selected → ]   [ Extract from this level ]
```

### Changes Required

**`catalog/schema.py`** — already covered by Primary Bug Fix Steps 5 and 6.

**`catalog/discovery.py`** — already covered by Primary Bug Fix Steps 6 and 7.
The decision context for all three decision types will carry `"ranked_candidates"`.

**`ui/app.py: _render_discovery_decision()`** — main UI change.

Replace the current simple button grid with a layout that:
1. Renders a `st.selectbox` when `decision.context.get("ranked_candidates")` is present
2. Pre-selects index 0 (AI's top pick), using `st.session_state` to persist the selection
   across reruns within the same decision
3. Derives the selected URL from the chosen candidate and passes it as `selected_url`
   instead of `link_index` in `user_input`
4. For `CONFIRM_FINAL_LEVEL`, wraps the "Go deeper" flow in the two-click pattern
   described above using a `show_override_picker` session state flag

```python
def _render_link_picker(decision, key_prefix: str) -> str | None:
    """Render ranked-candidate selectbox. Returns selected URL or None."""
    candidates = decision.context.get("ranked_candidates", [])
    if not candidates:
        return None

    labels = []
    for c in candidates:
        label = c.get("label") or ""
        url = c.get("url", "")
        # Show label + truncated URL slug for disambiguation
        slug = url.rstrip("/").rsplit("/", 1)[-1][:40] if url else ""
        display = f"{label}  ({slug})" if label and slug and label.lower() != slug.lower() else (label or slug)
        labels.append(display)

    idx = st.selectbox(
        "Drill into:",
        options=range(len(candidates)),
        format_func=lambda i: labels[i],
        key=f"{key_prefix}_link_picker",
    )
    selected = candidates[idx]
    confidence = selected.get("confidence", 0)
    reason = selected.get("reason", "")
    if reason:
        st.caption(f"Confidence {int(confidence * 100)}% — {reason}")
    return selected.get("url")
```

**`ui/api_client.py: advance_discovery()`** — no signature change needed; `user_input`
is already a free-form dict. The caller now puts `selected_url` inside it instead of
`link_index`.

**`api/server.py: _handle_drilling_response()`, `_handle_link_selection_response()`,
`_handle_final_level_response()`** — update to extract `selected_url` from payload
(already flows through `payload` dict) before falling back to `link_index`.

### What This Does Not Cover

- Custom URL text input ("Enter a different URL...") is listed as a nice-to-have above
  but is out of scope for the initial implementation. It can be added later as a
  `st.text_input` that overrides the selectbox selection.
- The ranked list is limited to candidates the LLM identifies. If the correct link is
  not in the top 8, the user currently has no recourse other than the escape hatch.

---

## Other Bugs

### CRITICAL

**BUG-01: Field correction always applies `None` selector** (`ui/app.py:742–748`)

The UI calls `correction.get("selector")` but the API returns `corrected_selector`.
Every AI-suggested field fix silently applies `None` as the selector, breaking the field.

```python
# BROKEN (current)
fixes = [{
    "field": problem_field,
    "selector": correction.get("selector"),              # None — key doesn't exist
    "attribute": correction.get("attribute", "text"),    # None — key doesn't exist
    "container_selector": correction.get("container_selector"),  # None
}]

# CORRECT
fixes = [{
    "field": problem_field,
    "selector": correction.get("corrected_selector"),
    "attribute": correction.get("corrected_attribute", "text"),
    "container_selector": correction.get("corrected_container_selector"),
}]
```

---

### HIGH

**BUG-02: Manual discovery mode is silently broken** (`ui/api_client.py:147, catalog/discovery.py:61`)

`api_client.py` sends `"interactive"` to the API. The API's `DiscoveryRequest` accepts
`Literal["auto", "interactive"]` and passes it directly to `advance_discovery()` which
expects `Literal["auto", "manual"]`. The `"interactive"` string never matches `"manual"`,
so `_handle_manual_mode()` never fires. Manual mode behaves identically to auto mode.

Fix: either rename `"manual"` to `"interactive"` throughout, or map `"interactive"` →
`"manual"` at the API layer before passing to `advance_discovery()`.

**BUG-03: No error recovery when LLM call fails during discovery** (`api/server.py:343–430`)

`infer_schema()` and `analyze_nesting()` can raise `ValueError` (invalid JSON from LLM)
or `openai.APIError`. These propagate uncaught from `advance_discovery()` through
`discovery_endpoint()` as an unhandled 500. The discovery state in `_discovery_states`
is left in an inconsistent partial state. The client sees a generic error and must
restart from scratch.

Fix: wrap the LLM calls in `advance_discovery()` with try/except; return a special
`Decision` that tells the user "AI analysis failed — retry?" without losing state.

**BUG-04: No pagination support** (feature gap, `catalog/extraction.py`)

`_scrape_level()` only fetches the `sample_url` for each level. If the catalog spans
multiple pages (`?page=2`, `/page/2/`), those items are silently skipped. Many
real catalogs paginate.

Fix requires: detecting pagination links (next/prev), iterating over pages at each
level. Scope is significant — suggest as a separate work item.

---

### MEDIUM

**BUG-05: `_discovery_states` is never cleaned up for abandoned discoveries** (`api/server.py:52`)

If a user starts discovery and closes the browser, the `DiscoveryState` stays in
`_discovery_states` forever. On a long-running server this leaks memory.

Fix: Add a timestamp to each entry; run a background cleanup on each request that
removes states older than, e.g., 30 minutes.

**BUG-06: `fix_fields_endpoint` mutates request data** (`api/server.py:538`)

```python
field_name = fix.pop("field", None)   # mutates the dict from the request body
```

Pydantic deserializes request body into mutable plain dicts; this `pop` is harmless
here but is confusing. Use `.get()` and build a separate fix dict.

**BUG-07: OpenAI key not checked at server startup** (`catalog/util.py:20–25`)

If `OPENAI_API_KEY` is missing, the server starts fine but the first LLM call fails
deep in discovery with a confusing `openai.AuthenticationError`. Should validate at
startup (or at API server startup) and fail fast with a clear message.

**BUG-08: Force-rediscover doesn't delete the old server-side plan** (`ui/app.py:258–263`)

When the user clicks "Discover fresh route", the old plan file in `results/` is not
deleted. During the new discovery, `GET /plan` still returns the old plan. Not
catastrophic (the new discovery overwrites on completion) but creates a confusing
window where the API reports a completed plan while discovery is running.

**BUG-09: Cross-domain links not filtered from drill-down candidates** (`catalog/util.py:209–231`)

`is_valid_drill_link()` does not check if the candidate link's domain matches the root
URL's domain. External links (social media, IMDB, payment processors) can appear in the
nesting analysis link list and confuse the LLM.

**BUG-10: `scrape_all()` caps at 10,000 rows without communicating the limit** (`catalog/extraction.py:474`)

```python
result = scrape_sample(..., max_rows=max_rows or 10000)
```

When called with `max_rows=None` (unlimited), it silently caps at 10,000. A catalog
with 12,000 items would silently return only 10,000.

**BUG-11: `get_result_path()` and discovery state key are different systems** (`catalog/state.py:88, api/server.py:204`)

Plans are persisted using a regex-sanitized URL path (`results/<safe_url>.json`), while
discovery state is keyed by `url_to_hash(normalize_url(url))`. The two systems are
internally consistent but completely different. If someone calls `GET /plan` with a URL
that normalizes differently (e.g., with/without trailing slash), the plan lookup may
fail while a discovery state for the same URL exists. Recommend unifying: use URL hash
for file storage too.

---

### LOW

**BUG-12: Extraction settings checkboxes are rendered but never used** (`ui/app.py:797–800`)

"Include URLs" and "Include timestamps" checkboxes appear in the extraction step but
their state (`st.session_state.include_urls`, `st.session_state.include_timestamps`) is
never read by `api.scrape_data()` or the scraping logic. They're dead UI.

**BUG-13: Model selection in UI is not sent to the API** (`ui/app.py:154–162, api/server.py`)

The user can select GPT-4o vs GPT-4o-mini in the UI, but the selection is stored in
`st.session_state.model` and never passed to the discovery or extraction API calls.
All API calls use whatever `_current_model` is set on the server side (defaults to
`gpt-4o-mini`).

**BUG-14: Discovery `recommended_link_index` passed from UI may be stale** (`ui/app.py:452–455`)

When user clicks "Yes, go deeper", the UI includes `link_index` from the decision
context. But this index refers to a position in `state._unvisited_links` at the time
the decision was created. If the server restarted between the decision and the response
(state lost), the index would refer to the wrong link or cause an out-of-bounds access.

**BUG-15: `_pending_field_edit` in Review step can silently vanish** (`ui/app.py:503–514`)

The inline field edit flow sets `st.session_state._pending_field_edit` and reruns.
If the rerun fails for any reason (e.g., API error), the pending edit is consumed
(`set to None` on line 505) before the error is checked, losing the edit silently.

---

## Summary Table

| ID | Description | Criticality | Component |
|---|---|---|---|
| PRIMARY | Discovery drills navigation links, not item links | Critical | `catalog/discovery.py`, `catalog/schema.py`, `catalog/util.py` |
| FEAT-01 | Link picker: dropdown of ranked drill-down candidates | High | `catalog/schema.py`, `catalog/discovery.py`, `ui/app.py` |
| BUG-01 | Field correction applies `None` selector (AI fix is silently broken) | Critical | `ui/app.py` |
| BUG-02 | Manual mode is broken (acts like auto mode) | High | `ui/api_client.py`, `catalog/discovery.py` |
| BUG-03 | LLM failure during discovery crashes state machine | High | `api/server.py`, `catalog/discovery.py` |
| BUG-04 | No pagination — only first page of catalog is scraped | High | `catalog/extraction.py` |
| BUG-05 | Abandoned discoveries leak memory on the API server | Medium | `api/server.py` |
| BUG-06 | `fix_fields_endpoint` mutates request data with `pop` | Medium | `api/server.py` |
| BUG-07 | Missing OpenAI API key gives cryptic error mid-discovery | Medium | `catalog/util.py` |
| BUG-08 | Force-rediscover leaves old plan visible via `GET /plan` | Medium | `ui/app.py` |
| BUG-09 | External (cross-domain) links not filtered from drill candidates | Medium | `catalog/util.py` |
| BUG-10 | `scrape_all` caps at 10,000 rows without telling the user | Medium | `catalog/extraction.py` |
| BUG-11 | Plan file path and discovery state key are different systems | Medium | `catalog/state.py`, `api/server.py` |
| BUG-12 | Extraction settings checkboxes are dead UI | Low | `ui/app.py` |
| BUG-13 | Model selection in UI is not sent to the API | Low | `ui/app.py`, `api/server.py` |
| BUG-14 | `link_index` in UI response may be stale after server restart | Low | `ui/app.py` |
| BUG-15 | Inline field edit can be silently lost on API error | Low | `ui/app.py` |
