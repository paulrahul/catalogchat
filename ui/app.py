"""
CatalogChat Streamlit UI

A wizard-style UI for AI-powered catalog schema discovery and data extraction.
Designed so that a non-technical user can go from URL to extracted data in minutes.
"""
import streamlit as st
from typing import Optional
import json
import pandas as pd

from api_client import CatalogChatAPI, DiscoveryResponse
from styles import get_css
from components import (
    render_header,
    render_schema_display,
    render_extraction_plan,
    render_sample_data,
    render_page_preview,
    render_field_cards,
    render_discovery_trail,
    render_editable_field_row,
)

# Page configuration
st.set_page_config(
    page_title="CatalogChat",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject custom CSS
st.markdown(get_css(), unsafe_allow_html=True)

# Define workflow steps
WORKFLOW_STEPS = [
    {"name": "URL", "description": "Choose a catalog"},
    {"name": "Navigate", "description": "Discover the route"},
    {"name": "Review", "description": "See what we'll extract"},
    {"name": "Verify", "description": "Check sample data"},
    {"name": "Extract", "description": "Download your data"},
]


def init_session_state():
    """Initialize session state variables."""
    defaults = {
        "current_step": 0,
        "url": "",
        "mode": "auto",
        "model": "gpt-4o-mini",
        "api_base_url": "http://localhost:8000",
        "discovery_response": None,
        "plan": None,
        "extraction_plan": None,
        "sample_data": None,
        "error": None,
        "is_loading": False,
        "loading_message": "",
        "show_plan_exists_dialog": False,
        "cached_plan": None,
        "force_rediscover": False,
        "show_advanced": False,
        # Discovery navigation history: [{level, name, url}]
        "discovery_history": [],
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_api_client() -> CatalogChatAPI:
    """Get or create API client."""
    return CatalogChatAPI(st.session_state.api_base_url)


def set_error(error: Optional[str]):
    """Set error state."""
    st.session_state.error = error


def advance_step():
    """Move to next workflow step."""
    st.session_state.current_step = min(
        st.session_state.current_step + 1,
        len(WORKFLOW_STEPS) - 1,
    )


def reset_workflow():
    """Reset workflow to initial state."""
    st.session_state.current_step = 0
    st.session_state.discovery_response = None
    st.session_state.plan = None
    st.session_state.extraction_plan = None
    st.session_state.sample_data = None
    st.session_state.error = None
    st.session_state.show_plan_exists_dialog = False
    st.session_state.cached_plan = None
    st.session_state.force_rediscover = False
    st.session_state.schema_edits = {"renames": {}, "deletes": set()}
    st.session_state.show_schema_editor = False
    st.session_state.show_advanced = False
    st.session_state.discovery_history = []


# ============================================================================
# STEP 0: Configuration
# ============================================================================
def render_configuration_step():
    """Render the configuration step - wizard-style URL input."""

    # Check if we're showing the "plan exists" dialog
    if st.session_state.get("show_plan_exists_dialog"):
        render_plan_exists_dialog()
        return

    st.markdown(
        '<div class="wizard-question">Which website\'s catalog would you like to scrape?</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="wizard-hint">Paste the URL of a page that lists the items you want to extract '
        '(e.g. a product listing, directory, or search results page).</div>',
        unsafe_allow_html=True,
    )

    with st.form("config_form"):
        # URL input - prominent
        url = st.text_input(
            "Catalog URL",
            value=st.session_state.url,
            placeholder="https://example.com/products",
            label_visibility="collapsed",
        )

        col1, col2 = st.columns(2)

        with col1:
            mode = st.radio(
                "Discovery Mode",
                options=["auto", "manual"],
                index=0 if st.session_state.mode == "auto" else 1,
                horizontal=True,
                help="**Auto**: AI guides the discovery. **Manual**: You control each step.",
            )

        with col2:
            models = {
                "gpt-4o-mini": "GPT-4o Mini (Fast)",
                "gpt-4o": "GPT-4o (Balanced)",
                "gpt-4-turbo": "GPT-4 Turbo (Accurate)",
            }
            model = st.selectbox(
                "AI Model",
                options=list(models.keys()),
                format_func=lambda x: models[x],
                index=list(models.keys()).index(st.session_state.model)
                if st.session_state.model in models
                else 0,
            )

        with st.expander("Advanced Settings"):
            api_base = st.text_input(
                "API Base URL",
                value=st.session_state.api_base_url,
                help="Backend API URL",
            )

        submitted = st.form_submit_button(
            "Start Discovery", type="primary", use_container_width=True
        )

        if submitted:
            if not url:
                st.error("Please enter a URL")
            else:
                st.session_state.url = url
                st.session_state.mode = mode
                st.session_state.model = model
                st.session_state.api_base_url = api_base

                try:
                    api = get_api_client()
                    existing = api.check_plan_exists(url)

                    if existing.get("plan"):
                        st.session_state.cached_plan = existing["plan"]
                        st.session_state.show_plan_exists_dialog = True
                        st.rerun()
                    else:
                        st.session_state.current_step = 1
                        st.rerun()
                except Exception as e:
                    st.error(f"Cannot reach API server: {str(e)}")


def render_plan_exists_dialog():
    """Render dialog when a plan already exists for the URL."""
    st.markdown(
        '<div class="wizard-question">We already have a navigation plan for this URL</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="wizard-hint">Would you like to reuse the existing plan or discover a fresh route?</div>',
        unsafe_allow_html=True,
    )

    cached_plan = st.session_state.get("cached_plan", {})
    schema_chain = cached_plan.get("schema_chain", [])

    # Show summary of existing plan
    if schema_chain:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Levels", len(schema_chain))
        with col2:
            total_fields = sum(
                len(level.get("fields", [])) for level in schema_chain
            )
            st.metric("Fields", total_fields)

        # Show field names as a quick preview
        all_field_names = []
        for level in schema_chain:
            for f in level.get("fields", []):
                name = f.get("name", "")
                if name and name not in all_field_names:
                    all_field_names.append(name)
        if all_field_names:
            st.markdown(
                "**Fields:** " + ", ".join(f"`{n}`" for n in all_field_names[:12])
                + (f" *and {len(all_field_names) - 12} more*" if len(all_field_names) > 12 else "")
            )

    st.markdown("")
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button(
            "Reuse existing plan",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.plan = cached_plan
            st.session_state.show_plan_exists_dialog = False
            st.session_state.cached_plan = None
            st.session_state.current_step = 2  # Go to review
            st.rerun()

    with col2:
        if st.button(
            "Discover fresh route",
            type="secondary",
            use_container_width=True,
        ):
            st.session_state.show_plan_exists_dialog = False
            st.session_state.cached_plan = None
            st.session_state.force_rediscover = True
            st.session_state.current_step = 1
            st.rerun()

    with col3:
        if st.button("Cancel", use_container_width=True):
            st.session_state.show_plan_exists_dialog = False
            st.session_state.cached_plan = None
            st.rerun()


# ============================================================================
# STEP 1: Discovery
# ============================================================================
def render_discovery_step():
    """Render the discovery step with page preview and friendly prompts."""
    st.markdown(
        '<div class="wizard-question">Discovering the catalog\'s navigation route</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="wizard-hint">'
        "We'll analyze each page level to understand how the catalog is structured."
        "</div>",
        unsafe_allow_html=True,
    )

    api = get_api_client()
    url = st.session_state.url
    mode = st.session_state.mode

    # Check if we need to force a fresh discovery
    if st.session_state.get("force_rediscover"):
        st.session_state.discovery_response = None
        st.session_state.plan = None
        st.session_state.extraction_plan = None
        st.session_state.sample_data = None
        st.session_state.force_rediscover = False
        st.session_state.discovery_history = []

    # Initialize or continue discovery
    response = st.session_state.discovery_response

    if response is None:
        with st.spinner("Analyzing the page..."):
            try:
                response = api.start_discovery(url, mode)
                st.session_state.discovery_response = response
                st.rerun()
            except Exception as e:
                st.error(f"Failed to start discovery: {str(e)}")
                if st.button("Retry"):
                    st.rerun()
                return

    # Check if discovery is complete
    if response.done:
        st.success("Navigation route discovered!")

        st.session_state.plan = response.plan
        st.session_state.current_step = 2
        st.rerun()
        return

    # Show discovery trail breadcrumb
    history = st.session_state.get("discovery_history", [])
    current_level = response.state.current_level if response.state else 1
    current_url = response.state.current_url if response.state else url
    render_discovery_trail(history, current_level, current_url)

    # Show current state metrics
    if response.state:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Current Level", response.state.current_level)
        with col2:
            st.metric("Pages Visited", len(response.state.visited_urls))
        with col3:
            st.metric("Status", "Analyzing...")

    # Handle pending decision
    if response.decision:
        decision = response.decision

        # Determine if we have a drill-down selector to highlight
        highlight_selector = None
        if decision.id == "confirm_drilling":
            highlight_selector = decision.context.get("drill_down_selector")

        # # Page preview with highlighting
        # with st.expander("Page Preview", expanded=True):
        #     render_page_preview(
        #         current_url,
        #         highlight_selector=highlight_selector,
        #         height=380,
        #     )

        st.markdown("---")

        # AI reasoning in a friendly format
        reasoning = decision.context.get("reasoning")
        if reasoning:
            st.markdown(
                f'<div class="ai-reasoning">💡 {reasoning}</div>',
                unsafe_allow_html=True,
            )

        # Schema summary from context (if available)
        schema_summary = decision.context.get("schema_summary", {})
        if schema_summary:
            item_name = schema_summary.get("item_name")
            field_count = schema_summary.get("field_count", 0)
            if item_name or field_count:
                parts = []
                if item_name:
                    parts.append(f"**Items found:** {item_name}")
                if field_count:
                    parts.append(f"**Fields detected:** {field_count}")
                st.markdown(" · ".join(parts))

        # Friendly decision prompt
        st.markdown("")
        _render_discovery_decision(decision, api, url, mode)

    # Cancel button
    st.markdown("---")
    if st.button("Cancel Discovery", type="secondary"):
        reset_workflow()
        st.rerun()


def _render_discovery_decision(decision, api, url, mode):
    """Render discovery decision buttons with friendly labels."""
    # Map decision IDs to friendly prompts
    prompts = {
        "confirm_drilling": "Should we go deeper into the detail pages, or is this the level you want to extract from?",
        "confirm_final_level": "This looks like the final detail level. Shall we proceed with these fields?",
        "select_link": "Is this the level to extract from, or should we drill into a detail page?",
    }
    prompt = prompts.get(decision.id, decision.prompt)
    st.markdown(f"**{prompt}**")

    # Recommended URL preview
    recommended_url = decision.context.get("recommended_url")
    if recommended_url:
        short = recommended_url if len(recommended_url) <= 60 else recommended_url[:57] + "..."
        st.caption(f"Next page: `{short}`")

    # Option buttons with friendly labels
    st.markdown("")
    cols = st.columns(len(decision.options))

    for i, (col, option) in enumerate(zip(cols, decision.options)):
        with col:
            # Map option names to friendly labels
            if option == "continue" and decision.id == "confirm_drilling":
                btn_label = "Yes, go deeper →"
            elif option == "final":
                btn_label = "Extract from this level"
            elif option == "confirm":
                btn_label = "Looks good, continue"
            elif option == "drill":
                btn_label = "Go deeper →"
            else:
                btn_label = option.replace("_", " ").title()

            btn_type = "primary" if i == 0 else "secondary"

            if st.button(
                btn_label,
                key=f"opt_{option}_{i}",
                type=btn_type,
                use_container_width=True,
            ):
                user_input = {"choice": option}

                # Add link index if needed
                if "recommended_link_index" in decision.context:
                    user_input["link_index"] = decision.context[
                        "recommended_link_index"
                    ]

                # Save current level to history before advancing
                current_state = st.session_state.discovery_response.state
                if current_state and option in ("continue", "drill"):
                    history = st.session_state.get("discovery_history", [])
                    schema_summary = decision.context.get("schema_summary", {})
                    history.append(
                        {
                            "level": current_state.current_level,
                            "name": schema_summary.get("item_name")
                            or f"Level {current_state.current_level}",
                            "url": current_state.current_url,
                        }
                    )
                    st.session_state.discovery_history = history

                with st.spinner("Analyzing next level..."):
                    try:
                        new_response = api.advance_discovery(
                            url, user_input, mode
                        )
                        st.session_state.discovery_response = new_response
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")


# ============================================================================
# STEP 2: Review Plan
# ============================================================================
def render_review_step():
    """Render the plan review step with visual field display."""
    st.markdown(
        '<div class="wizard-question">Here\'s what we\'ll extract</div>',
        unsafe_allow_html=True,
    )

    plan = st.session_state.plan

    if not plan:
        st.error("No plan available. Please complete discovery first.")
        if st.button("Go Back"):
            st.session_state.current_step = 1
            st.rerun()
        return

    # Process any pending field edits (from inline edit/delete buttons)
    pending = st.session_state.get("_pending_field_edit")
    if pending:
        st.session_state._pending_field_edit = None
        try:
            api = get_api_client()
            result = api.apply_schema_edits(st.session_state.url, [pending])
            st.session_state.plan = result.get("plan", st.session_state.plan)
            st.session_state.extraction_plan = None
            plan = st.session_state.plan
            st.rerun()
        except Exception as e:
            st.error(f"Failed to update field: {str(e)}")

    schema_chain = plan.get("schema_chain", [])
    merged_fields = plan.get("fields", [])

    # Quick summary
    total_fields = len(merged_fields) if merged_fields else sum(
        len(level.get("fields", [])) for level in schema_chain
    )

    if schema_chain:
        # Build level name path
        level_names = []
        for i, level in enumerate(schema_chain):
            name = level.get("item_name") or f"Level {i + 1}"
            level_names.append(name)
        route = " → ".join(level_names)
    else:
        route = "Single page"

    st.markdown(
        f'<div class="wizard-hint">'
        f"{total_fields} fields across {len(schema_chain)} level(s): {route}"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Toggle for technical details
    show_advanced = st.toggle(
        "Show technical details (CSS selectors)",
        value=st.session_state.get("show_advanced", False),
        key="advanced_toggle",
    )
    st.session_state.show_advanced = show_advanced

    # Schema display with field cards
    render_schema_display(plan, show_advanced=show_advanced, editable=True)

    # Build extraction plan
    if st.session_state.extraction_plan is None:
        with st.spinner("Building extraction plan..."):
            try:
                api = get_api_client()
                extraction_plan = api.get_extraction_plan(st.session_state.url)
                st.session_state.extraction_plan = extraction_plan
                st.rerun()
            except Exception as e:
                st.error(f"Failed to build extraction plan: {str(e)}")

    # if st.session_state.extraction_plan:
    #     st.markdown("---")
    #     st.markdown("##### Extraction plan")
    #     render_extraction_plan(
    #         st.session_state.extraction_plan, show_advanced=show_advanced
    #     )

    # Actions
    st.markdown("---")
    col1, col2 = st.columns([1, 1])

    with col1:
        if st.button(
            "Verify with Sample Data →",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.current_step = 3
            st.rerun()

    with col2:
        if st.button("Start Over", type="secondary", use_container_width=True):
            reset_workflow()
            st.rerun()


# ============================================================================
# STEP 3: Sample Data
# ============================================================================
def render_sample_step():
    """Render the sample data verification step."""
    st.markdown(
        '<div class="wizard-question">Let\'s verify the data looks right</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="wizard-hint">'
        "We'll extract a few sample rows so you can check the results before doing a full extraction."
        "</div>",
        unsafe_allow_html=True,
    )

    sample_data = st.session_state.sample_data

    if sample_data is None:
        col1, col2 = st.columns([3, 1])
        with col1:
            num_rows = st.slider(
                "Number of sample rows", min_value=1, max_value=10, value=3
            )
        with col2:
            st.markdown("")
            st.markdown("")
            fetch_btn = st.button(
                "Fetch Samples", type="primary", use_container_width=True
            )

        if fetch_btn:
            with st.spinner(f"Fetching {num_rows} sample rows..."):
                try:
                    api = get_api_client()
                    sample_data = api.get_sample_data(st.session_state.url, num_rows)
                    st.session_state.sample_data = sample_data
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to fetch sample data: {str(e)}")
        return

    # Display sample data
    render_sample_data(sample_data)

    # Check for issues
    if sample_data.get("decision"):
        decision = sample_data["decision"]
        st.warning(
            f"Potential issue: {decision.get('prompt', 'Some fields may need adjustment')}"
        )

    # Verification options
    st.markdown("---")
    st.markdown("**Does the sample data look correct?**")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button(
            "Looks good, extract! →",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.current_step = 4
            st.rerun()

    with col2:
        if st.button("Refetch Samples", use_container_width=True):
            st.session_state.sample_data = None
            st.rerun()

    with col3:
        if st.button("Fix a Field", use_container_width=True):
            st.session_state.show_field_fixer = True
            st.rerun()

    # Field fixer interface
    if st.session_state.get("show_field_fixer"):
        render_field_fixer()


def render_field_fixer():
    """Render the field fixer interface."""
    st.markdown("---")
    st.markdown("#### Fix a Field")
    st.caption(
        "Tell us which field looks wrong and what the correct value should be. "
        "The AI will suggest a better way to extract it."
    )

    sample_data = st.session_state.sample_data
    field_names = sample_data.get("field_names", [])

    problem_field = st.selectbox(
        "Which field has incorrect data?", options=field_names
    )

    expected_value = st.text_input(
        "What value did you expect?",
        help="Enter an example of what the correct value should look like",
    )

    user_feedback = st.text_area(
        "Additional context (optional)",
        placeholder="Describe what's wrong...",
        help="Provide details to help the AI suggest a better selector",
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button(
            "Get AI Suggestion", type="primary", use_container_width=True
        ):
            if problem_field and expected_value:
                with st.spinner("Getting AI suggestion..."):
                    try:
                        api = get_api_client()
                        suggestion = api.suggest_correction(
                            st.session_state.url,
                            problem_field,
                            expected_value,
                            user_feedback
                            or f"Expected value should be: {expected_value}",
                        )
                        st.session_state.field_suggestion = suggestion
                        st.session_state.problem_field = problem_field
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to get suggestion: {str(e)}")

    with col2:
        if st.button("Cancel", use_container_width=True):
            st.session_state.show_field_fixer = False
            st.session_state.field_suggestion = None
            st.rerun()

    # Show suggestion if available
    if st.session_state.get("field_suggestion"):
        suggestion = st.session_state.field_suggestion
        correction = suggestion.get("correction")
        found_elements = suggestion.get("found_elements", [])

        if found_elements:
            st.markdown("**Found elements:**")
            for elem in found_elements[:5]:
                st.code(str(elem), language=None)

        if correction:
            st.markdown("**Suggested fix:**")
            st.json(correction)

            if st.button("Apply Fix", type="primary"):
                try:
                    api = get_api_client()
                    problem_field = st.session_state.get("problem_field", "")
                    fixes = [
                        {
                            "field": problem_field,
                            "selector": correction.get("selector"),
                            "attribute": correction.get("attribute", "text"),
                            "container_selector": correction.get(
                                "container_selector"
                            ),
                        }
                    ]
                    api.fix_fields(st.session_state.url, fixes)
                    st.session_state.sample_data = None
                    st.session_state.show_field_fixer = False
                    st.session_state.field_suggestion = None
                    st.session_state.problem_field = None
                    st.success("Fix applied! Refetching samples...")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to apply fix: {str(e)}")
        else:
            st.warning(
                "No correction suggestion available. Try providing more context."
            )


# ============================================================================
# STEP 4: Full Extraction
# ============================================================================
def render_extraction_step():
    """Render the full extraction step."""
    st.markdown(
        '<div class="wizard-question">Ready to extract your data</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="wizard-hint">'
        "Choose how many rows to extract and we'll do the rest."
        "</div>",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns([3, 1])

    with col1:
        max_rows = st.number_input(
            "Maximum rows (0 = unlimited)",
            min_value=0,
            max_value=10000,
            value=100,
            step=10,
        )

    with col2:
        st.markdown("")
        st.markdown("")

    with st.expander("Extraction Settings"):
        st.checkbox("Include URLs", value=True, key="include_urls")
        st.checkbox("Include timestamps", value=True, key="include_timestamps")

    if st.button(
        "Start Extraction", type="primary", use_container_width=True
    ):
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            api = get_api_client()
            status_text.text("Extracting data...")

            result = api.scrape_data(
                st.session_state.url,
                max_rows=max_rows if max_rows > 0 else None,
            )

            progress_bar.progress(100)
            status_text.text("Extraction complete!")

            st.session_state.extraction_result = result
            st.rerun()

        except Exception as e:
            st.error(f"Extraction failed: {str(e)}")

    # Show results if available
    if st.session_state.get("extraction_result"):
        result = st.session_state.extraction_result
        rows = result.get("rows", [])
        count = result.get("count", len(rows))

        st.success(f"Successfully extracted {count} rows!")

        if rows:
            df = pd.DataFrame(rows)

            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Rows", count)
            with col2:
                st.metric("Total Columns", len(df.columns))

            if len(df) > 100:
                st.info("Showing first 100 rows. Download the full dataset below.")
                st.dataframe(df.head(100), use_container_width=True)
            else:
                st.dataframe(df, use_container_width=True)

            # Download options
            st.markdown("#### Download Results")
            col1, col2, col3 = st.columns(3)

            with col1:
                json_data = json.dumps(rows, indent=2, default=str)
                st.download_button(
                    "Download JSON",
                    data=json_data,
                    file_name="catalog_data.json",
                    mime="application/json",
                    use_container_width=True,
                )

            with col2:
                csv_data = df.to_csv(index=False)
                st.download_button(
                    "Download CSV",
                    data=csv_data,
                    file_name="catalog_data.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

            with col3:
                if st.button("Start New Extraction", use_container_width=True):
                    reset_workflow()
                    st.rerun()
        else:
            st.warning(
                "No data was extracted. Please check your extraction plan."
            )
            if st.button("Go Back to Review"):
                st.session_state.current_step = 2
                st.rerun()


def render_clickable_progress_steps():
    """Render clickable progress steps in the sidebar."""
    current_step = st.session_state.current_step

    for i, step in enumerate(WORKFLOW_STEPS):
        if i < current_step:
            if st.button(
                f"✓ {step['name']}",
                key=f"nav_step_{i}",
                use_container_width=True,
                type="secondary",
            ):
                st.session_state.current_step = i
                st.rerun()
        elif i == current_step:
            st.markdown(
                f"""<div style="
                    background: #C9B896;
                    color: #3A4A50;
                    padding: 0.5rem 1rem;
                    border-radius: 8px;
                    margin: 0.25rem 0;
                    font-weight: 600;
                    border-left: 4px solid #B0A080;
                ">{i + 1}. {step['name']}</div>""",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""<div style="
                    background: #F1F0E8;
                    color: #7A8A90;
                    padding: 0.5rem 1rem;
                    border-radius: 8px;
                    margin: 0.25rem 0;
                    border: 1px solid #E0D0B8;
                ">{i + 1}. {step['name']}</div>""",
                unsafe_allow_html=True,
            )


# ============================================================================
# Sidebar
# ============================================================================
def render_sidebar():
    """Render the sidebar with progress and info."""
    with st.sidebar:
        st.markdown("## Progress")
        render_clickable_progress_steps()

        st.markdown("---")

        if st.session_state.url:
            st.markdown("### Session")
            display_url = (
                st.session_state.url[:40] + "..."
                if len(st.session_state.url) > 40
                else st.session_state.url
            )
            st.markdown(f"**URL:** `{display_url}`")
            st.markdown(f"**Mode:** {st.session_state.mode.title()}")

        st.markdown("---")

        if st.button("Reset Session", use_container_width=True):
            reset_workflow()
            st.rerun()

        with st.expander("Help"):
            st.markdown("""
            **How it works:**
            1. Enter the URL of a catalog page
            2. We discover the navigation structure
            3. Review the fields we'll extract
            4. Verify with sample data
            5. Extract the full dataset

            **Modes:**
            - **Auto**: AI recommends navigation choices
            - **Manual**: You control each step
            """)


# ============================================================================
# Main Application
# ============================================================================
def main():
    """Main application entry point."""
    init_session_state()

    render_header()
    render_sidebar()

    if st.session_state.error:
        st.error(st.session_state.error)
        if st.button("Dismiss"):
            set_error(None)
            st.rerun()

    current_step = st.session_state.current_step

    if current_step == 0:
        render_configuration_step()
    elif current_step == 1:
        render_discovery_step()
    elif current_step == 2:
        render_review_step()
    elif current_step == 3:
        render_sample_step()
    elif current_step == 4:
        render_extraction_step()


if __name__ == "__main__":
    main()
