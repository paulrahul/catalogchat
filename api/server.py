"""
HTTP API server for the catalog library.

This is a thin adapter layer that exposes the core library via HTTP.
All business logic lives in the catalog package - this layer only handles:
- HTTP request/response
- JSON serialization
- State persistence by URL

Run with: uvicorn api.server:app --reload
"""

from datetime import datetime
from typing import Literal, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from catalog import (
    CatalogPlan,
    DiscoveryState,
    ExtractionPlan,
    DecisionId,
    DecisionStep,
    create_plan,
    load_plan,
    save_plan,
    start_discovery,
    advance_discovery,
    apply_schema_edits,
    build_extraction_plan,
    scrape_sample,
    scrape_all,
    apply_field_fix,
    prepare_field_correction,
)
from catalog.schema import correct_field_selector
from catalog.util import normalize_url, url_to_hash, fetch_html
from catalog.state import save_state, load_state, get_result_path

app = FastAPI(
    title="Catalog API",
    description="API for AI-assisted catalog schema discovery and data extraction",
    version="0.1.0",
)

# -------------------------
# In-memory state for active discoveries
# (In production, you might use Redis or similar)
# -------------------------

_discovery_states: dict[str, DiscoveryState] = {}


# -------------------------
# Request/Response Models
# -------------------------


class UrlRequest(BaseModel):
    url: str


class PlanResponse(BaseModel):
    url: str
    normalized_url: str
    plan: dict | None


class SchemaEditRequest(BaseModel):
    url: str
    edits: list[dict]


class DiscoveryResponse(BaseModel):
    url: str
    state: dict
    decision: dict | None
    done: bool
    plan: dict | None = None


class ExtractionPlanResponse(BaseModel):
    url: str
    extraction_plan: dict


class SampleRequest(BaseModel):
    url: str
    num_rows: int = 3
    target_level: int | None = None


class SampleResponse(BaseModel):
    url: str
    sample: dict
    decision: dict | None = None


class FieldFixRequest(BaseModel):
    url: str
    fixes: list[dict]


class FieldCorrectionRequest(BaseModel):
    url: str
    field_name: str
    expected_value: str
    user_feedback: str


class FieldCorrectionResponse(BaseModel):
    url: str
    field_name: str
    found_elements: list[dict]
    correction: dict | None


class ScrapeRequest(BaseModel):
    url: str
    max_rows: int | None = None
    target_level: int | None = None


class ScrapeResponse(BaseModel):
    url: str
    rows: list[dict]
    count: int


# -------------------------
# Wait Response Models (Generic Decision Handler)
# -------------------------


class DecisionInfo(BaseModel):
    """
    The decision being responded to.

    Attributes:
        id: Stable semantic identifier (e.g., "confirm_drilling", "fix_field")
        step: Optional phase/step identifier (e.g., "discovery", "sample_analysis")
        action: The user's chosen action (e.g., "continue", "final", "fix", "skip")
    """
    id: str
    step: str | None = None
    action: str


class WaitResponseMeta(BaseModel):
    """Optional metadata for tracking and analytics."""
    source: str | None = None  # e.g., "ui", "n8n", "cli"
    timestamp: str | None = None


class WaitResponseRequest(BaseModel):
    """
    Generic request for handling user responses to decisions.

    This single endpoint handles all human-in-the-loop decision responses,
    making it easy to integrate with workflow tools like n8n.

    Attributes:
        url: The catalog URL (primary correlation key)
        decision: The decision being responded to (id, step, action)
        payload: Optional action-specific data (e.g., fixes, selected_url)
        meta: Optional metadata for logging/analytics
    """
    url: str
    decision: DecisionInfo
    payload: dict[str, Any] | None = None
    meta: WaitResponseMeta | None = None


class WaitResponseResult(BaseModel):
    """
    Result of processing a wait response.

    Attributes:
        url: The catalog URL
        success: Whether the response was processed successfully
        next_decision: If another decision is needed, it's returned here
        state: Current state summary
        plan: Completed plan (if discovery finished)
        extraction_plan: Updated extraction plan (if applicable)
        sample: Updated sample data (if applicable)
        message: Human-readable status message
    """
    url: str
    success: bool
    next_decision: dict | None = None
    state: dict | None = None
    plan: dict | None = None
    extraction_plan: dict | None = None
    sample: dict | None = None
    message: str | None = None


# -------------------------
# Helper Functions
# -------------------------


def _get_state_key(url: str) -> str:
    """Get the state key for a URL."""
    normalized = normalize_url(url)
    return url_to_hash(normalized)


def _load_plan_by_url(url: str) -> tuple[str, CatalogPlan | None]:
    """Load a plan by URL. Returns (normalized_url, plan)."""
    normalized = normalize_url(url)
    path = get_result_path(normalized)
    state = load_state(path)
    if state and "plan" in state:
        return normalized, CatalogPlan.from_dict(state["plan"])
    return normalized, None


def _save_plan_by_url(url: str, plan: CatalogPlan, extra_data: dict | None = None):
    """Save a plan by URL."""
    normalized = normalize_url(url)
    path = get_result_path(normalized)

    # Load existing state to preserve other data
    existing = load_state(path) or {}
    existing["plan"] = plan.to_dict()

    if extra_data:
        existing.update(extra_data)
    save_state(existing, path)


def _load_extraction_plan_by_url(url: str) -> ExtractionPlan | None:
    """Load extraction plan by URL."""
    normalized = normalize_url(url)
    path = get_result_path(normalized)
    state = load_state(path)
    if state and "extraction_plan" in state:
        return ExtractionPlan.from_dict(state["extraction_plan"])
    return None


def _save_extraction_plan_by_url(url: str, extraction_plan: ExtractionPlan):
    """Save extraction plan by URL."""
    normalized = normalize_url(url)
    path = get_result_path(normalized)

    existing = load_state(path) or {}
    existing["extraction_plan"] = extraction_plan.to_dict()
    save_state(existing, path)


# -------------------------
# Plan Endpoints
# -------------------------


@app.post("/plan", response_model=PlanResponse)
def create_or_load_plan(request: UrlRequest):
    """
    Create a new plan or load an existing one for the given URL.

    If a plan already exists for this URL, it is returned.
    Otherwise, a new empty plan is created.
    """
    normalized, existing_plan = _load_plan_by_url(request.url)

    if existing_plan:
        return PlanResponse(
            url=request.url,
            normalized_url=normalized,
            plan=existing_plan.to_dict(),
        )

    # Create new plan
    plan = create_plan(normalized)
    _save_plan_by_url(request.url, plan)

    return PlanResponse(
        url=request.url,
        normalized_url=normalized,
        plan=plan.to_dict(),
    )


@app.get("/plan", response_model=PlanResponse)
def get_plan(url: str):
    """
    Get an existing plan by URL.

    Returns 404 if no plan exists for this URL.
    """
    normalized, plan = _load_plan_by_url(url)

    if not plan:
        raise HTTPException(status_code=404, detail=f"No plan found for URL: {url}")

    return PlanResponse(
        url=url,
        normalized_url=normalized,
        plan=plan.to_dict(),
    )


@app.put("/plan", response_model=PlanResponse)
def update_plan(request: SchemaEditRequest):
    """
    Apply schema edits to an existing plan.

    Supported edit actions:
    - {"action": "rename", "field": "old_name", "new_name": "new_name"}
    - {"action": "delete", "field": "field_name"}
    """
    normalized, plan = _load_plan_by_url(request.url)

    if not plan:
        raise HTTPException(status_code=404, detail=f"No plan found for URL: {request.url}")

    # Apply edits using core library
    plan = apply_schema_edits(plan, request.edits)
    _save_plan_by_url(request.url, plan)

    return PlanResponse(
        url=request.url,
        normalized_url=normalized,
        plan=plan.to_dict(),
    )


# -------------------------
# Discovery Endpoint
# -------------------------


class DiscoveryRequest(BaseModel):
    """Request to run discovery for a URL."""
    url: str
    user_input: dict | None = None  # For responding to decisions
    mode: Literal["auto", "interactive"] = "auto"


@app.post("/plan/discovery", response_model=DiscoveryResponse)
def discovery_endpoint(request: DiscoveryRequest):
    """
    Run discovery for a URL.

    This is a unified endpoint that handles both starting and advancing discovery:
    - If no active discovery exists for this URL, starts a new one
    - If active discovery exists, advances it with the provided user_input

    Use GET /plan to check for existing completed plans before calling this.

    User input examples (when responding to decisions):
    - {"choice": "continue"} - continue drilling deeper
    - {"choice": "final"} - mark current level as final
    - {"choice": "drill", "link_index": 0} - select specific link to follow

    When done=true, the completed plan is returned.
    """
    normalized = normalize_url(request.url)
    state_key = _get_state_key(request.url)

    # Check for active discovery state
    state = _discovery_states.get(state_key)

    if not state:
        # No active discovery - start a new one
        plan = create_plan(normalized)
        state = start_discovery(plan, mode=request.mode)
        _discovery_states[state_key] = state

        # Auto-advance to get the first decision
        state, decision = advance_discovery(
            state=state,
            user_input=None,
            mode=request.mode,
        )
        _discovery_states[state_key] = state

        # Check if already done (unlikely but possible for trivial cases)
        completed_plan = None
        if state.done:
            _save_plan_by_url(request.url, state.plan)
            completed_plan = state.plan.to_dict()
            del _discovery_states[state_key]

        return DiscoveryResponse(
            url=request.url,
            state=_serialize_discovery_state(state),
            decision=decision.to_dict() if decision else None,
            done=state.done,
            plan=completed_plan,
        )

    # Active discovery exists
    # If there's a pending decision and no user_input, return the pending decision (idempotent)
    if state.pending_decision and not request.user_input:
        return DiscoveryResponse(
            url=request.url,
            state=_serialize_discovery_state(state),
            decision=state.pending_decision.to_dict(),
            done=state.done,
            plan=None,
        )

    # Advance discovery with user input
    state, decision = advance_discovery(
        state=state,
        user_input=request.user_input,
        mode=request.mode,
    )

    # Update stored state
    _discovery_states[state_key] = state

    # If done, save plan and clean up
    completed_plan = None
    if state.done:
        _save_plan_by_url(request.url, state.plan)
        completed_plan = state.plan.to_dict()
        del _discovery_states[state_key]

    return DiscoveryResponse(
        url=request.url,
        state=_serialize_discovery_state(state),
        decision=decision.to_dict() if decision else None,
        done=state.done,
        plan=completed_plan,
    )


def _serialize_discovery_state(state: DiscoveryState) -> dict:
    """Serialize discovery state for API response (excluding internal fields)."""
    return {
        "current_url": state.current_url,
        "current_level": state.current_level,
        "visited_urls": list(state.visited_urls),
        "done": state.done,
        "has_pending_decision": state.pending_decision is not None,
    }


# -------------------------
# Extraction Plan Endpoints
# -------------------------


@app.post("/plan/extraction-plan", response_model=ExtractionPlanResponse)
def build_extraction_plan_endpoint(request: UrlRequest):
    """
    Build an extraction plan from a completed discovery plan.

    The extraction plan contains all the information needed to scrape
    the catalog, including navigation paths and field selectors.
    """
    normalized, plan = _load_plan_by_url(request.url)

    if not plan:
        raise HTTPException(status_code=404, detail=f"No plan found for URL: {request.url}")

    if not plan.schema_chain:
        raise HTTPException(
            status_code=400,
            detail="Plan has no schema chain. Run discovery first.",
        )

    # Build extraction plan using core library
    extraction_plan = build_extraction_plan(plan)
    _save_extraction_plan_by_url(request.url, extraction_plan)

    return ExtractionPlanResponse(
        url=request.url,
        extraction_plan=extraction_plan.to_dict(),
    )


# -------------------------
# Sample & Correction Endpoints
# -------------------------


@app.post("/plan/sample", response_model=SampleResponse)
def scrape_sample_endpoint(request: SampleRequest):
    """
    Scrape sample data using the extraction plan.

    Returns sample rows and optionally a decision if there are
    data quality issues that need user attention.
    """
    extraction_plan = _load_extraction_plan_by_url(request.url)

    if not extraction_plan:
        raise HTTPException(
            status_code=404,
            detail=f"No extraction plan found for URL: {request.url}. Call POST /plan/extraction-plan first.",
        )

    # Scrape sample using core library
    sample = scrape_sample(
        extraction_plan=extraction_plan,
        target_level=request.target_level,
        max_rows=request.num_rows,
    )

    # Analyze for issues (could return a decision)
    from catalog import analyze_sample
    decision = analyze_sample(sample, extraction_plan)

    return SampleResponse(
        url=request.url,
        sample=sample.to_dict(),
        decision=decision.to_dict() if decision else None,
    )


@app.post("/plan/fix-fields", response_model=ExtractionPlanResponse)
def fix_fields_endpoint(request: FieldFixRequest):
    """
    Apply field selector fixes to the extraction plan.

    Each fix should contain:
    - field: the field name to fix
    - container_selector: new container selector (optional)
    - selector: new CSS selector
    - attribute: attribute to extract (text, href, src, etc.)
    """
    extraction_plan = _load_extraction_plan_by_url(request.url)

    if not extraction_plan:
        raise HTTPException(
            status_code=404,
            detail=f"No extraction plan found for URL: {request.url}",
        )

    # Apply fixes using core library
    for fix in request.fixes:
        field_name = fix.pop("field", None)
        if field_name:
            extraction_plan = apply_field_fix(extraction_plan, field_name, fix)

    _save_extraction_plan_by_url(request.url, extraction_plan)
    return ExtractionPlanResponse(
        url=request.url,
        extraction_plan=extraction_plan.to_dict(),
    )


@app.post("/plan/suggest-correction", response_model=FieldCorrectionResponse)
def suggest_field_correction_endpoint(request: FieldCorrectionRequest):
    """
    Get an AI-suggested correction for a field selector.

    This endpoint:
    1. Fetches the page HTML
    2. Searches for the expected value
    3. Asks AI to suggest a better selector

    The caller can then apply the suggestion using POST /plan/fix-fields.
    """
    extraction_plan = _load_extraction_plan_by_url(request.url)

    if not extraction_plan:
        raise HTTPException(
            status_code=404,
            detail=f"No extraction plan found for URL: {request.url}",
        )

    # Find the field in the plan
    from catalog import find_field_in_plan
    level_plan, field_info = find_field_in_plan(extraction_plan, request.field_name)

    if not level_plan or not field_info:
        raise HTTPException(
            status_code=404,
            detail=f"Field '{request.field_name}' not found in extraction plan",
        )

    # Fetch HTML
    try:
        html = fetch_html(level_plan.sample_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch page: {e}")

    # Prepare correction context using core library
    context = prepare_field_correction(
        extraction_plan=extraction_plan,
        field_name=request.field_name,
        expected_value=request.expected_value,
        html=html,
    )

    if not context:
        raise HTTPException(
            status_code=500,
            detail="Failed to prepare correction context",
        )

    # Get AI correction suggestion
    try:
        correction = correct_field_selector(
            field_name=field_info.name,
            current_container_selector=field_info.container_selector,
            current_selector=field_info.selector,
            current_attribute=field_info.attribute or "text",
            current_value="",  # We don't have the current value in this flow
            user_feedback=request.user_feedback,
            expected_value=request.expected_value,
            dom_summary=context["dom_summary"],
            item_container_selector=context["item_container_selector"],
            found_elements=context["found_elements"],
        )
    except Exception as e:
        correction = None

    return FieldCorrectionResponse(
        url=request.url,
        field_name=request.field_name,
        found_elements=context["found_elements"],
        correction=correction,
    )


# -------------------------
# Full Scrape Endpoint
# -------------------------


@app.post("/plan/scrape", response_model=ScrapeResponse)
def scrape_endpoint(request: ScrapeRequest):
    """
    Perform a full scrape using the extraction plan.

    Returns all scraped rows up to max_rows (if specified).
    """
    extraction_plan = _load_extraction_plan_by_url(request.url)

    if not extraction_plan:
        raise HTTPException(
            status_code=404,
            detail=f"No extraction plan found for URL: {request.url}. Call POST /plan/extraction-plan first.",
        )

    # Scrape all using core library
    rows = scrape_all(
        extraction_plan=extraction_plan,
        target_level=request.target_level,
        max_rows=request.max_rows,
    )

    return ScrapeResponse(
        url=request.url,
        rows=rows,
        count=len(rows),
    )


# -------------------------
# Generic Wait Response Endpoint
# -------------------------


@app.get("/wait_response", response_model=WaitResponseResult)
def get_pending_decision(url: str):
    """
    Get the current pending decision for a URL.

    This is useful for:
    - Resuming after a client disconnect
    - Checking if there's a decision waiting for input
    - UIs that need to re-render the current decision
    - Workflow tools (n8n) polling for decision state

    Returns the pending decision if one exists, along with state context.
    """
    state_key = _get_state_key(url)
    state = _discovery_states.get(state_key)

    if not state:
        # Check if there's a completed plan
        _, plan = _load_plan_by_url(url)
        if plan and plan.schema_chain:
            return WaitResponseResult(
                url=url,
                success=True,
                plan=plan.to_dict(),
                message="Discovery already complete. Plan exists.",
            )
        return WaitResponseResult(
            url=url,
            success=True,
            message="No active discovery. Call POST /plan/discovery to start.",
        )

    if state.done:
        return WaitResponseResult(
            url=url,
            success=True,
            state=_serialize_discovery_state(state),
            plan=state.plan.to_dict() if state.plan else None,
            message="Discovery complete.",
        )

    if state.pending_decision:
        return WaitResponseResult(
            url=url,
            success=True,
            next_decision=state.pending_decision.to_dict(),
            state=_serialize_discovery_state(state),
            message="Waiting for user response.",
        )

    return WaitResponseResult(
        url=url,
        success=True,
        state=_serialize_discovery_state(state),
        message="Discovery in progress. Call POST /plan/discovery to continue.",
    )


@app.post("/wait_response", response_model=WaitResponseResult)
def wait_response_endpoint(request: WaitResponseRequest):
    """
    Generic endpoint for handling user responses to decisions.

    This single endpoint handles all human-in-the-loop decision responses,
    routing to the appropriate handler based on decision.id and decision.action.

    Supported decision IDs:
    - confirm_drilling: Continue/stop drilling during discovery
    - select_link: Select which link to follow during discovery
    - confirm_final_level: Confirm current level is final
    - fix_field: Fix field selectors after sample analysis
    - edit_schema: Apply schema edits
    - scrape_more: Continue scraping more data

    The response includes the next decision (if any) or the completed result.
    """
    decision_id = request.decision.id
    action = request.decision.action
    payload = request.payload or {}

    # Route to appropriate handler based on decision ID
    handlers = {
        DecisionId.CONFIRM_DRILLING: _handle_drilling_response,
        DecisionId.SELECT_LINK: _handle_link_selection_response,
        DecisionId.CONFIRM_FINAL_LEVEL: _handle_final_level_response,
        DecisionId.FIX_FIELD: _handle_fix_field_response,
        DecisionId.EDIT_SCHEMA: _handle_edit_schema_response,
        DecisionId.SCRAPE_MORE: _handle_scrape_more_response,
    }

    handler = handlers.get(decision_id)
    if not handler:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown decision ID: {decision_id}. Valid IDs: {list(handlers.keys())}",
        )

    try:
        return handler(request.url, action, payload, request.meta)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing response: {str(e)}",
        )


def _handle_drilling_response(
    url: str, action: str, payload: dict, meta: WaitResponseMeta | None
) -> WaitResponseResult:
    """Handle response to CONFIRM_DRILLING decision."""
    state_key = _get_state_key(url)
    state = _discovery_states.get(state_key)

    if not state:
        raise HTTPException(
            status_code=400,
            detail="No active discovery for this URL. Start discovery first.",
        )

    user_input = {"choice": action}

    # selected_url takes priority over link_index
    if "selected_url" in payload:
        user_input["selected_url"] = payload["selected_url"]
    elif "link_index" in payload:
        user_input["link_index"] = payload["link_index"]

    # Advance discovery with user input
    state, next_decision = advance_discovery(
        state=state,
        user_input=user_input,
        mode="auto",
    )

    _discovery_states[state_key] = state

    # Check if done
    completed_plan = None
    if state.done:
        _save_plan_by_url(url, state.plan)
        completed_plan = state.plan.to_dict()
        del _discovery_states[state_key]

    return WaitResponseResult(
        url=url,
        success=True,
        next_decision=next_decision.to_dict() if next_decision else None,
        state=_serialize_discovery_state(state),
        plan=completed_plan,
        message="Drilling response processed" if not state.done else "Discovery complete",
    )


def _handle_link_selection_response(
    url: str, action: str, payload: dict, meta: WaitResponseMeta | None
) -> WaitResponseResult:
    """Handle response to SELECT_LINK decision."""
    state_key = _get_state_key(url)
    state = _discovery_states.get(state_key)

    if not state:
        raise HTTPException(
            status_code=400,
            detail="No active discovery for this URL. Start discovery first.",
        )

    user_input = {"choice": action}

    if action == "drill":
        # selected_url takes priority; fall back to link_index
        if "selected_url" in payload:
            user_input["selected_url"] = payload["selected_url"]
        elif "link_index" in payload:
            user_input["link_index"] = payload["link_index"]

    # Advance discovery
    state, next_decision = advance_discovery(
        state=state,
        user_input=user_input,
        mode="auto",
    )

    _discovery_states[state_key] = state

    completed_plan = None
    if state.done:
        _save_plan_by_url(url, state.plan)
        completed_plan = state.plan.to_dict()
        del _discovery_states[state_key]

    return WaitResponseResult(
        url=url,
        success=True,
        next_decision=next_decision.to_dict() if next_decision else None,
        state=_serialize_discovery_state(state),
        plan=completed_plan,
        message="Link selection processed" if not state.done else "Discovery complete",
    )


def _handle_final_level_response(
    url: str, action: str, payload: dict, meta: WaitResponseMeta | None
) -> WaitResponseResult:
    """Handle response to CONFIRM_FINAL_LEVEL decision."""
    state_key = _get_state_key(url)
    state = _discovery_states.get(state_key)

    if not state:
        raise HTTPException(
            status_code=400,
            detail="No active discovery for this URL. Start discovery first.",
        )

    user_input = {"choice": action}

    # selected_url takes priority over link_index
    if "selected_url" in payload:
        user_input["selected_url"] = payload["selected_url"]
    elif "link_index" in payload:
        user_input["link_index"] = payload["link_index"]

    # Advance discovery with user input
    state, next_decision = advance_discovery(
        state=state,
        user_input=user_input,
        mode="auto",
    )

    _discovery_states[state_key] = state

    # Check if done
    completed_plan = None
    if state.done:
        _save_plan_by_url(url, state.plan)
        completed_plan = state.plan.to_dict()
        del _discovery_states[state_key]

    return WaitResponseResult(
        url=url,
        success=True,
        next_decision=next_decision.to_dict() if next_decision else None,
        state=_serialize_discovery_state(state),
        plan=completed_plan,
        message="Final level confirmed" if state.done else "Drilling deeper",
    )


def _handle_fix_field_response(
    url: str, action: str, payload: dict, meta: WaitResponseMeta | None
) -> WaitResponseResult:
    """Handle response to FIX_FIELD decision."""
    if action == "skip":
        # User chose to skip fixing
        return WaitResponseResult(
            url=url,
            success=True,
            message="Field fixing skipped",
        )

    if action != "fix":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action for fix_field: {action}. Expected 'fix' or 'skip'.",
        )

    # Get fixes from payload
    fixes = payload.get("fixes", [])
    if not fixes:
        raise HTTPException(
            status_code=400,
            detail="No fixes provided in payload. Expected 'fixes' array.",
        )

    # Load extraction plan
    extraction_plan = _load_extraction_plan_by_url(url)
    if not extraction_plan:
        raise HTTPException(
            status_code=404,
            detail=f"No extraction plan found for URL: {url}",
        )

    # Apply fixes
    for fix in fixes:
        field_name = fix.get("field")
        if field_name:
            fix_data = {k: v for k, v in fix.items() if k != "field"}
            extraction_plan = apply_field_fix(extraction_plan, field_name, fix_data)

    _save_extraction_plan_by_url(url, extraction_plan)

    # Optionally re-scrape sample to verify fix
    sample = None
    next_decision = None
    if payload.get("resample", True):
        num_rows = payload.get("num_rows", 3)
        sample_result = scrape_sample(
            extraction_plan=extraction_plan,
            max_rows=num_rows,
        )
        sample = sample_result.to_dict()

        # Check if there are still issues
        from catalog import analyze_sample
        decision = analyze_sample(sample_result, extraction_plan)
        if decision:
            next_decision = decision.to_dict()

    return WaitResponseResult(
        url=url,
        success=True,
        extraction_plan=extraction_plan.to_dict(),
        sample=sample,
        next_decision=next_decision,
        message="Field fixes applied" + (" - more issues found" if next_decision else " - all fields OK"),
    )


def _handle_edit_schema_response(
    url: str, action: str, payload: dict, meta: WaitResponseMeta | None
) -> WaitResponseResult:
    """Handle response to EDIT_SCHEMA decision."""
    if action == "skip":
        return WaitResponseResult(
            url=url,
            success=True,
            message="Schema editing skipped",
        )

    if action != "edit":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action for edit_schema: {action}. Expected 'edit' or 'skip'.",
        )

    # Get edits from payload
    edits = payload.get("edits", [])
    if not edits:
        raise HTTPException(
            status_code=400,
            detail="No edits provided in payload. Expected 'edits' array.",
        )

    # Load plan
    normalized, plan = _load_plan_by_url(url)
    if not plan:
        raise HTTPException(
            status_code=404,
            detail=f"No plan found for URL: {url}",
        )

    # Apply edits
    plan = apply_schema_edits(plan, edits)
    _save_plan_by_url(url, plan)

    return WaitResponseResult(
        url=url,
        success=True,
        plan=plan.to_dict(),
        message=f"Applied {len(edits)} schema edit(s)",
    )


def _handle_scrape_more_response(
    url: str, action: str, payload: dict, meta: WaitResponseMeta | None
) -> WaitResponseResult:
    """Handle response to SCRAPE_MORE decision."""
    if action == "stop":
        return WaitResponseResult(
            url=url,
            success=True,
            message="Scraping stopped",
        )

    if action != "continue":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action for scrape_more: {action}. Expected 'continue' or 'stop'.",
        )

    # Get scraping parameters from payload
    num_rows = payload.get("num_rows", 10)
    target_level = payload.get("target_level")

    # Load extraction plan
    extraction_plan = _load_extraction_plan_by_url(url)
    if not extraction_plan:
        raise HTTPException(
            status_code=404,
            detail=f"No extraction plan found for URL: {url}",
        )

    # Scrape more data
    rows = scrape_all(
        extraction_plan=extraction_plan,
        target_level=target_level,
        max_rows=num_rows,
    )

    return WaitResponseResult(
        url=url,
        success=True,
        sample={"rows": rows, "count": len(rows)},
        message=f"Scraped {len(rows)} rows",
    )


# -------------------------
# Health Check
# -------------------------


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
