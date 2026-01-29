"""
Extraction functions for the catalog library.

This module contains:
- Building extraction plans from catalog plans
- Scraping sample data
- Full data extraction
- Sample analysis and field fixing
"""

import re

from bs4 import BeautifulSoup

from catalog.types import (
    CatalogPlan,
    ExtractionPlan,
    SampleResult,
    Decision,
    DecisionType,
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

    for level_schema in plan.schema_chain:
        level_num = level_schema.level
        level_name = level_schema.catalog_type or f"level_{level_num}"

        # Convert fields to the right format
        level_fields = []
        for field in level_schema.fields:
            level_fields.append(
                Field(
                    name=field.name,
                    type=field.type,
                    container_selector=field.container_selector,
                    selector=field.selector,
                    attribute=field.attribute,
                )
            )

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

    # Build field name mapping: "level_name:original_name" -> merged_name
    field_name_mapping = {}
    for field in plan.fields:
        if field.source_level and field.original_name:
            key = f"{field.source_level}:{field.original_name}"
            field_name_mapping[key] = field.name

    # Build summary
    level_names = [lp.catalog_type or f"Level {lp.level}" for lp in navigation_path]
    path_description = " -> ".join(level_names)

    return ExtractionPlan(
        root_url=plan.root_url,
        navigation_path=navigation_path,
        fields=plan.fields.copy(),
        field_name_mapping=field_name_mapping,
        final_field_names=[f.name for f in plan.fields],
        summary={
            "path": path_description,
            "depth": len(navigation_path),
            "total_fields": len(plan.fields),
            "item_name": plan.item_name,
        },
    )


# -------------------------
# Field Extraction
# -------------------------


def _extract_field_value(
    soup_or_element, field: dict | Field, fallback_container=None
) -> str | None:
    """
    Extract a field value using container_selector and selector.

    Args:
        soup_or_element: BeautifulSoup soup object or element to search within
        field: Field definition with 'container_selector', 'selector', and 'attribute' keys
        fallback_container: Element to use if field has no container_selector

    Returns:
        Extracted value or None
    """
    # Handle both Field objects and dicts
    if isinstance(field, Field):
        container_selector = field.container_selector
        selector = field.selector
        attribute = field.attribute or "text"
    else:
        container_selector = field.get("container_selector")
        selector = field.get("selector")
        attribute = field.get("attribute", "text")

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
    html: str, level_plan: LevelPlan | dict, base_url: str, field_name_mapping: dict | None = None
) -> list[dict]:
    """
    Extract all items from a page using the level's extraction plan.

    Args:
        html: The HTML content
        level_plan: The level's plan with item_container_selector and fields
        base_url: Base URL for resolving relative links
        field_name_mapping: Maps "level_name:original_name" -> merged_name

    Returns:
        List of dicts, each with 'fields' (extracted values with merged names) and 'drill_url' (if applicable)
    """
    soup = BeautifulSoup(html, "html.parser")

    # Handle both LevelPlan objects and dicts
    if isinstance(level_plan, LevelPlan):
        item_selector = level_plan.item_container_selector
        fields = level_plan.fields
        drill_selector = level_plan.drill_down_link_selector
        is_final = level_plan.is_final_level
        level_name = level_plan.level_name or level_plan.catalog_type or f"level_{level_plan.level}"
    else:
        item_selector = level_plan.get("item_container_selector")
        fields = level_plan.get("fields", [])
        drill_selector = level_plan.get("drill_down_link_selector")
        is_final = level_plan.get("is_final_level", True)
        level_name = level_plan.get("level_name") or level_plan.get("catalog_type") or f"level_{level_plan.get('level', 1)}"

    if not item_selector:
        return []

    try:
        items = soup.select(item_selector)
    except Exception:
        return []

    results = []

    for item in items:
        # Extract field values
        row = {}
        for field in fields:
            if isinstance(field, Field):
                original_name = field.name
            else:
                original_name = field.get("name")

            value = _extract_field_value(soup, field, fallback_container=item)

            # Map to merged field name if mapping exists
            if field_name_mapping:
                mapping_key = f"{level_name}:{original_name}"
                merged_name = field_name_mapping.get(mapping_key, original_name)
            else:
                merged_name = original_name

            row[merged_name] = value

        # Extract drill-down URL if not final level
        drill_url = None
        if not is_final:
            # First check if the item itself is a link
            if item.name == "a" and item.get("href"):
                href = item.get("href")
                if href and not href.startswith(("#", "javascript:", "mailto:")):
                    drill_url = resolve_url(base_url, href)

            # If not, try the drill selector
            if not drill_url and drill_selector:
                try:
                    link_el = item.select_one(drill_selector)
                    if link_el:
                        href = link_el.get("href")
                        if href:
                            drill_url = resolve_url(base_url, href)
                except Exception:
                    pass

            # Fallback: find any link in the item
            if not drill_url:
                try:
                    link_el = item.select_one("a[href]")
                    if link_el:
                        href = link_el.get("href")
                        if href and not href.startswith(("#", "javascript:", "mailto:")):
                            drill_url = resolve_url(base_url, href)
                except Exception:
                    pass

        # If there's a 'url' field that's null but we have a drill_url, use the drill_url
        url_field_names = []
        for f in fields:
            fname = f.name if isinstance(f, Field) else f.get("name")
            if fname:
                url_field_names.append(fname)

        if drill_url and row.get("url") is None and "url" in url_field_names:
            row["url"] = drill_url

        results.append({"fields": row, "drill_url": drill_url})

    return results


# -------------------------
# Scraping Functions
# -------------------------


def _scrape_level(
    extraction_plan: ExtractionPlan | dict,
    target_level: int,
    current_level: int = 1,
    current_url: str | None = None,
    parent_context: dict | None = None,
    max_items_per_level: int | None = None,
    max_total_rows: int | None = None,
    rows_collected: list | None = None,
    on_progress=None,
) -> list[dict]:
    """
    Recursively scrape data from level 1 to target_level.

    This function traverses the catalog hierarchy, collecting fields from each level.
    Parent-level fields are carried forward as context for child items.
    """
    # Handle both ExtractionPlan objects and dicts
    if isinstance(extraction_plan, ExtractionPlan):
        navigation_path = extraction_plan.navigation_path
        field_name_mapping = extraction_plan.field_name_mapping
    else:
        navigation_path = extraction_plan.get("navigation_path", [])
        field_name_mapping = extraction_plan.get("field_name_mapping", {})

    # Initialize rows_collected tracker on first call
    if rows_collected is None:
        rows_collected = []

    # Check if we've already collected enough rows
    if max_total_rows is not None and len(rows_collected) >= max_total_rows:
        return []

    # Find current level plan
    level_plan = None
    for lp in navigation_path:
        lp_level = lp.level if isinstance(lp, LevelPlan) else lp.get("level")
        if lp_level == current_level:
            level_plan = lp
            break

    if not level_plan:
        if on_progress:
            on_progress("Error", f"Level {current_level} not found in extraction plan")
        return []

    # Determine URL to scrape
    if isinstance(level_plan, LevelPlan):
        url = current_url or level_plan.sample_url
        item_selector = level_plan.item_container_selector
        level_type = level_plan.catalog_type or f"Level {current_level}"
    else:
        url = current_url or level_plan.get("sample_url")
        item_selector = level_plan.get("item_container_selector")
        level_type = level_plan.get("catalog_type") or f"Level {current_level}"

    if not url:
        if on_progress:
            on_progress("Error", f"No URL for level {current_level}")
        return []

    # Check for required selectors
    if not item_selector:
        if on_progress:
            on_progress("Warning", f"No item_container_selector for {level_type} - cannot extract items")
        return []

    # Initialize parent context
    if parent_context is None:
        parent_context = {}

    if on_progress:
        short_url = url[:50] + "..." if len(url) > 50 else url
        on_progress(f"Scraping {level_type}", short_url)

    # Fetch and parse the page
    try:
        html = fetch_html(url)
    except Exception as e:
        if on_progress:
            on_progress("Error fetching page", str(e)[:50])
        return []

    # Extract items from this page
    items = _extract_items_from_page(html, level_plan, url, field_name_mapping)

    if not items:
        if on_progress:
            on_progress("Warning", f"No items found with selector: {item_selector[:40] if item_selector else 'N/A'}")
        return []

    # Determine how many items to process
    if max_total_rows is not None:
        remaining = max_total_rows - len(rows_collected)
        if remaining <= 0:
            return []
        items_to_process = items
        if on_progress:
            on_progress(f"Found {len(items)} items", f"need {remaining} more rows")
    elif max_items_per_level is not None:
        items_to_process = items[:max_items_per_level]
        if on_progress:
            on_progress(f"Found {len(items)} items", f"processing up to {max_items_per_level}")
    else:
        items_to_process = items
        if on_progress:
            on_progress(f"Found {len(items)} items", "processing all")

    results = []

    for item in items_to_process:
        # Check if we've collected enough rows
        if max_total_rows is not None and len(rows_collected) >= max_total_rows:
            break

        # Merge parent context with this item's fields
        item_context = {**parent_context, **item["fields"]}

        if current_level >= target_level:
            # We've reached the target level - add this row to results
            results.append(item_context)
            rows_collected.append(item_context)

            if max_total_rows is not None and len(rows_collected) >= max_total_rows:
                if on_progress:
                    on_progress("Target reached", f"{len(rows_collected)} rows collected")
                break
        else:
            # Need to go deeper - follow drill URL
            drill_url = item.get("drill_url")
            if drill_url:
                child_rows = _scrape_level(
                    extraction_plan=extraction_plan,
                    target_level=target_level,
                    current_level=current_level + 1,
                    current_url=drill_url,
                    parent_context=item_context,
                    max_items_per_level=max_items_per_level,
                    max_total_rows=max_total_rows,
                    rows_collected=rows_collected,
                    on_progress=on_progress,
                )
                results.extend(child_rows)
            else:
                if on_progress and current_level < target_level:
                    on_progress("Warning", f"No drill-down URL found, stopping at level {current_level}")
                results.append(item_context)
                rows_collected.append(item_context)

                if max_total_rows is not None and len(rows_collected) >= max_total_rows:
                    break

    return results


def scrape_sample(
    extraction_plan: ExtractionPlan | dict,
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
    # Handle both ExtractionPlan objects and dicts
    if isinstance(extraction_plan, ExtractionPlan):
        navigation_path = extraction_plan.navigation_path
        field_name_mapping = extraction_plan.field_name_mapping
        final_field_names = extraction_plan.final_field_names
    else:
        navigation_path = extraction_plan.get("navigation_path", [])
        field_name_mapping = extraction_plan.get("field_name_mapping", {})
        final_field_names = extraction_plan.get("final_field_names", [])

    if not navigation_path:
        return SampleResult(
            rows=[],
            field_names=[],
            target_level=target_level or 1,
            errors=["No navigation path in extraction plan"],
        )

    # Default to deepest level
    max_level = max(
        lp.level if isinstance(lp, LevelPlan) else lp.get("level", 1)
        for lp in navigation_path
    )
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

    # Filter to only fields from levels up to target_level
    fields_from_target_levels = set()
    for lp in navigation_path:
        lp_level = lp.level if isinstance(lp, LevelPlan) else lp.get("level")
        if lp_level <= target_level:
            level_name = (
                (lp.level_name or lp.catalog_type or f"level_{lp.level}")
                if isinstance(lp, LevelPlan)
                else (lp.get("level_name") or lp.get("catalog_type") or f"level_{lp.get('level')}")
            )
            fields = lp.fields if isinstance(lp, LevelPlan) else lp.get("fields", [])
            for field in fields:
                original_name = field.name if isinstance(field, Field) else field.get("name")
                mapping_key = f"{level_name}:{original_name}"
                merged_name = field_name_mapping.get(mapping_key, original_name)
                if merged_name:
                    fields_from_target_levels.add(merged_name)

    # Final field names
    field_names = [f for f in final_field_names if f in fields_from_target_levels]

    # Check if any level is missing selectors
    missing_selectors = []
    for lp in navigation_path:
        lp_level = lp.level if isinstance(lp, LevelPlan) else lp.get("level")
        item_selector = (
            lp.item_container_selector
            if isinstance(lp, LevelPlan)
            else lp.get("item_container_selector")
        )
        if lp_level <= target_level and not item_selector:
            level_name = (
                (lp.catalog_type or f"Level {lp.level}")
                if isinstance(lp, LevelPlan)
                else (lp.get("catalog_type") or f"Level {lp.get('level')}")
            )
            missing_selectors.append(level_name)

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

    # Filter rows to only include fields in final_field_names
    field_names_set = set(field_names)
    filtered_rows = []
    for row in rows:
        filtered_row = {k: v for k, v in row.items() if k in field_names_set}
        filtered_rows.append(filtered_row)

    if on_progress:
        on_progress("Scraping complete", f"{len(filtered_rows)} rows collected")

    return SampleResult(
        rows=filtered_rows,
        field_names=field_names,
        target_level=target_level,
        errors=[],
    )


def scrape_all(
    extraction_plan: ExtractionPlan | dict,
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
        type=DecisionType.FIX_FIELD,
        prompt="Some fields may have incorrect selectors. Would you like to fix them?",
        options=["fix", "skip"],
        context={
            "issues": issues,
            "field_names": sample.field_names,
            "sample_rows": sample.rows[:3],
        },
    )


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
    # Update field in extraction_plan.fields
    for field in extraction_plan.fields:
        if field.name == field_name:
            if fix.get("container_selector") is not None:
                field.container_selector = fix["container_selector"]
            if fix.get("selector") is not None:
                field.selector = fix["selector"]
            if fix.get("attribute") is not None:
                field.attribute = fix["attribute"]
            break

    # Also update in navigation_path
    for level_plan in extraction_plan.navigation_path:
        for field in level_plan.fields:
            if field.name == field_name:
                if fix.get("container_selector") is not None:
                    field.container_selector = fix["container_selector"]
                if fix.get("selector") is not None:
                    field.selector = fix["selector"]
                if fix.get("attribute") is not None:
                    field.attribute = fix["attribute"]
                break

    return extraction_plan
