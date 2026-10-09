"""
Extraction functions for the catalog library.

This module contains:
- Building extraction plans from catalog plans
- Scraping sample data
- Full data extraction
- Sample analysis and field fixing
"""

import re
import traceback

from bs4 import BeautifulSoup

from catalog.types import (
    CatalogPlan,
    ExtractionPlan,
    SampleResult,
    Decision,
    DecisionType,
    DecisionId,
    DecisionStep,
    Field,
    LevelPlan,
)
from catalog.util import fetch_html, resolve_url


# -------------------------
# Extraction Plan Building
# -------------------------


def build_extraction_plan(plan: CatalogPlan) -> ExtractionPlan:
    """
    Build an extraction plan from a CatalogPlan.

    The extraction plan contains all the information needed to scrape the catalog,
    including navigation path and field selectors.

    Args:
        plan: The CatalogPlan to build from

    Returns:
        ExtractionPlan ready for scraping
    """
    navigation_path = []
    total_levels = len(plan.schema_chain)

    all_fields = []

    for level_schema in plan.schema_chain:
        level_num = level_schema.level
        level_name = level_schema.catalog_type or f"level_{level_num}"

        # Convert fields to the right format
        level_fields = []
        for field in level_schema.fields:
            f = Field(
                name=field.name,
                type=field.type,
                container_selector=field.container_selector,
                selector=field.selector,
                attribute=field.attribute,
            )
            level_fields.append(f)
            all_fields.append(f)

        # Determine drill-down selector from nesting analysis
        drill_selector = None
        if level_schema.nesting_analysis:
            drill_selector = level_schema.nesting_analysis.get("drill_down_link_selector")

        level_plan = LevelPlan(
            level=level_num,
            level_name=level_name,
            sample_url=level_schema.url,
            catalog_type=level_schema.catalog_type,
            item_name=level_schema.item_name,
            item_container_selector=level_schema.item_container_selector,
            is_final_level=(level_num == total_levels),
            drill_down_link_selector=drill_selector,
            fields=level_fields,
        )

        navigation_path.append(level_plan)

    # Build summary
    level_names = [lp.catalog_type or f"Level {lp.level}" for lp in navigation_path]
    path_description = " -> ".join(level_names)

    return ExtractionPlan(
        root_url=plan.root_url,
        navigation_path=navigation_path,
        fields=all_fields,
        summary={
            "path": path_description,
            "depth": len(navigation_path),
            "total_fields": len(all_fields),
            "item_name": plan.item_name,
        },
    )


# -------------------------
# Field Extraction
# -------------------------


def _extract_field_value(
    soup_or_element, field: Field, fallback_container=None
) -> str | None:
    """
    Extract a field value using container_selector and selector.

    Args:
        soup_or_element: BeautifulSoup soup object or element to search within
        field: Field definition with container_selector, selector, and attribute
        fallback_container: Element to use if field has no container_selector

    Returns:
        Extracted value or None
    """
    container_selector = field.container_selector
    selector = field.selector
    attribute = field.attribute or "text"

    if not selector:
        return None

    try:
        # Determine the container to search within
        if container_selector:
            container = soup_or_element.select_one(container_selector)
            if not container:
                return None
        elif fallback_container is not None:
            container = fallback_container
        else:
            container = soup_or_element

        # Find the field element within the container
        element = container.select_one(selector)
        if element:
            if attribute == "text":
                value = " ".join(element.stripped_strings)
                value = re.sub(r"\s+", " ", value).strip()
            else:
                value = element.get(attribute)
            return value
    except Exception:
        pass

    return None


def _extract_items_from_page(
    html: str, level_plan: LevelPlan, base_url: str
) -> list[dict]:
    """
    Extract all items from a page using the level's extraction plan.

    Args:
        html: The HTML content
        level_plan: The level's plan with item_container_selector and fields
        base_url: Base URL for resolving relative links

    Returns:
        List of dicts, each with 'fields' (extracted values) and 'drill_url' (if applicable)
    """
    soup = BeautifulSoup(html, "html.parser")

    if not level_plan.item_container_selector:
        return []

    try:
        items = soup.select(level_plan.item_container_selector)
    except Exception:
        traceback.print_exc()
        return []

    results = []

    for item in items:
        # Extract field values
        row = {}
        for f in level_plan.fields:
            row[f.name] = _extract_field_value(soup, f, fallback_container=item)

        # Extract drill-down URL if not final level
        drill_url = None
        if not level_plan.is_final_level:
            drill_url = _extract_drill_url(item, level_plan.drill_down_link_selector, base_url)

        # If there's a 'url' field that's null but we have a drill_url, use it
        field_names = {f.name for f in level_plan.fields}
        if drill_url and row.get("url") is None and "url" in field_names:
            row["url"] = drill_url

        results.append({"fields": row, "drill_url": drill_url})

    return results


def _extract_drill_url(item, drill_selector: str | None, base_url: str) -> str | None:
    """Extract a drill-down URL from an item element."""
    # First check if the item itself is a link
    if item.name == "a" and item.get("href"):
        href = item.get("href")
        if href and not href.startswith(("#", "javascript:", "mailto:")):
            return resolve_url(base_url, href)

    # Try the drill selector
    if drill_selector:
        try:
            link_el = item.select_one(drill_selector)
            if link_el:
                href = link_el.get("href")
                if href:
                    return resolve_url(base_url, href)
        except Exception:
            traceback.print_exc()

    # Fallback: find any link in the item
    try:
        link_el = item.select_one("a[href]")
        if link_el:
            href = link_el.get("href")
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                return resolve_url(base_url, href)
    except Exception:
        traceback.print_exc()

    return None


# -------------------------
# Scraping Functions
# -------------------------


def _scrape_level(
    extraction_plan: ExtractionPlan,
    target_level: int,
    current_level: int = 1,
    current_url: str | None = None,
    parent_fields: dict | None = None,
    max_total_rows: int | None = None,
    rows_collected: list | None = None,
    on_progress=None,
) -> list[dict]:
    """
    DFS traversal of the catalog hierarchy.

    Descends through all levels, collecting fields at each level. When the
    target depth is reached, all accumulated fields become one row. Then
    backtracks to the parent and drills into the next sibling link.

    Each non-final level page may contain *multiple* drill-down items (e.g. a
    category page listing many products). The function iterates over every
    drill-down link, recursing into each one, until the target row count is met.
    """
    # Find the level plan for the current level
    level_plan = None
    for lp in extraction_plan.navigation_path:
        if lp.level == current_level:
            level_plan = lp
            break

    if not level_plan:
        if on_progress:
            on_progress("Error", f"Level {current_level} not found in extraction plan")
        return []

    # Initialize shared mutable list on first call
    if rows_collected is None:
        rows_collected = []
    if parent_fields is None:
        parent_fields = {}

    url = current_url or level_plan.sample_url
    if not url:
        if on_progress:
            on_progress("Error", f"No URL for level {current_level}")
        return []

    if not level_plan.item_container_selector:
        if on_progress:
            level_type = level_plan.catalog_type or f"Level {current_level}"
            on_progress("Warning", f"No item_container_selector for {level_type}")
        return []

    if on_progress:
        level_type = level_plan.catalog_type or f"Level {current_level}"
        short_url = url[:50] + "..." if len(url) > 50 else url
        on_progress(f"Scraping {level_type}", short_url)

    # Fetch page
    try:
        html = fetch_html(url)
    except Exception as e:
        if on_progress:
            on_progress("Error fetching page", str(e)[:50])
        return []

    # Extract items from this page
    items = _extract_items_from_page(html, level_plan, url)

    if on_progress:
        remaining = (max_total_rows - len(rows_collected)) if max_total_rows else "all"
        on_progress(f"Found {len(items)} items", f"need {remaining} more rows")

    results = []

    for item in items:
        # Check row limit before processing each item
        if max_total_rows is not None and len(rows_collected) >= max_total_rows:
            break

        # Accumulate fields from this level onto parent fields
        accumulated = {**parent_fields, **item["fields"]}

        if current_level >= target_level:
            # Reached target depth — emit a row
            results.append(accumulated)
            rows_collected.append(accumulated)
        else:
            # Not at target depth yet — drill down
            drill_url = item.get("drill_url")
            if drill_url:
                child_rows = _scrape_level(
                    extraction_plan=extraction_plan,
                    target_level=target_level,
                    current_level=current_level + 1,
                    current_url=drill_url,
                    parent_fields=accumulated,
                    max_total_rows=max_total_rows,
                    rows_collected=rows_collected,
                    on_progress=on_progress,
                )
                results.extend(child_rows)
            else:
                # No drill URL available — emit what we have
                if on_progress:
                    on_progress("Warning", f"No drill-down URL at level {current_level}, emitting partial row")
                results.append(accumulated)
                rows_collected.append(accumulated)

    return results


def scrape_sample(
    extraction_plan: ExtractionPlan,
    target_level: int | None = None,
    max_rows: int = 3,
    on_progress=None,
) -> SampleResult:
    """
    Scrape sample data from a catalog using the extraction plan.

    This traverses from level 1 down to the target level, collecting fields
    from all intermediate levels.

    Args:
        extraction_plan: The extraction plan from build_extraction_plan()
        target_level: Deepest level to scrape (defaults to max level in plan)
        max_rows: Stop when exactly this many total rows are collected
        on_progress: Optional callback(step, detail)

    Returns:
        SampleResult with rows, field_names, target_level, and errors
    """
    navigation_path = extraction_plan.navigation_path

    if not navigation_path:
        return SampleResult(
            rows=[],
            field_names=[],
            target_level=target_level or 1,
            errors=["No navigation path in extraction plan"],
        )

    # Default to deepest level
    max_level = max(lp.level for lp in navigation_path)
    if target_level is None:
        target_level = max_level

    # Validate target level
    if target_level < 1 or target_level > max_level:
        return SampleResult(
            rows=[],
            field_names=[],
            target_level=target_level,
            errors=[f"Invalid target level {target_level}. Valid range: 1-{max_level}"],
        )

    if on_progress:
        on_progress("Starting hierarchical scrape", f"levels 1-{target_level}, target: {max_rows} rows")

    # Build field_names from levels up to target_level
    field_names = []
    seen = set()
    for lp in navigation_path:
        if lp.level <= target_level:
            for f in lp.fields:
                if f.name and f.name not in seen:
                    field_names.append(f.name)
                    seen.add(f.name)

    # Check if any level is missing selectors
    missing_selectors = []
    for lp in navigation_path:
        if lp.level <= target_level and not lp.item_container_selector:
            missing_selectors.append(lp.catalog_type or f"Level {lp.level}")

    if missing_selectors:
        return SampleResult(
            rows=[],
            field_names=field_names,
            target_level=target_level,
            errors=[
                f"Missing item_container_selector for: {', '.join(missing_selectors)}",
                "Please re-run discovery to generate CSS selectors",
            ],
        )

    # Perform the hierarchical scrape
    try:
        rows = _scrape_level(
            extraction_plan=extraction_plan,
            target_level=target_level,
            max_total_rows=max_rows,
            on_progress=on_progress,
        )
    except Exception as e:
        return SampleResult(
            rows=[],
            field_names=field_names,
            target_level=target_level,
            errors=[f"Scraping error: {str(e)}"],
        )

    if on_progress:
        on_progress("Scraping complete", f"{len(rows)} rows collected")

    return SampleResult(
        rows=rows,
        field_names=field_names,
        target_level=target_level,
        errors=[],
    )


def scrape_all(
    extraction_plan: ExtractionPlan,
    target_level: int | None = None,
    max_rows: int | None = None,
    on_progress=None,
) -> list[dict]:
    """
    Scrape all data from a catalog using the extraction plan.

    Args:
        extraction_plan: The extraction plan
        target_level: Deepest level to scrape (defaults to max)
        max_rows: Optional limit on total rows
        on_progress: Optional callback

    Returns:
        List of dicts with extracted data
    """
    result = scrape_sample(
        extraction_plan=extraction_plan,
        target_level=target_level,
        max_rows=max_rows or 10000,  # Use a high default
        on_progress=on_progress,
    )
    return result.rows


# -------------------------
# Sample Analysis
# -------------------------


def analyze_sample(
    sample: SampleResult,
    extraction_plan: ExtractionPlan,
) -> Decision | None:
    """
    Analyze sample data and return a Decision if there are issues to fix.

    Args:
        sample: The sample scrape result
        extraction_plan: The current extraction plan

    Returns:
        Decision requesting field fixes, or None if data looks good
    """
    issues = []

    # Check for empty rows
    if not sample.rows:
        issues.append("No data extracted")

    # Check for fields with mostly null values
    if sample.rows:
        for field_name in sample.field_names:
            null_count = sum(1 for row in sample.rows if not row.get(field_name))
            if null_count == len(sample.rows):
                issues.append(f"Field '{field_name}' is empty in all rows")
            elif null_count > len(sample.rows) * 0.5:
                issues.append(f"Field '{field_name}' is empty in {null_count}/{len(sample.rows)} rows")

    if not issues:
        return None

    return Decision(
        id=DecisionId.FIX_FIELD,
        type=DecisionType.FIX_FIELD,
        step=DecisionStep.SAMPLE_ANALYSIS,
        prompt="Some fields may have incorrect selectors. Would you like to fix them?",
        options=["fix", "skip"],
        context={
            "issues": issues,
            "field_names": sample.field_names,
            "sample_rows": sample.rows[:3],
        },
    )


def find_field_in_plan(
    extraction_plan: ExtractionPlan,
    field_name: str,
) -> tuple[LevelPlan | None, Field | None]:
    """
    Find a field in the extraction plan by name.

    Args:
        extraction_plan: The extraction plan to search
        field_name: The field name to find

    Returns:
        Tuple of (LevelPlan, Field) where the field was found, or (None, None) if not found
    """
    for level_plan in extraction_plan.navigation_path:
        for field in level_plan.fields:
            if field.name == field_name:
                return level_plan, field

    return None, None


def prepare_field_correction(
    extraction_plan: ExtractionPlan,
    field_name: str,
    expected_value: str,
    html: str,
    on_progress=None,
) -> dict | None:
    """
    Prepare context for correcting a field selector.

    This is a convenience function that:
    1. Finds the field in the extraction plan
    2. Summarizes the DOM
    3. Searches for the expected value in the HTML

    Args:
        extraction_plan: The extraction plan
        field_name: Name of the field to correct
        expected_value: The value the user expects to see
        html: The HTML content of the page
        on_progress: Optional callback

    Returns:
        Dict with field_info, level_plan, dom_summary, found_elements, or None if field not found
    """
    from catalog.schema import summarize_dom, find_value_in_html

    # Find the field
    level_plan, field_info = find_field_in_plan(extraction_plan, field_name)
    if not level_plan or not field_info:
        return None

    # Summarize DOM
    if on_progress:
        on_progress("Analyzing page structure", "")
    dom_summary = summarize_dom(html, on_progress=on_progress)

    # Search for expected value
    if on_progress:
        on_progress("Searching for expected value", expected_value[:30])
    found_elements = find_value_in_html(html, expected_value)

    return {
        "field_info": field_info,
        "level_plan": level_plan,
        "dom_summary": dom_summary,
        "found_elements": found_elements,
        "item_container_selector": level_plan.item_container_selector or "",
    }


def apply_field_fix(
    extraction_plan: ExtractionPlan,
    field_name: str,
    fix: dict,
) -> ExtractionPlan:
    """
    Apply a field selector fix to the extraction plan.

    Args:
        extraction_plan: The current extraction plan
        field_name: Name of the field to fix
        fix: Dict with 'container_selector', 'selector', 'attribute'

    Returns:
        Updated ExtractionPlan
    """
    for level_plan in extraction_plan.navigation_path:
        for field in level_plan.fields:
            if field.name == field_name:
                if fix.get("container_selector") is not None:
                    field.container_selector = fix["container_selector"]
                if fix.get("selector") is not None:
                    field.selector = fix["selector"]
                if fix.get("attribute") is not None:
                    field.attribute = fix["attribute"]
                return extraction_plan

    return extraction_plan
