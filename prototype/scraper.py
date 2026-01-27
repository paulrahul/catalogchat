"""
Scraper module for extracting data from catalogs.
Uses extraction plans to navigate nested catalog structures and extract data.
"""

import re
from bs4 import BeautifulSoup

from prototype.util import fetch_html, resolve_url


def extract_field_value(item_element, field: dict) -> str | None:
    """
    Extract a field value from an item element using selector and attribute.

    Args:
        item_element: BeautifulSoup element for the item container
        field: Field definition with 'selector' and 'attribute' keys

    Returns:
        Extracted value or None
    """
    selector = field.get("selector")
    attribute = field.get("attribute", "text")

    if not selector:
        return None

    try:
        element = item_element.select_one(selector)
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


def extract_items_from_page(html: str, level_plan: dict, base_url: str, field_name_mapping: dict = None) -> list:
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

    item_selector = level_plan.get("item_container_selector")
    if not item_selector:
        return []

    try:
        items = soup.select(item_selector)
    except Exception:
        return []

    results = []
    fields = level_plan.get("fields", [])
    drill_selector = level_plan.get("drill_down_link_selector")
    is_final = level_plan.get("is_final_level", True)
    level_name = level_plan.get("level_name") or level_plan.get("catalog_type") or f"level_{level_plan.get('level', 1)}"

    for item in items:
        # Extract field values
        row = {}
        for field in fields:
            original_name = field.get("name")
            value = extract_field_value(item, field)

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
                if href and not href.startswith(('#', 'javascript:', 'mailto:')):
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
                        if href and not href.startswith(('#', 'javascript:', 'mailto:')):
                            drill_url = resolve_url(base_url, href)
                except Exception:
                    pass

        results.append({
            "fields": row,
            "drill_url": drill_url
        })

    return results


def scrape_level(
    extraction_plan: dict,
    target_level: int,
    current_level: int = 1,
    current_url: str = None,
    parent_context: dict = None,
    max_items_per_level: int = 1,
    on_progress=None
) -> list:
    """
    Recursively scrape data from level 1 to target_level.

    This function traverses the catalog hierarchy, collecting fields from each level.
    Parent-level fields are carried forward as context for child items.

    Args:
        extraction_plan: The full extraction plan
        target_level: The deepest level to scrape (1-indexed)
        current_level: Current level being processed (internal use)
        current_url: URL to scrape (internal use, defaults to level's sample_url)
        parent_context: Fields from parent levels (internal use)
        max_items_per_level: Max items to process per level (for sampling)
        on_progress: Optional callback(step, detail)

    Returns:
        List of dicts, each representing a fully-flattened row with fields from all levels
    """
    navigation_path = extraction_plan.get("navigation_path", [])
    field_name_mapping = extraction_plan.get("field_name_mapping", {})

    # Find current level plan
    level_plan = None
    for lp in navigation_path:
        if lp.get("level") == current_level:
            level_plan = lp
            break

    if not level_plan:
        if on_progress:
            on_progress("Error", f"Level {current_level} not found in extraction plan")
        return []

    # Determine URL to scrape
    url = current_url or level_plan.get("sample_url")
    if not url:
        if on_progress:
            on_progress("Error", f"No URL for level {current_level}")
        return []

    # Check for required selectors
    item_selector = level_plan.get("item_container_selector")
    if not item_selector:
        if on_progress:
            level_name = level_plan.get("catalog_type") or f"Level {current_level}"
            on_progress("Warning", f"No item_container_selector for {level_name} - cannot extract items")
            on_progress("Hint", "Re-run discovery to generate CSS selectors")
        return []

    # Initialize parent context
    if parent_context is None:
        parent_context = {}

    if on_progress:
        level_name = level_plan.get("catalog_type") or f"Level {current_level}"
        short_url = url[:50] + "..." if len(url) > 50 else url
        on_progress(f"Scraping {level_name}", short_url)

    # Fetch and parse the page
    try:
        html = fetch_html(url)
    except Exception as e:
        if on_progress:
            on_progress("Error fetching page", str(e)[:50])
        return []

    # Extract items from this page
    items = extract_items_from_page(html, level_plan, url, field_name_mapping)

    if not items:
        if on_progress:
            on_progress("Warning", f"No items found with selector: {item_selector[:40]}")
        return []

    if on_progress:
        on_progress(f"Found {len(items)} items", f"processing up to {max_items_per_level}")

    # Limit items for sampling
    items = items[:max_items_per_level]

    results = []

    for item in items:
        # Merge parent context with this item's fields
        item_context = {**parent_context, **item["fields"]}

        if current_level >= target_level:
            # We've reached the target level - add this row to results
            results.append(item_context)
        else:
            # Need to go deeper - follow drill URL
            drill_url = item.get("drill_url")
            if drill_url:
                # Recursively scrape child level
                child_rows = scrape_level(
                    extraction_plan=extraction_plan,
                    target_level=target_level,
                    current_level=current_level + 1,
                    current_url=drill_url,
                    parent_context=item_context,
                    max_items_per_level=max_items_per_level,
                    on_progress=on_progress
                )
                results.extend(child_rows)
            else:
                # No drill URL available - log warning and return what we have
                if on_progress and current_level < target_level:
                    on_progress("Warning", f"No drill-down URL found, stopping at level {current_level}")
                results.append(item_context)

    return results


def scrape_sample(
    extraction_plan: dict,
    target_level: int = None,
    max_items_per_level: int = 1,
    on_progress=None
) -> dict:
    """
    Scrape sample data from a catalog using the extraction plan.

    This traverses from level 1 down to the target level, collecting fields
    from all intermediate levels. Parent-level fields provide context/grouping
    for child-level data.

    Args:
        extraction_plan: The extraction plan from build_extraction_plan()
        target_level: Deepest level to scrape (defaults to max level in plan)
        max_items_per_level: Max items to process at each level (default 5)
        on_progress: Optional callback(step, detail)

    Returns:
        Dict containing:
        - rows: List of dicts with all extracted field values (using merged names)
        - field_names: List of field names in order (merged names from all levels)
        - target_level: The level that was targeted
        - errors: List of any errors encountered
    """
    navigation_path = extraction_plan.get("navigation_path", [])
    field_name_mapping = extraction_plan.get("field_name_mapping", {})

    if not navigation_path:
        return {
            "rows": [],
            "field_names": [],
            "target_level": target_level,
            "errors": ["No navigation path in extraction plan"]
        }

    # Default to deepest level
    max_level = max(lp.get("level", 1) for lp in navigation_path)
    if target_level is None:
        target_level = max_level

    # Validate target level
    if target_level < 1 or target_level > max_level:
        return {
            "rows": [],
            "field_names": [],
            "target_level": target_level,
            "errors": [f"Invalid target level {target_level}. Valid range: 1-{max_level}"]
        }

    if on_progress:
        on_progress("Starting hierarchical scrape", f"levels 1-{target_level}")

    # Use final_field_names from extraction plan as the authoritative list
    # This ensures we only return fields that are in the merged schema
    all_final_fields = extraction_plan.get("final_field_names", [])

    # Filter to only fields from levels up to target_level
    # Build a set of field names that come from levels we're scraping
    fields_from_target_levels = set()
    for lp in navigation_path:
        if lp.get("level") <= target_level:
            level_name = lp.get("level_name") or lp.get("catalog_type") or f"level_{lp.get('level')}"
            for field in lp.get("fields", []):
                original_name = field.get("name")
                # Map to merged name
                mapping_key = f"{level_name}:{original_name}"
                merged_name = field_name_mapping.get(mapping_key, original_name)
                if merged_name:
                    fields_from_target_levels.add(merged_name)

    # Final field names = intersection of (fields in merged schema) AND (fields from target levels)
    field_names = [f for f in all_final_fields if f in fields_from_target_levels]

    # Check if any level is missing selectors
    missing_selectors = []
    for lp in navigation_path:
        if lp.get("level") <= target_level:
            if not lp.get("item_container_selector"):
                level_name = lp.get("catalog_type") or f"Level {lp.get('level')}"
                missing_selectors.append(level_name)

    if missing_selectors:
        return {
            "rows": [],
            "field_names": field_names,
            "target_level": target_level,
            "errors": [
                f"Missing item_container_selector for: {', '.join(missing_selectors)}",
                "Please re-run discovery to generate CSS selectors"
            ]
        }

    # Perform the hierarchical scrape
    try:
        rows = scrape_level(
            extraction_plan=extraction_plan,
            target_level=target_level,
            max_items_per_level=max_items_per_level,
            on_progress=on_progress
        )
    except Exception as e:
        return {
            "rows": [],
            "field_names": field_names,
            "target_level": target_level,
            "errors": [f"Scraping error: {str(e)}"]
        }

    # Filter rows to only include fields in final_field_names
    # This removes any fields that were extracted but aren't in the merged schema
    filtered_rows = []
    field_names_set = set(field_names)
    for row in rows:
        filtered_row = {k: v for k, v in row.items() if k in field_names_set}
        filtered_rows.append(filtered_row)

    if on_progress:
        on_progress("Scraping complete", f"{len(filtered_rows)} rows collected")

    return {
        "rows": filtered_rows,
        "field_names": field_names,
        "target_level": target_level,
        "errors": []
    }
