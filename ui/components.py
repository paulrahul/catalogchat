"""
Reusable UI components for the CatalogChat Streamlit UI.
"""
import re
import json

import httpx
import streamlit as st
import streamlit.components.v1 as stc
from typing import Any, Optional


# =============================================================================
# Header
# =============================================================================

def render_header():
    """Render the main application header."""
    st.markdown("""
        <div style="
            background: #ADC4CE;
            padding: 1.5rem 2rem;
            border-radius: 12px;
            margin-bottom: 1.5rem;
            text-align: center;
            border: 1px solid #8BAAB6;
        ">
            <h1 style="margin: 0; font-size: 2.2rem; font-weight: 700; color: #3A4A50;">CatalogChat</h1>
            <p style="margin: 0.3rem 0 0; color: #5A6A70; font-size: 1rem;">Turn any website's catalog into structured data</p>
        </div>
    """, unsafe_allow_html=True)


# =============================================================================
# Page Preview with Selector Highlighting
# =============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_preview_html(url: str) -> Optional[str]:
    """Fetch and sanitize page HTML for preview display."""
    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=15.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
        )
        html = resp.text
        # Remove scripts for security (preview is display-only)
        html = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
        # Remove event handlers
        html = re.sub(r'\s+on\w+="[^"]*"', '', html, flags=re.IGNORECASE)
        # Inject base tag for proper URL resolution of images/CSS
        base_tag = f'<base href="{url}" target="_blank">'
        if re.search(r'<head[^>]*>', html, re.IGNORECASE):
            html = re.sub(r'(<head[^>]*>)', rf'\1{base_tag}', html, count=1, flags=re.IGNORECASE)
        else:
            html = f'<html><head>{base_tag}</head><body>{html}</body></html>'
        return html
    except Exception:
        return None


def render_page_preview(
    url: str,
    highlight_selector: Optional[str] = None,
    height: int = 420,
):
    """
    Render a live page preview with optional CSS selector highlighting.

    Args:
        url: The page URL to preview
        highlight_selector: CSS selector to highlight (e.g. drill-down links)
        height: Height of the preview iframe in pixels
    """
    # Browser-style header bar
    short_url = url if len(url) <= 70 else url[:67] + "..."
    st.markdown(f"""
        <div class="preview-bar">
            <span class="preview-dot preview-dot-red"></span>
            <span class="preview-dot preview-dot-yellow"></span>
            <span class="preview-dot preview-dot-green"></span>
            <span class="preview-url">{short_url}</span>
        </div>
    """, unsafe_allow_html=True)

    html = _fetch_preview_html(url)

    if html is None:
        st.caption(f"Preview unavailable. [Open in browser]({url})")
        return

    # Inject highlight CSS if a selector is provided
    if highlight_selector:
        # Escape the selector for safe injection into CSS
        highlight_css = f"""
        <style>
            {highlight_selector} {{
                outline: 3px solid #E74C3C !important;
                outline-offset: 3px !important;
                box-shadow: 0 0 20px rgba(231, 76, 60, 0.5) !important;
                animation: cc-highlight-pulse 1.5s ease-in-out infinite !important;
                position: relative !important;
                z-index: 9999 !important;
            }}
            @keyframes cc-highlight-pulse {{
                0%, 100% {{ box-shadow: 0 0 15px rgba(231, 76, 60, 0.4); }}
                50% {{ box-shadow: 0 0 30px rgba(231, 76, 60, 0.7); }}
            }}
        </style>
        """
        if re.search(r'</head>', html, re.IGNORECASE):
            html = re.sub(r'</head>', f'{highlight_css}</head>', html, count=1, flags=re.IGNORECASE)
        else:
            html = highlight_css + html

    stc.html(html, height=height, scrolling=True)

    # Legend if highlighting
    if highlight_selector:
        st.markdown(
            '<div class="highlight-legend">'
            '<span class="highlight-swatch"></span>'
            'Red highlight = drill-down links the AI detected'
            '</div>',
            unsafe_allow_html=True,
        )


# =============================================================================
# Field Cards (user-friendly field display with sample values)
# =============================================================================

def render_field_cards(fields: list[dict], show_advanced: bool = False):
    """
    Render fields as visual cards with sample values.

    Default view is user-friendly (name + sample + type).
    Advanced view adds CSS selectors and attributes.
    """
    if not fields:
        st.info("No fields discovered yet.")
        return

    # Build HTML cards for all fields
    cards_html = '<div class="field-card-grid">'
    for field in fields:
        name = field.get("name", "unknown")
        field_type = field.get("type", "string")
        sample = field.get("sample_value")

        sample_html = ""
        if sample:
            display = sample[:80] + "..." if len(sample) > 80 else sample
            # Escape HTML entities in sample values
            display = display.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            sample_html = f'<div class="field-card-sample">"{display}"</div>'
        else:
            sample_html = '<div class="field-card-sample" style="opacity:0.5;">no sample</div>'

        advanced_html = ""
        if show_advanced:
            selector = field.get("selector", "N/A") or "N/A"
            attribute = field.get("attribute", "text")
            container = field.get("container_selector", "")
            sel_display = selector[:50] + "..." if len(selector) > 50 else selector
            sel_display = sel_display.replace("<", "&lt;").replace(">", "&gt;")
            advanced_html = (
                f'<div style="margin-top:0.4rem;font-size:0.75rem;color:#7A8A90;font-family:monospace;">'
                f'{sel_display} &rarr; {attribute}'
            )
            if container:
                c_display = container[:40] + "..." if len(container) > 40 else container
                c_display = c_display.replace("<", "&lt;").replace(">", "&gt;")
                advanced_html += f'<br/>container: {c_display}'
            advanced_html += '</div>'

        # Build card HTML without blank lines — blank lines (even whitespace-only)
        # cause st.markdown's CommonMark parser to terminate the HTML block early,
        # rendering subsequent cards as escaped text.
        card_parts = [
            '<div class="field-card">',
            f'<div class="field-card-name">{name}</div>',
            sample_html,
            f'<span class="field-card-type">{field_type}</span>',
        ]
        if advanced_html:
            card_parts.append(advanced_html)
        card_parts.append('</div>')
        cards_html += '\n'.join(card_parts)

    cards_html += '</div>'
    st.markdown(cards_html, unsafe_allow_html=True)


# =============================================================================
# Editable Field Row (inline edit/delete per field)
# =============================================================================

def render_editable_field_row(level: int, field: dict, show_advanced: bool = False):
    """Render a single field with inline edit and delete controls."""
    field_name = field.get("name", "unknown")
    # qualified_name is ONLY for Streamlit widget key uniqueness (avoids
    # collisions when the same field name appears at different levels).
    widget_key = f"level_{level}_{field_name}"
    field_type = field.get("type", "string")
    sample = field.get("sample_value", "")

    editing_key = f"_editing_{widget_key}"
    is_editing = st.session_state.get(editing_key, False)

    if is_editing:
        c1, c2, c3 = st.columns([4, 1, 1])
        with c1:
            new_name = st.text_input(
                "Rename",
                value=field_name,
                key=f"_rename_input_{widget_key}",
                label_visibility="collapsed",
                placeholder="Field name",
            )
        with c2:
            if st.button("Save", key=f"_save_{widget_key}", type="primary"):
                if new_name and new_name != field_name:
                    st.session_state._pending_field_edit = {
                        "action": "rename",
                        "field": field_name,
                        "new_name": new_name,
                        "level": level,
                    }
                st.session_state[editing_key] = False
                st.rerun()
        with c3:
            if st.button("Cancel", key=f"_cancel_{widget_key}"):
                st.session_state[editing_key] = False
                st.rerun()
    else:
        c1, c2, c3 = st.columns([8, 1, 1])
        with c1:
            sample_html = ""
            if sample:
                display_sample = (
                    sample[:60] + "..." if len(sample) > 60 else sample
                )
                display_sample = (
                    display_sample.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
                )
                sample_html = (
                    f' <span style="color:#7A8A90;font-style:italic;'
                    f'font-size:0.85rem;">&mdash; "{display_sample}"</span>'
                )
            name_html = field_name.replace("<", "&lt;").replace(">", "&gt;")
            advanced_html = ""
            if show_advanced:
                selector = field.get("selector", "N/A") or "N/A"
                attribute = field.get("attribute", "text")
                sel_display = (
                    selector[:50] + "..." if len(selector) > 50 else selector
                )
                sel_display = sel_display.replace("<", "&lt;").replace(">", "&gt;")
                advanced_html = (
                    f'<br/><span style="font-size:0.75rem;color:#7A8A90;'
                    f'font-family:monospace;">{sel_display} &rarr; {attribute}</span>'
                )
            st.markdown(
                f'<span style="font-weight:600;">{name_html}</span>'
                f'{sample_html}'
                f' <span class="field-card-type">{field_type}</span>'
                f'{advanced_html}',
                unsafe_allow_html=True,
            )
        with c2:
            if st.button("✏️", key=f"_edit_{widget_key}", help="Rename"):
                st.session_state[editing_key] = True
                st.rerun()
        with c3:
            if st.button("🗑️", key=f"_del_{widget_key}", help="Delete"):
                st.session_state._pending_field_edit = {
                    "action": "delete",
                    "field": field_name,
                    "level": level,
                }
                st.rerun()


# =============================================================================
# Schema Display (for Review step)
# =============================================================================

def render_schema_display(plan: dict, show_advanced: bool = False, editable: bool = False):
    """
    Render the extraction schema.

    Default view: visual field cards per level.
    Advanced view: includes CSS selectors and attributes.
    Editable view: inline edit/delete controls per field.
    """
    schema_chain = plan.get("schema_chain", [])

    if not schema_chain:
        st.info("No schema levels defined yet.")
        return

    st.markdown("##### Fields to extract")

    for i, level in enumerate(schema_chain):
        item_name = level.get("item_name") or f"Level {i + 1}"
        catalog_type = level.get("catalog_type")
        badge = f" ({catalog_type})" if catalog_type else ""

        fields = level.get("fields", [])

        with st.expander(
            f"Level {i + 1}: {item_name}{badge}",
            expanded=True,
        ):
            if not fields:
                st.caption("No fields at this level")
                continue

            for field in fields:
                render_editable_field_row(i, field, show_advanced)

            if show_advanced:
                container = level.get("item_container_selector")
                if container:
                    st.caption(f"Item container: `{container}`")
                url = level.get("url")
                if url:
                    st.caption(f"Sample URL: `{url}`")


# =============================================================================
# Extraction Plan Display (for Review step)
# =============================================================================

def render_extraction_plan(extraction_plan: dict, show_advanced: bool = False):
    """Render the extraction plan with navigation paths."""
    summary = extraction_plan.get("summary", {})
    navigation_path = extraction_plan.get("navigation_path", [])
    final_fields = extraction_plan.get("final_field_names", [])

    # Summary
    if summary:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Levels", summary.get("total_levels", len(navigation_path)))
        with col2:
            st.metric("Fields", summary.get("total_fields", len(final_fields)))
        with col3:
            path_desc = summary.get("path_description", "N/A")
            if len(path_desc) > 25:
                path_desc = path_desc[:22] + "..."
            st.metric("Path", path_desc)

    # Navigation route visualization
    if navigation_path and len(navigation_path) > 1:
        route_parts = []
        for i, level in enumerate(navigation_path):
            name = level.get("level_name") or level.get("item_name") or f"Level {i+1}"
            is_final = level.get("is_final_level", False)
            suffix = " (extract)" if is_final else ""
            route_parts.append(f"{name}{suffix}")
        st.markdown("**Navigation route:** " + " → ".join(route_parts))

    # Field summary
    if final_fields:
        st.markdown("**Extracted fields:** " + ", ".join(f"`{f}`" for f in final_fields))

    # Detailed level info (advanced)
    if show_advanced and navigation_path:
        st.markdown("---")
        st.markdown("##### Navigation details")
        for i, level in enumerate(navigation_path):
            level_name = level.get("level_name", f"Level {i + 1}")
            is_final = level.get("is_final_level", False)
            badge = " (Final)" if is_final else ""

            with st.expander(f"Level {i + 1}: {level_name}{badge}", expanded=False):
                if level.get("sample_url"):
                    sample_url = level["sample_url"]
                    display_url = sample_url[:60] + "..." if len(sample_url) > 60 else sample_url
                    st.markdown(f"**Sample URL:** `{display_url}`")
                if level.get("item_container_selector"):
                    st.markdown(f"**Container:** `{level['item_container_selector']}`")
                if level.get("drill_down_link_selector"):
                    st.markdown(f"**Drill-down link:** `{level['drill_down_link_selector']}`")

                fields = level.get("fields", [])
                if fields:
                    st.markdown("**Fields:**")
                    for field in fields:
                        attr = field.get("attribute", "text")
                        st.markdown(f"- `{field['name']}`: {field.get('selector', 'N/A')} → {attr}")


# =============================================================================
# Sample Data Display
# =============================================================================

def render_sample_data(sample_result: dict):
    """Render sample data in a table format."""
    rows = sample_result.get("rows", [])
    field_names = sample_result.get("field_names", [])

    if not rows:
        st.warning("No sample data retrieved.")
        return

    st.markdown(f"**{len(rows)} sample row(s) retrieved**")

    import pandas as pd

    # Convert to DataFrame
    if rows and isinstance(rows[0], dict):
        df = pd.DataFrame(rows)
    elif rows and isinstance(rows[0], (list, tuple)):
        if field_names and len(field_names) == len(rows[0]):
            df = pd.DataFrame(rows, columns=field_names)
        else:
            df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame(rows)

    # Truncate long values for display
    def truncate(val, max_len=100):
        if isinstance(val, str) and len(val) > max_len:
            return val[:max_len] + "..."
        return val

    display_df = df.map(truncate)
    st.dataframe(display_df, use_container_width=True)

    if field_names:
        with st.expander("Field names"):
            st.write(", ".join(f"`{f}`" for f in field_names))


# =============================================================================
# Discovery Breadcrumb Trail
# =============================================================================

def render_discovery_trail(history: list[dict], current_level: int, current_url: str):
    """
    Render a visual breadcrumb trail of discovery levels.

    Args:
        history: List of {level, name, url} dicts for completed levels
        current_level: Current level number being analyzed
        current_url: Current URL being analyzed
    """
    if not history and current_level <= 1:
        return

    parts = []
    for item in history:
        name = item.get("name", f"Level {item.get('level', '?')}")
        parts.append(f'<span class="nav-trail-level">{name}</span>')
        parts.append('<span class="nav-trail-arrow">→</span>')

    parts.append(f'<span class="nav-trail-current">Level {current_level} (analyzing...)</span>')

    st.markdown(
        '<div class="nav-trail">' + " ".join(parts) + '</div>',
        unsafe_allow_html=True,
    )


# =============================================================================
# Utility Components
# =============================================================================

def render_progress_steps(current_step: int, steps: list[dict]):
    """Render progress steps indicator."""
    st.markdown('<div class="progress-container">', unsafe_allow_html=True)

    for i, step in enumerate(steps):
        if i < current_step:
            status = "complete"
            icon = "✓"
        elif i == current_step:
            status = "active"
            icon = str(i + 1)
        else:
            status = "pending"
            icon = str(i + 1)

        st.markdown(f"""
            <div class="progress-step {status}">
                <span class="step-number {status}">{icon}</span>
                <span>{step['name']}</span>
            </div>
        """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


def render_info_box(message: str, box_type: str = "info"):
    """Render a styled info/warning/error box."""
    icon_map = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
    }
    icon = icon_map.get(box_type, "ℹ️")
    st.markdown(f"""
        <div class="{box_type}-box">
            <span class="info-box-icon">{icon}</span>
            {message}
        </div>
    """, unsafe_allow_html=True)


def render_status_badge(status: str, text: Optional[str] = None):
    """Render a status badge."""
    status_lower = status.lower()
    badge_text = text or status.replace("_", " ").title()
    st.markdown(f"""
        <span class="status-badge status-{status_lower}">{badge_text}</span>
    """, unsafe_allow_html=True)


def render_json_viewer(data: Any, title: Optional[str] = None):
    """Render JSON data in a formatted viewer."""
    if title:
        st.markdown(f"**{title}**")
    formatted_json = json.dumps(data, indent=2, default=str)
    st.code(formatted_json, language="json")
