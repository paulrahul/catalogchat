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
    Field,
    LevelSchema,
)
from catalog.schema import summarize_dom, infer_schema, analyze_nesting, merge_schemas
from catalog.util import fetch_html, get_resolved_links
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

    # Handle pending decision if we have user input
    if state.pending_decision and user_input:
        state = _handle_user_input(state, user_input, on_progress)
        # Always return after processing user input - let next call handle the new state
        return state, None

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

    # Check if we're waiting for user to confirm this is final level
    if state.pending_decision and state.pending_decision.type == DecisionType.CONFIRM_FINAL_LEVEL:
        # User said this is final - reanalyze as detail page
        state._current_schema = infer_schema(
            state.current_url,
            state._current_dom_summary,
            on_progress,
            is_final_level=True,
        )
        return _add_level_and_finalize(state, on_progress), None

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

    # Get links for potential drilling
    link_samples = state._current_dom_summary.get("link_samples", [])
    resolved_links = get_resolved_links(state.current_url, link_samples)
    state._unvisited_links = [link for link in resolved_links if link not in state.visited_urls]

    if not state._unvisited_links:
        if on_progress:
            on_progress("No unvisited links", "treating as final level")
        return _add_level_and_finalize(state, on_progress), None

    # Determine next action based on mode
    if mode == "manual":
        return _handle_manual_mode(state, on_progress)
    else:
        return _handle_auto_mode(state, on_progress)


def _handle_manual_mode(
    state: DiscoveryState, on_progress=None
) -> tuple[DiscoveryState, Decision | None]:
    """Handle manual mode - ask user what to do."""
    # Ask user if this is the final level or if they want to drill deeper
    decision = Decision(
        id=DecisionId.SELECT_LINK,
        type=DecisionType.SELECT_LINK,
        step=DecisionStep.DISCOVERY,
        prompt="Is this the final detail level, or should we drill deeper?",
        options=["final", "drill"],
        context={
            "current_url": state.current_url,
            "current_level": state.current_level,
            "available_links": state._unvisited_links[:20],  # Limit shown links
            "schema_summary": {
                "catalog_type": state._current_schema.get("catalog_type"),
                "item_name": state._current_schema.get("item_schema", {}).get("item_name"),
            },
        },
    )

    state.pending_decision = decision
    return state, decision


def _handle_auto_mode(
    state: DiscoveryState, on_progress=None
) -> tuple[DiscoveryState, Decision | None]:
    """Handle auto mode - use LLM to decide, then confirm with user."""
    # Analyze nesting with LLM
    nesting_result = analyze_nesting(
        state.current_url,
        state._current_dom_summary,
        state._current_schema,
        state._unvisited_links,
        on_progress,
    )

    is_final = nesting_result.get("is_final_level", True)

    if on_progress:
        reasoning = nesting_result.get("reasoning", "")
        on_progress("Nesting analysis", f"Final level: {is_final}")
        if reasoning:
            on_progress("Reason", reasoning)

    if is_final:
        # LLM says this is final - just proceed
        return _add_level_and_finalize(state, on_progress), None

    # LLM recommends drilling - ask user to confirm
    link_index = nesting_result.get("recommended_link_index")
    if link_index is None:
        return _add_level_and_finalize(state, on_progress), None

    try:
        link_index = int(link_index)
    except (TypeError, ValueError):
        if on_progress:
            on_progress("Warning", f"Invalid link index: {link_index}")
        return _add_level_and_finalize(state, on_progress), None

    if link_index < 0 or link_index >= len(state._unvisited_links):
        if on_progress:
            on_progress("Warning", f"Link index {link_index} out of range")
        return _add_level_and_finalize(state, on_progress), None

    recommended_url = state._unvisited_links[link_index]

    if on_progress:
        on_progress("Recommended drill URL", recommended_url)

    # Create decision for user confirmation
    decision = Decision(
        id=DecisionId.CONFIRM_DRILLING,
        type=DecisionType.CONFIRM_DRILLING,
        step=DecisionStep.NESTING_ANALYSIS,
        prompt="The AI recommends drilling deeper. Do you want to continue?",
        options=["continue", "final", "stop"],
        context={
            "current_url": state.current_url,
            "recommended_url": recommended_url,
            "reasoning": nesting_result.get("reasoning"),
            "drill_down_selector": nesting_result.get("drill_down_link_selector"),
            "link_reason": nesting_result.get("recommended_link_reason"),
        },
    )

    # Store nesting result in state for later use
    state._current_schema["nesting_analysis"] = nesting_result

    state.pending_decision = decision
    return state, decision


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
            # User says this is final - reanalyze as detail page
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
            # Proceed to next level
            recommended_url = decision.context.get("recommended_url")
            if recommended_url:
                # Add current level to chain
                state = _add_level_to_chain(state, on_progress)
                # Move to next level
                state.current_url = recommended_url
                state.current_level += 1
                # Reset page state
                state._current_html = None
                state._current_dom_summary = None
                state._current_schema = None
                state._unvisited_links = []
            return state

    elif decision.type == DecisionType.SELECT_LINK:
        choice = user_input.get("choice", "final")

        if choice == "final":
            # User confirms this is final
            state._current_schema = infer_schema(
                state.current_url,
                state._current_dom_summary,
                on_progress,
                is_final_level=True,
            )
            return _add_level_and_mark_done(state, on_progress)

        elif choice == "drill":
            # User wants to drill - get selected link
            selected_index = user_input.get("link_index", 0)
            if 0 <= selected_index < len(state._unvisited_links):
                selected_url = state._unvisited_links[selected_index]
                # Add current level to chain
                state = _add_level_to_chain(state, on_progress)
                # Move to next level
                state.current_url = selected_url
                state.current_level += 1
                # Reset page state
                state._current_html = None
                state._current_dom_summary = None
                state._current_schema = None
                state._unvisited_links = []
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
    return _update_plan_from_chain(state, on_progress)


def _update_plan_from_chain(
    state: DiscoveryState, on_progress=None
) -> DiscoveryState:
    """Update the plan from the schema chain."""
    # Convert schema chain to format expected by merge_schemas
    schema_chain_dicts = []
    for level_schema in state.plan.schema_chain:
        schema_chain_dicts.append({
            "level": level_schema.level,
            "url": level_schema.url,
            "schema": {
                "is_catalog": level_schema.is_catalog,
                "catalog_type": level_schema.catalog_type,
                "confidence": level_schema.confidence,
                "archetype": level_schema.archetype,
                "reasoning": level_schema.reasoning,
                "item_schema": {
                    "item_name": level_schema.item_name,
                    "item_container_selector": level_schema.item_container_selector,
                    "fields": [f.to_dict() for f in level_schema.fields],
                },
            },
            "nesting_analysis": level_schema.nesting_analysis,
        })

    # Merge schemas
    merged = merge_schemas(schema_chain_dicts, on_progress)

    # Update plan
    state.plan.item_name = merged.get("item_name", "Item")
    state.plan.nesting_depth = merged.get("nesting_depth", 1)
    state.plan.level_names = merged.get("level_names", [])
    state.plan.fields = [Field.from_dict(f) for f in merged.get("fields", [])]
    state.plan.visited_urls = list(state.visited_urls)

    if on_progress:
        on_progress("Discovery complete", f"{len(state.plan.fields)} fields, {state.plan.nesting_depth} levels")

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
