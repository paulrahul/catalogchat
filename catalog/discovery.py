"""
Discovery state machine for the catalog library.

This module implements the discovery process as a state machine that can be:
- Started, paused, and resumed
- Driven step-by-step
- Used from any interface (CLI, API, UI)

The key concept is that discovery returns Decision objects when it needs
human input, rather than blocking on I/O.
"""

from typing import Literal

from catalog.types import (
    CatalogPlan,
    DiscoveryState,
    Decision,
    DecisionType,
    DecisionId,
    DecisionStep,
    LevelSchema,
    Field,
)
from bs4 import BeautifulSoup

from catalog.extraction import _extract_field_value
from catalog.schema import summarize_dom, infer_schema, analyze_nesting
from catalog.util import fetch_html, get_resolved_links, resolve_url, is_valid_drill_link, score_drill_link
from catalog.plan import create_plan


def start_discovery(
    plan: CatalogPlan,
    mode: Literal["auto", "manual"] = "auto",
    max_depth: int = 10,
) -> DiscoveryState:
    """
    Start discovery for a CatalogPlan.

    This initializes a DiscoveryState that can be advanced step-by-step.

    Args:
        plan: The CatalogPlan to discover (can be newly created)
        mode: "auto" for LLM-driven discovery, "manual" for user-driven
        max_depth: Maximum nesting depth to explore

    Returns:
        Initial DiscoveryState ready to be advanced
    """
    return DiscoveryState(
        plan=plan,
        current_url=plan.root_url,
        current_level=1,
        visited_urls=set(),
        done=False,
        pending_decision=None,
    )


def advance_discovery(
    state: DiscoveryState,
    user_input: dict | None = None,
    mode: Literal["auto", "manual"] = "auto",
    max_depth: int = 10,
    on_progress=None,
) -> tuple[DiscoveryState, Decision | None]:
    """
    Advance the discovery process by one step.

    This is the core function that drives discovery forward. It:
    1. Processes any pending user input
    2. Fetches and analyzes the current page
    3. Determines the next action
    4. Returns an updated state and optional Decision

    Args:
        state: Current discovery state
        user_input: User's response to a pending Decision (if any)
        mode: "auto" for LLM-driven, "manual" for user-driven
        max_depth: Maximum nesting depth
        on_progress: Optional callback(step, detail) for progress reporting

    Returns:
        Tuple of (updated_state, decision_or_none)
        - If decision is returned, caller should get user input and call advance_discovery again
        - If decision is None and state.done is True, discovery is complete
    """
    # If discovery is already done, return immediately
    if state.done:
        return state, None

    # If there's a pending decision, we need user input to proceed
    if state.pending_decision:
        if user_input:
            # Handle the user's response
            state = _handle_user_input(state, user_input, on_progress)
            # Continue processing after handling input (don't return early)
        else:
            # No user input provided - return the pending decision again (idempotent)
            return state, state.pending_decision

    # Check depth limit
    if state.current_level > max_depth:
        if on_progress:
            on_progress("Warning", f"Reached maximum depth ({max_depth})")
        return _finalize_discovery(state, on_progress), None

    # Check for cycles
    if state.current_url in state.visited_urls:
        if on_progress:
            on_progress("Warning", "URL already visited, stopping to avoid cycle")
        return _finalize_discovery(state, on_progress), None

    # Mark current URL as visited
    state.visited_urls.add(state.current_url)

    if on_progress:
        on_progress(f"Level {state.current_level}", state.current_url)

    # Fetch and analyze the page if we haven't already
    if state._current_html is None:
        try:
            state._current_html = fetch_html(state.current_url, on_progress)
        except Exception as e:
            if on_progress:
                on_progress("Error fetching page", str(e)[:50])
            return _finalize_discovery(state, on_progress), None

        state._current_dom_summary = summarize_dom(state._current_html, on_progress=on_progress)

    # Infer schema if we haven't
    if state._current_schema is None:
        state._current_schema = infer_schema(
            state.current_url,
            state._current_dom_summary,
            on_progress,
            is_final_level=False,
        )

    # Check if this is a catalog at all
    if not state._current_schema.get("is_catalog"):
        # Not a catalog (list) page - this means it's a detail page
        # Re-analyze as detail page to extract fields
        if on_progress:
            on_progress("Not a catalog page", "analyzing as detail page")
        state._current_schema = infer_schema(
            state.current_url,
            state._current_dom_summary,
            on_progress,
            is_final_level=True,
        )
        return _add_level_and_finalize(state, on_progress), None

    # Build the candidate link pool, preferring item-scoped links
    state = _build_link_pool(state, on_progress)

    if not state._unvisited_links:
        if on_progress:
            on_progress("No unvisited links", "treating as final level")
        return _add_level_and_finalize(state, on_progress), None

    # Determine next action based on mode
    if mode == "manual":
        return _handle_manual_mode(state, on_progress)
    else:
        return _handle_auto_mode(state, on_progress)


def _extract_item_links(soup, item_container_sel: str) -> list[dict]:
    """Extract links from within item containers, returning enriched dicts."""
    results = []
    seen: set[str] = set()
    try:
        for container in soup.select(item_container_sel):
            for a in container.find_all("a", href=True):
                href = a.get("href", "")
                if not href or href in seen:
                    continue
                if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                seen.add(href)
                text = a.get_text(strip=True)[:60]
                results.append({"href": href, "text": text, "in_nav": False})
    except Exception:
        pass
    return results


def _url_to_label(url: str) -> str:
    """Derive a readable label from the last segment of a URL path."""
    from urllib.parse import urlparse
    path = urlparse(url).path.rstrip("/")
    slug = path.rsplit("/", 1)[-1] if "/" in path else path
    return slug.replace("-", " ").replace("_", " ").title()


def _build_link_pool(state: DiscoveryState, on_progress=None) -> DiscoveryState:
    """
    Build state._unvisited_links and state._link_labels for the current page.

    Strategy (in priority order):
    1. Extract links from within item containers (item-scoped) — most precise.
    2. Fall back to the full-page link_samples from dom_summary.
    In both cases, resolve to absolute URLs, filter same-domain, deduplicate,
    sort by URL path-prefix score (child URLs first), and exclude visited URLs.
    """
    item_container_sel = (
        (state._current_schema or {}).get("item_schema") or {}
    ).get("item_container_selector")

    link_dicts: list[dict] = []

    if item_container_sel and state._current_html:
        soup = BeautifulSoup(state._current_html, "html.parser")
        item_link_dicts = _extract_item_links(soup, item_container_sel)
        if item_link_dicts:
            if on_progress:
                on_progress("Item-scoped links", f"{len(item_link_dicts)} found in {item_container_sel}")
            link_dicts = item_link_dicts

    if not link_dicts:
        # Fallback: use the full-page link_samples from dom_summary
        link_dicts = state._current_dom_summary.get("link_samples", [])

    # Resolve, filter, deduplicate
    resolved: list[str] = get_resolved_links(state.current_url, link_dicts)

    # Build label map: resolved URL -> anchor text
    link_labels: dict[str, str] = {}
    for ld in link_dicts:
        if not isinstance(ld, dict):
            continue
        href = ld.get("href", "")
        text = ld.get("text", "").strip()
        if href and text:
            abs_url = resolve_url(state.current_url, href)
            if abs_url not in link_labels:
                link_labels[abs_url] = text

    # Sort: child URLs (score 1.0) before sibling paths (score 0.3)
    resolved.sort(key=lambda u: score_drill_link(state.current_url, u), reverse=True)

    state._unvisited_links = [u for u in resolved if u not in state.visited_urls]
    state._link_labels = link_labels
    return state


def _handle_manual_mode(
    state: DiscoveryState, on_progress=None
) -> tuple[DiscoveryState, Decision | None]:
    """Handle manual mode - ask user what to do."""
    ranked_candidates = _build_ranked_candidates_from_pool(state)
    decision = Decision(
        id=DecisionId.SELECT_LINK,
        type=DecisionType.SELECT_LINK,
        step=DecisionStep.DISCOVERY,
        prompt="Is this the final detail level, or should we drill deeper?",
        options=["final", "drill"],
        context={
            "current_url": state.current_url,
            "current_level": state.current_level,
            "available_links": state._unvisited_links[:20],
            "ranked_candidates": ranked_candidates,
            "schema_summary": {
                "catalog_type": state._current_schema.get("catalog_type"),
                "item_name": state._current_schema.get("item_schema", {}).get("item_name"),
            },
        },
    )

    state.pending_decision = decision
    return state, decision


def _build_ranked_candidates_from_pool(state: DiscoveryState) -> list[dict]:
    """Build ranked_candidates from the current scored link pool (no LLM call)."""
    candidates = []
    for url in state._unvisited_links[:8]:
        label = state._link_labels.get(url) or _url_to_label(url)
        candidates.append({
            "url": url,
            "label": label,
            "reason": "",
            "confidence": score_drill_link(state.current_url, url),
        })
    return candidates


def _handle_auto_mode(
    state: DiscoveryState, on_progress=None
) -> tuple[DiscoveryState, Decision | None]:
    """Handle auto mode - use LLM to decide, then confirm with user."""
    # Build enriched link context for the LLM (URL + anchor text + nav flag)
    link_context = [
        {"href": url, "text": state._link_labels.get(url, ""), "in_nav": False}
        for url in state._unvisited_links
    ]

    nesting_result = analyze_nesting(
        state.current_url,
        state._current_dom_summary,
        state._current_schema,
        link_context,
        on_progress,
    )

    is_final = nesting_result.get("is_final_level", True)

    if on_progress:
        on_progress("Nesting analysis", f"Final level: {is_final}")
        reasoning = nesting_result.get("reasoning", "")
        if reasoning:
            on_progress("Reason", reasoning)

    # Store nesting result in schema so it's persisted on the level
    if state._current_schema:
        state._current_schema["nesting_analysis"] = nesting_result

    # Map ranked_candidates indices → resolved URLs with labels
    ranked_candidates = _resolve_ranked_candidates(nesting_result, state)

    schema_summary = {
        "catalog_type": (state._current_schema or {}).get("catalog_type"),
        "item_name": ((state._current_schema or {}).get("item_schema") or {}).get("item_name"),
        "field_count": len(((state._current_schema or {}).get("item_schema") or {}).get("fields", [])),
    }

    if is_final:
        decision = Decision(
            id=DecisionId.CONFIRM_FINAL_LEVEL,
            type=DecisionType.CONFIRM_FINAL_LEVEL,
            step=DecisionStep.NESTING_ANALYSIS,
            prompt="The AI determined this is the final detail level. Confirm to complete discovery, or choose to drill deeper.",
            options=["confirm", "drill"],
            context={
                "current_url": state.current_url,
                "current_level": state.current_level,
                "reasoning": nesting_result.get("reasoning"),
                "available_links": state._unvisited_links[:10],
                "ranked_candidates": ranked_candidates,
                "schema_summary": schema_summary,
            },
        )
        state.pending_decision = decision
        return state, decision

    # LLM recommends drilling — derive recommended_url from top ranked candidate
    recommended_url = ranked_candidates[0]["url"] if ranked_candidates else None
    if not recommended_url and state._unvisited_links:
        recommended_url = state._unvisited_links[0]

    if not recommended_url:
        decision = Decision(
            id=DecisionId.CONFIRM_FINAL_LEVEL,
            type=DecisionType.CONFIRM_FINAL_LEVEL,
            step=DecisionStep.NESTING_ANALYSIS,
            prompt="No more links to explore. Confirm to complete discovery.",
            options=["confirm"],
            context={
                "current_url": state.current_url,
                "current_level": state.current_level,
                "reasoning": "No unvisited links available for drilling",
                "ranked_candidates": [],
            },
        )
        state.pending_decision = decision
        return state, decision

    if on_progress:
        label = state._link_labels.get(recommended_url) or recommended_url
        on_progress("Recommended drill", label)

    decision = Decision(
        id=DecisionId.CONFIRM_DRILLING,
        type=DecisionType.CONFIRM_DRILLING,
        step=DecisionStep.NESTING_ANALYSIS,
        prompt="The AI recommends drilling deeper. Do you want to continue?",
        options=["continue", "final"],
        context={
            "current_url": state.current_url,
            "recommended_url": recommended_url,
            "reasoning": nesting_result.get("reasoning"),
            "drill_down_selector": nesting_result.get("drill_down_link_selector"),
            "link_reason": nesting_result.get("recommended_link_reason"),
            "ranked_candidates": ranked_candidates,
        },
    )

    state.pending_decision = decision
    return state, decision


def _resolve_ranked_candidates(nesting_result: dict, state: DiscoveryState) -> list[dict]:
    """
    Map the LLM's ranked_candidates (index-based) to resolved URLs with labels.

    Falls back to the top scored links from the pool if the LLM returns nothing.
    """
    candidates: list[dict] = []

    for raw in nesting_result.get("ranked_candidates", []):
        idx = raw.get("link_index")
        if idx is None:
            continue
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < len(state._unvisited_links)):
            continue
        url = state._unvisited_links[idx]
        label = (
            raw.get("label")
            or state._link_labels.get(url)
            or _url_to_label(url)
        )
        candidates.append({
            "url": url,
            "label": label,
            "reason": raw.get("reason", ""),
            "confidence": float(raw.get("confidence", 0.0)),
        })

    if not candidates:
        candidates = _build_ranked_candidates_from_pool(state)

    return candidates


def _resolve_drill_url(user_input: dict, decision, state: DiscoveryState) -> str | None:
    """
    Resolve which URL to drill into from user_input.

    Priority:
    1. selected_url explicitly provided (new UI sends this)
    2. link_index into _unvisited_links (CLI / legacy)
    3. recommended_url from the decision context
    4. First unvisited link
    """
    selected_url = user_input.get("selected_url")
    if selected_url and selected_url in state._unvisited_links:
        return selected_url

    link_index = user_input.get("link_index")
    if link_index is not None:
        try:
            idx = int(link_index)
            if 0 <= idx < len(state._unvisited_links):
                return state._unvisited_links[idx]
        except (TypeError, ValueError):
            pass

    recommended = decision.context.get("recommended_url") if decision else None
    if recommended and recommended in state._unvisited_links:
        return recommended

    return state._unvisited_links[0] if state._unvisited_links else None


def _drill_to(state: DiscoveryState, next_url: str, on_progress=None) -> DiscoveryState:
    """Add the current level to the chain and move state to next_url."""
    state = _add_level_to_chain(state, on_progress)
    state.current_url = next_url
    state.current_level += 1
    state._current_html = None
    state._current_dom_summary = None
    state._current_schema = None
    state._unvisited_links = []
    state._link_labels = {}
    return state


def _handle_user_input(
    state: DiscoveryState, user_input: dict, on_progress=None
) -> DiscoveryState:
    """Process user input for a pending decision."""
    decision = state.pending_decision
    if not decision:
        return state

    state.pending_decision = None

    if decision.type == DecisionType.CONFIRM_DRILLING:
        choice = user_input.get("choice", "continue")

        if choice == "final":
            state._current_schema = infer_schema(
                state.current_url,
                state._current_dom_summary,
                on_progress,
                is_final_level=True,
            )
            return _add_level_and_mark_done(state, on_progress)

        elif choice == "stop":
            if on_progress:
                on_progress("Discovery stopped by user", "")
            return _add_level_and_mark_done(state, on_progress)

        else:  # continue
            next_url = _resolve_drill_url(user_input, decision, state)
            if next_url:
                state = _drill_to(state, next_url, on_progress)
            return state

    elif decision.type == DecisionType.CONFIRM_FINAL_LEVEL:
        choice = user_input.get("choice", "confirm")

        if choice == "confirm":
            if on_progress:
                on_progress("Confirmed final level", state.current_url)
            if not state._current_schema or not state._current_schema.get("item_schema", {}).get("fields"):
                state._current_schema = infer_schema(
                    state.current_url,
                    state._current_dom_summary,
                    on_progress,
                    is_final_level=True,
                )
            return _add_level_and_mark_done(state, on_progress)

        elif choice == "drill":
            next_url = _resolve_drill_url(user_input, decision, state)
            if next_url:
                state = _drill_to(state, next_url, on_progress)
            return state

    elif decision.type == DecisionType.SELECT_LINK:
        choice = user_input.get("choice", "final")

        if choice == "final":
            state._current_schema = infer_schema(
                state.current_url,
                state._current_dom_summary,
                on_progress,
                is_final_level=True,
            )
            return _add_level_and_mark_done(state, on_progress)

        elif choice == "drill":
            next_url = _resolve_drill_url(user_input, decision, state)
            if next_url:
                state = _drill_to(state, next_url, on_progress)
            return state

    return state


def _add_level_to_chain(state: DiscoveryState, on_progress=None) -> DiscoveryState:
    """Add the current level's schema to the schema chain."""
    schema = state._current_schema
    if schema:
        # Convert to LevelSchema and add fields
        # Handle None or missing item_schema gracefully
        item_schema = schema.get("item_schema") or {}
        fields = [
            Field.from_dict(f) for f in (item_schema.get("fields") or [])
        ]

        # Best-effort: extract a sample value for each field from the page HTML
        try:
            if state._current_html and fields:
                soup = BeautifulSoup(state._current_html, "html.parser")
                fallback_container = None
                if schema.get("is_catalog"):
                    # For catalog pages, scope to the first item container
                    container_sel = item_schema.get("item_container_selector")
                    if container_sel:
                        fallback_container = soup.select_one(container_sel)
                else:
                    # For detail pages, the whole page is the context
                    fallback_container = soup

                for f in fields:
                    val = _extract_field_value(soup, f, fallback_container)
                    if val is not None:
                        f.sample_value = val[:200]
        except Exception:
            pass  # sample values are best-effort

        level_schema = LevelSchema(
            level=state.current_level,
            url=state.current_url,
            is_catalog=schema.get("is_catalog", False),
            catalog_type=schema.get("catalog_type"),
            confidence=schema.get("confidence", 0.0),
            archetype=schema.get("archetype"),
            item_name=item_schema.get("item_name"),
            item_container_selector=item_schema.get("item_container_selector"),
            fields=fields,
            reasoning=schema.get("reasoning", ""),
            nesting_analysis=schema.get("nesting_analysis"),
        )

        state.plan.schema_chain.append(level_schema)
        state.plan.visited_urls.append(state.current_url)

    return state


def _add_level_and_finalize(
    state: DiscoveryState, on_progress=None
) -> DiscoveryState:
    """Add current level and finalize discovery."""
    state = _add_level_to_chain(state, on_progress)
    return _finalize_discovery(state, on_progress)


def _add_level_and_mark_done(
    state: DiscoveryState, on_progress=None
) -> DiscoveryState:
    """Add current level and mark discovery as done."""
    state = _add_level_to_chain(state, on_progress)
    state.done = True
    return _update_plan_from_chain(state, on_progress)


def _finalize_discovery(state: DiscoveryState, on_progress=None) -> DiscoveryState:
    """Finalize discovery and merge schemas."""
    state.done = True
    state.pending_decision = None  # Clear any pending decision
    return _update_plan_from_chain(state, on_progress)


def _update_plan_from_chain(
    state: DiscoveryState, on_progress=None
) -> DiscoveryState:
    """Update the plan from the schema chain."""
    chain = state.plan.schema_chain

    if chain:
        # item_name comes from the final (deepest) level
        final_level = chain[-1]
        state.plan.item_name = final_level.item_name or "Item"
        state.plan.nesting_depth = len(chain)
        state.plan.level_names = [
            ls.catalog_type or f"level_{ls.level}" for ls in chain
        ]
    else:
        state.plan.item_name = "Item"
        state.plan.nesting_depth = 1
        state.plan.level_names = []

    state.plan.visited_urls = list(state.visited_urls)

    if on_progress:
        total_fields = sum(len(ls.fields) for ls in chain)
        on_progress("Discovery complete", f"{total_fields} fields, {state.plan.nesting_depth} levels")

    return state


def run_discovery_simple(
    root_url: str,
    mode: Literal["auto", "manual"] = "auto",
    max_depth: int = 10,
    on_progress=None,
    on_decision=None,
) -> CatalogPlan:
    """
    Run complete discovery with a simple callback for decisions.

    This is a convenience function that drives the full discovery loop.
    For more control, use start_discovery() and advance_discovery() directly.

    Args:
        root_url: The URL to start discovery from
        mode: "auto" or "manual"
        max_depth: Maximum depth
        on_progress: Optional callback(step, detail)
        on_decision: Callback(decision) -> dict that handles decisions
                    If None, uses default behavior (auto-continue)

    Returns:
        Completed CatalogPlan
    """
    plan = create_plan(root_url)
    state = start_discovery(plan, mode, max_depth)

    while not state.done:
        state, decision = advance_discovery(
            state,
            user_input=None,
            mode=mode,
            max_depth=max_depth,
            on_progress=on_progress,
        )

        if decision:
            if on_decision:
                user_input = on_decision(decision)
            else:
                # Default: continue in auto mode, mark as final in manual mode
                if decision.type == DecisionType.CONFIRM_DRILLING:
                    user_input = {"choice": "continue"}
                else:
                    user_input = {"choice": "final"}

            state, decision = advance_discovery(
                state,
                user_input=user_input,
                mode=mode,
                max_depth=max_depth,
                on_progress=on_progress,
            )

    return state.plan
