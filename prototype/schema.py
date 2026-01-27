"""
Schema inference and manipulation functions.
These are the core backend functions for catalog discovery.
All functions are stateless and suitable for API use.
"""

import re
import json
from collections import Counter
from bs4 import BeautifulSoup

from prototype.util import fetch_html, call_llm, get_resolved_links


# -------------------------
# DOM Summarization
# -------------------------

def summarize_dom(html: str, max_blocks: int = 20, on_progress=None) -> dict:
    """
    Extract repeated DOM patterns and text samples from HTML.
    This is intentionally lossy — we don't want to dump full HTML to the LLM.

    Args:
        html: The HTML content to analyze
        max_blocks: Maximum number of CSS class patterns to extract
        on_progress: Optional callback(step, detail) for progress reporting

    Returns:
        Dict containing title, common_classes, samples, and link_samples
    """
    if on_progress:
        on_progress("Parsing and summarizing DOM structure", "")

    soup = BeautifulSoup(html, "html.parser")

    # Remove noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Find candidate repeated blocks
    elements = soup.find_all(True)
    class_counter = Counter()

    for el in elements:
        classes = el.get("class")
        if classes:
            for c in classes:
                class_counter[c] += 1

    common_classes = [
        c for c, count in class_counter.items()
        if count >= 5
    ][:max_blocks]

    samples = []
    for cls in common_classes:
        nodes = soup.select(f".{cls}")[:3]
        for n in nodes:
            text = " ".join(n.stripped_strings)
            text = re.sub(r"\s+", " ", text)
            samples.append({
                "class": cls,
                "tag": n.name,
                "text_sample": text[:300]
            })

    links = [
        a.get("href")
        for a in soup.find_all("a", href=True)
    ][:20]

    if on_progress:
        on_progress("DOM analysis complete", f"{len(common_classes)} patterns, {len(links)} links")

    return {
        "title": soup.title.string if soup.title else None,
        "common_classes": common_classes,
        "samples": samples,
        "link_samples": links
    }


# -------------------------
# Prompt Builders
# -------------------------

def build_schema_prompt(url: str, dom_summary: dict, is_final_level: bool = False) -> str:
    """Build the prompt for schema inference."""

    if is_final_level:
        # Prompt optimized for detail/final pages
        return f"""
You are an expert web data extraction system.

Your task is to analyze a DETAIL PAGE - a page that shows information about a SINGLE ITEM
(e.g., a product detail page, a movie info page, an article page).

Extract the DESCRIPTIVE FIELDS that characterize this item:
- Title/name of the item
- Description or summary
- Key attributes (price, rating, date, author, director, year, duration, etc.)
- Main image
- Any other factual information about this specific item

DO NOT extract:
- Navigation links to other pages
- Related items or recommendations
- Footer/header content
- Social media links

Output STRICT JSON in the following format:

{{
  "is_catalog": true,
  "catalog_type": "string (what type of item this is, e.g., 'film', 'product', 'article')",
  "confidence": 0.0-1.0,
  "archetype": "detail_page",
  "item_schema": {{
    "item_name": "string (singular name of the item type)",
    "item_container_selector": "CSS selector for the main content container (e.g., 'article', '.product-detail', 'main')",
    "fields": [
      {{
        "name": "string (use descriptive names: title, description, price, rating, director, year, etc.)",
        "type": "string | number | boolean | url | date",
        "required": true | false,
        "description": "string",
        "selector": "CSS selector to find this field, or null if not extractable",
        "attribute": "attribute to extract - 'text' for inner text content, 'href' for links, 'src' for images"
      }}
    ]
  }},
  "reasoning": "short explanation of what item this page describes"
}}

IMPORTANT: Focus on extracting CONTENT fields, not navigation. This is the final detail level.

Page URL:
{url}

Page title:
{dom_summary.get("title")}

Common CSS classes detected:
{dom_summary.get("common_classes")}

DOM samples (class, tag, text):
{json.dumps(dom_summary.get("samples"), indent=2)}

Link samples (for context only, do NOT extract these as fields):
{json.dumps(dom_summary.get("link_samples"), indent=2)}
"""
    else:
        # Prompt for catalog/list pages
        return f"""
You are an expert web data extraction system.

Your task is to analyze a webpage summary and infer whether it represents
a CATALOG (a list of similar objects such as products, movies, articles, books, etc).

If it is a catalog:
- Identify the object type
- Infer a clean, minimal schema for ONE item
- Use generic, reusable field names
- Infer data types
- Prefer universal fields (title, price, author, rating, url, image, etc)
- Do NOT hallucinate fields not strongly suggested by the page
- Identify CSS selectors for extracting the data

If it is NOT a catalog, clearly say so.

Supported catalog archetypes (v1):
- Card grid
- Vertical list
- Table

Output STRICT JSON in the following format:

{{
  "is_catalog": true | false,
  "catalog_type": "string | null",
  "confidence": 0.0-1.0,
  "archetype": "card_grid | list | table | unknown",
  "item_schema": {{
    "item_name": "string",
    "item_container_selector": "CSS selector to find each repeated item container",
    "fields": [
      {{
        "name": "string",
        "type": "string | number | boolean | url | date",
        "required": true | false,
        "description": "string",
        "selector": "CSS selector relative to item container, or null if not extractable",
        "attribute": "attribute to extract (e.g., 'href', 'src', 'text') - use 'text' for inner text content"
      }}
    ]
  }},
  "reasoning": "short explanation"
}}

SELECTOR GUIDELINES:
- item_container_selector: CSS selector that matches ALL repeated items on the page (e.g., ".product-card", "tr.item-row", ".listing")
- field selector: CSS selector RELATIVE to the item container (e.g., ".title", "a.link", "img.thumbnail")
- attribute: what to extract - "text" for inner text content, "href" for links, "src" for images, or any HTML attribute
- Use the common CSS classes provided below to identify the right selectors
- If a field cannot be reliably selected, set selector to null

DO NOT include markdown.
DO NOT include extra commentary.

Page URL:
{url}

Page title:
{dom_summary.get("title")}

Common CSS classes detected:
{dom_summary.get("common_classes")}

DOM samples (class, tag, text):
{json.dumps(dom_summary.get("samples"), indent=2)}

Link samples:
{json.dumps(dom_summary.get("link_samples"), indent=2)}
"""


def build_nesting_analysis_prompt(url: str, dom_summary: dict, schema: dict, link_samples: list) -> str:
    """Build the prompt for nesting analysis."""
    # Build numbered list of links for clarity
    numbered_links = "\n".join([f"  {i}: {link}" for i, link in enumerate(link_samples)])

    return f"""
You are an expert web structure analyzer.

You are analyzing a catalog page to determine if it contains NESTED content that should be explored further.

NESTING EXAMPLES:
- A "Categories" page linking to individual category pages (each with their own item lists)
- A "Departments" page linking to sub-departments
- A product listing linking to product detail pages
- An index page linking to sub-sections

YOUR TASK:
1. Determine if this is a FINAL DETAIL PAGE (no further meaningful nesting) or an INTERMEDIATE PAGE (links to deeper content)
2. If intermediate, identify the BEST link to follow to reach the actual item details
3. If intermediate, identify the CSS selector pattern to find ALL similar drill-down links

A page is a FINAL DETAIL PAGE if:
- It shows individual item details (product specs, article content, movie info, etc.)
- The links mostly lead to unrelated pages, navigation, or external sites
- There's no clear "drill down" pattern

A page is an INTERMEDIATE PAGE if:
- Items are categories, sections, or groups that contain more items
- Links clearly lead to more specific content within the same domain
- There's a hierarchical structure to explore

CURRENT PAGE INFO:
URL: {url}
Title: {dom_summary.get("title")}
Detected catalog type: {schema.get("catalog_type")}
Item name: {schema.get("item_schema", {}).get("item_name", "unknown")}
Item container selector: {schema.get("item_schema", {}).get("item_container_selector", "unknown")}

Common CSS classes on this page:
{dom_summary.get("common_classes")}

Available links on this page (INDEX: URL):
{numbered_links}

Output STRICT JSON:
{{
  "is_final_level": true | false,
  "reasoning": "why this is/isn't the final level",
  "recommended_link_index": null | <index number from the list above>,
  "recommended_link_reason": "why this link is the best choice to explore deeper",
  "drill_down_link_selector": "CSS selector to find ALL drill-down links within item containers, or null if final level"
}}

SELECTOR GUIDELINES:
- drill_down_link_selector should be relative to the item container (e.g., "a.item-link", "a[href]", ".title a")
- This selector will be used to find the link to follow for EACH item in the catalog
- If is_final_level is true, set drill_down_link_selector to null

IMPORTANT: recommended_link_index must be the exact index number from the list above (0, 1, 2, etc.)

If is_final_level is true, set recommended_link_index to null.
If is_final_level is false, you MUST provide a valid index number from the list.

DO NOT include markdown.
DO NOT include extra commentary.
"""


# -------------------------
# Schema Inference (Single Page)
# -------------------------

def infer_schema(url: str, dom_summary: dict, on_progress=None, is_final_level: bool = False) -> dict:
    """
    Infer catalog schema from DOM summary.

    Args:
        url: The page URL
        dom_summary: DOM summary from summarize_dom()
        on_progress: Optional callback(step, detail) for progress reporting
        is_final_level: If True, uses detail-page optimized prompt to extract descriptive fields

    Returns:
        Schema dict with is_catalog, catalog_type, confidence, archetype, item_schema, reasoning
    """
    prompt = build_schema_prompt(url, dom_summary, is_final_level=is_final_level)
    return call_llm(prompt, "schema inference", on_progress)


def analyze_nesting(url: str, dom_summary: dict, schema: dict, link_samples: list, on_progress=None) -> dict:
    """
    Analyze if page has nested content and recommend next link.

    Args:
        url: The page URL
        dom_summary: DOM summary from summarize_dom()
        schema: Schema from infer_schema()
        link_samples: List of resolved URLs to consider
        on_progress: Optional callback(step, detail) for progress reporting

    Returns:
        Dict with is_final_level, reasoning, recommended_link_index, recommended_link_reason
    """
    prompt = build_nesting_analysis_prompt(url, dom_summary, schema, link_samples)
    return call_llm(prompt, "nesting detection", on_progress)


# -------------------------
# Field Correction
# -------------------------

def build_field_correction_prompt(
    field_name: str,
    current_selector: str,
    current_attribute: str,
    current_value: str,
    user_feedback: str,
    expected_value: str,
    dom_summary: dict,
    item_container_selector: str
) -> str:
    """Build prompt for correcting a field's selector."""
    return f"""
You are an expert web data extraction system helping to fix an incorrect CSS selector.

A user is trying to extract data from a webpage, but one of the fields is extracting wrong data.

CURRENT EXTRACTION SETUP:
- Field name: {field_name}
- Item container selector: {item_container_selector}
- Field selector (relative to container): {current_selector or "None"}
- Attribute being extracted: {current_attribute}
- Current extracted value: {current_value or "Nothing extracted"}

USER FEEDBACK:
- What's wrong: {user_feedback}
- Expected value (example): {expected_value}

PAGE STRUCTURE:
Common CSS classes detected:
{dom_summary.get("common_classes")}

DOM samples (class, tag, text):
{json.dumps(dom_summary.get("samples"), indent=2)}

YOUR TASK:
Analyze the DOM structure and suggest a CORRECTED selector that will extract the expected value.
The selector should be RELATIVE to the item container.

Output STRICT JSON:
{{
  "corrected_selector": "new CSS selector relative to item container",
  "corrected_attribute": "text | href | src | or other attribute",
  "reasoning": "explanation of why this selector should work",
  "confidence": 0.0-1.0
}}

If you cannot determine a good selector, set corrected_selector to null and explain in reasoning.

DO NOT include markdown.
DO NOT include extra commentary.
"""


def correct_field_selector(
    field_name: str,
    current_selector: str,
    current_attribute: str,
    current_value: str,
    user_feedback: str,
    expected_value: str,
    dom_summary: dict,
    item_container_selector: str,
    on_progress=None
) -> dict:
    """
    Use AI to correct a field's selector based on user feedback.

    Args:
        field_name: Name of the field to correct
        current_selector: Current CSS selector being used
        current_attribute: Current attribute being extracted
        current_value: What's currently being extracted
        user_feedback: User's description of what's wrong
        expected_value: What the user expects to see
        dom_summary: DOM summary from the page
        item_container_selector: The container selector for items
        on_progress: Optional callback

    Returns:
        Dict with corrected_selector, corrected_attribute, reasoning, confidence
    """
    prompt = build_field_correction_prompt(
        field_name=field_name,
        current_selector=current_selector,
        current_attribute=current_attribute,
        current_value=current_value,
        user_feedback=user_feedback,
        expected_value=expected_value,
        dom_summary=dom_summary,
        item_container_selector=item_container_selector
    )
    return call_llm(prompt, f"correcting {field_name} selector", on_progress)


def traverse(url: str, on_progress=None, is_final_level: bool = False) -> dict:
    """
    Traverse a single page and infer its schema.
    This is the main entry point for single-page schema inference.

    Args:
        url: The URL to analyze
        on_progress: Optional callback(step, detail) for progress reporting
        is_final_level: If True, uses detail-page optimized prompt

    Returns:
        Dict containing:
        - url: The analyzed URL
        - schema: The inferred schema
        - dom_summary: The DOM summary
        - link_samples: List of links found on the page
    """
    html = fetch_html(url, on_progress)
    dom_summary = summarize_dom(html, on_progress=on_progress)
    schema = infer_schema(url, dom_summary, on_progress, is_final_level=is_final_level)
    link_samples = dom_summary.get("link_samples", [])

    return {
        "url": url,
        "schema": schema,
        "dom_summary": dom_summary,
        "link_samples": link_samples
    }


# -------------------------
# Schema Merging
# -------------------------

def normalize_level_name(name: str) -> str:
    """Convert a level name to a valid field prefix (snake_case)."""
    if not name:
        return "level"
    # Convert to lowercase and replace spaces/special chars with underscores
    normalized = name.lower()
    normalized = re.sub(r'[^a-z0-9]+', '_', normalized)
    normalized = normalized.strip('_')
    return normalized or "level"


def merge_schemas(schema_chain: list, on_progress=None) -> dict:
    """
    Merge schemas from all nesting levels into a single unified schema.
    Fields with the same name but from different levels are kept separate
    with level-prefixed names.

    Args:
        schema_chain: List of dicts with 'level', 'url', 'schema' keys
        on_progress: Optional callback(step, detail) for progress reporting

    Returns:
        Merged schema dict with item_name, nesting_depth, fields, level_names
    """
    if on_progress:
        on_progress("Merging schemas from all levels", "")

    if not schema_chain:
        return {}

    # First pass: collect all fields with their level info
    all_fields = []
    for level_info in schema_chain:
        level_num = level_info["level"]
        schema = level_info["schema"]
        level_name = schema.get("catalog_type") or f"level_{level_num}"

        item_schema = schema.get("item_schema", {})
        fields = item_schema.get("fields", [])

        for field in fields:
            all_fields.append({
                "field": field,
                "level_num": level_num,
                "level_name": level_name
            })

    # Second pass: identify which field names appear at multiple levels with different meanings
    field_occurrences = {}  # field_name -> list of (level_name, description)
    for entry in all_fields:
        field = entry["field"]
        field_name = field.get("name")
        level_name = entry["level_name"]
        description = field.get("description", "")

        if field_name not in field_occurrences:
            field_occurrences[field_name] = []

        # Check if this level already has this field (same level, same meaning)
        level_exists = any(
            occ["level_name"] == level_name
            for occ in field_occurrences[field_name]
        )
        if not level_exists:
            field_occurrences[field_name].append({
                "level_name": level_name,
                "description": description
            })

    # Identify fields that need prefixing (appear at multiple levels)
    fields_needing_prefix = {
        name for name, occurrences in field_occurrences.items()
        if len(occurrences) > 1
    }

    # Third pass: build merged fields with appropriate naming
    merged_fields = []
    seen_final_names = set()

    for entry in all_fields:
        field = entry["field"]
        level_name = entry["level_name"]
        field_name = field.get("name")

        # Determine the final field name
        if field_name in fields_needing_prefix:
            prefix = normalize_level_name(level_name)
            final_name = f"{prefix}_{field_name}"
        else:
            final_name = field_name

        # Skip if we've already added this exact final name
        if final_name in seen_final_names:
            continue

        seen_final_names.add(final_name)

        merged_field = field.copy()
        merged_field["name"] = final_name
        merged_field["original_name"] = field_name
        merged_field["source_level"] = level_name
        merged_fields.append(merged_field)

    # Use the deepest level's item name as the primary item name
    final_level = schema_chain[-1]
    final_item_name = final_level["schema"].get("item_schema", {}).get("item_name", "Item")

    if on_progress:
        on_progress("Schema merge complete", f"{len(merged_fields)} unique fields")

    return {
        "item_name": final_item_name,
        "nesting_depth": len(schema_chain),
        "fields": merged_fields,
        "level_names": [s["schema"].get("catalog_type", f"level_{s['level']}") for s in schema_chain]
    }


# -------------------------
# Discovery (Multi-Page Traversal)
# -------------------------

def discover(
    start_url: str,
    max_depth: int = 10,
    on_progress=None,
    on_schema_inferred=None,
    select_next_link=None,
    confirm_drilling=None
) -> dict:
    """
    Discover nested catalog structure starting from a URL.
    This is the main entry point for full catalog discovery.

    Args:
        start_url: The root URL to start discovery from
        max_depth: Maximum nesting depth to explore
        on_progress: Optional callback(step, detail) for progress reporting
        on_schema_inferred: Optional callback(level, url, schema) called after each page is analyzed
        select_next_link: Optional callback(url, dom_summary, schema, unvisited_links, visited_urls)
                         that returns (should_continue, next_url, nesting_info).
                         If None, uses automatic LLM-based detection.
        confirm_drilling: Optional callback(nesting_info, recommended_url) for auto mode.
                         Returns: "continue" to proceed, "final" to mark as final level,
                         or "stop" to stop discovery. Only used when select_next_link is None.

    Returns:
        Dict containing:
        - root_url: The starting URL
        - final_url: The deepest URL analyzed
        - schema_chain: List of all schemas at each level
        - merged_schema: The combined schema from all levels
        - visited_urls: Set of all visited URLs
    """
    current_url = start_url
    schema_chain = []
    visited_urls = set()
    level = 1
    mark_as_final = False  # Flag to indicate user confirmed this is final level

    while level <= max_depth:
        # Check for cycles
        if current_url in visited_urls:
            if on_progress:
                on_progress("Warning", f"URL already visited, stopping to avoid cycle")
            break

        visited_urls.add(current_url)

        if on_progress:
            on_progress(f"Level {level}", current_url)

        # Fetch and summarize the page
        html = fetch_html(current_url, on_progress)
        dom_summary = summarize_dom(html, on_progress=on_progress)
        link_samples = dom_summary.get("link_samples", [])

        # Infer schema - use detail-page prompt if marked as final
        schema = infer_schema(current_url, dom_summary, on_progress, is_final_level=mark_as_final)

        level_entry = {
            "level": level,
            "url": current_url,
            "schema": schema,
            "nesting_analysis": None  # Will be populated if we analyze nesting
        }
        schema_chain.append(level_entry)

        # Notify about inferred schema
        if on_schema_inferred:
            on_schema_inferred(level, current_url, schema)

        # If this was marked as final, stop here
        if mark_as_final:
            if on_progress:
                on_progress("Final level confirmed", "discovery complete")
            break

        # Check if this is a catalog at all
        if not schema.get("is_catalog"):
            if on_progress:
                on_progress("Not a catalog page", "stopping discovery")
            break

        # Get resolved links and filter visited
        resolved_links = get_resolved_links(current_url, link_samples)
        unvisited_links = [link for link in resolved_links if link not in visited_urls]

        if not unvisited_links:
            if on_progress:
                on_progress("No unvisited links", "treating as final level")
            break

        # Determine next URL to visit
        if select_next_link:
            # Use provided callback (for interactive mode)
            should_continue, next_url, nesting_info = select_next_link(
                current_url, dom_summary, schema, unvisited_links, visited_urls
            )
            level_entry["nesting_analysis"] = nesting_info

            # Check if user marked this as final
            if nesting_info and nesting_info.get("user_confirmed_final"):
                mark_as_final = True
                # Re-analyze current page with detail-page prompt
                schema = infer_schema(current_url, dom_summary, on_progress, is_final_level=True)
                level_entry["schema"] = schema
                if on_schema_inferred:
                    on_schema_inferred(level, current_url, schema)
                if on_progress:
                    on_progress("Final level confirmed", "discovery complete")
                break
        else:
            # Use automatic LLM-based detection
            should_continue, next_url, nesting_info = _auto_select_next_link(
                current_url, dom_summary, schema, unvisited_links, on_progress
            )
            level_entry["nesting_analysis"] = nesting_info

            # If we have a confirm_drilling callback, ask user for confirmation
            if confirm_drilling and not nesting_info.get("is_final_level", True):
                user_decision = confirm_drilling(nesting_info, next_url)

                if user_decision == "final":
                    # User says this is the final level - re-analyze with detail prompt
                    mark_as_final = True
                    schema = infer_schema(current_url, dom_summary, on_progress, is_final_level=True)
                    level_entry["schema"] = schema
                    nesting_info["is_final_level"] = True
                    nesting_info["user_confirmed_final"] = True
                    if on_schema_inferred:
                        on_schema_inferred(level, current_url, schema)
                    if on_progress:
                        on_progress("Final level confirmed", "discovery complete")
                    break
                elif user_decision == "stop":
                    if on_progress:
                        on_progress("Discovery stopped by user", "")
                    break
                # else "continue" - proceed as normal

        if not should_continue or not next_url:
            if on_progress:
                on_progress("Reached final level", "discovery complete")
            break

        current_url = next_url
        level += 1

    if level > max_depth and on_progress:
        on_progress("Warning", f"Reached maximum depth ({max_depth})")

    # Merge all schemas
    merged_schema = merge_schemas(schema_chain, on_progress)

    return {
        "root_url": start_url,
        "final_url": schema_chain[-1]["url"] if schema_chain else start_url,
        "schema_chain": schema_chain,
        "merged_schema": merged_schema,
        "visited_urls": list(visited_urls)
    }


# -------------------------
# Extraction Plan Builder
# -------------------------

def build_extraction_plan(discovery_result: dict) -> dict:
    """
    Build an extraction plan from a discovery result.
    The extraction plan contains all the information needed to scrape the catalog.

    Args:
        discovery_result: The result from discover()

    Returns:
        Extraction plan dict with:
        - navigation_path: List of levels with URL patterns and selectors
        - fields: List of fields to extract with their selectors
        - field_name_mapping: Maps (level_name, original_name) -> merged_name
        - summary: Human-readable summary of the plan
    """
    schema_chain = discovery_result.get("schema_chain", [])
    merged_schema = discovery_result.get("merged_schema", {})
    total_levels = len(schema_chain)

    navigation_path = []

    for level_info in schema_chain:
        level_num = level_info["level"]
        url = level_info["url"]
        schema = level_info["schema"]
        nesting_analysis = level_info.get("nesting_analysis")

        item_schema = schema.get("item_schema", {})
        level_name = schema.get("catalog_type") or f"level_{level_num}"

        level_plan = {
            "level": level_num,
            "level_name": level_name,
            "sample_url": url,
            "catalog_type": schema.get("catalog_type"),
            "item_name": item_schema.get("item_name"),
            "item_container_selector": item_schema.get("item_container_selector"),
            "is_final_level": level_num == total_levels,  # Default based on position
            "drill_down_link_selector": None,
            "fields": []
        }

        # Add field extraction info
        for field in item_schema.get("fields", []):
            level_plan["fields"].append({
                "name": field.get("name"),
                "type": field.get("type"),
                "selector": field.get("selector"),
                "attribute": field.get("attribute", "text")
            })

        # Add nesting info if available (overrides default is_final_level)
        if nesting_analysis:
            is_final = nesting_analysis.get("is_final_level", level_num == total_levels)
            level_plan["is_final_level"] = is_final
            level_plan["drill_down_link_selector"] = nesting_analysis.get("drill_down_link_selector")

        navigation_path.append(level_plan)

    # Build summary
    level_names = [p.get("catalog_type") or f"Level {p['level']}" for p in navigation_path]
    path_description = " -> ".join(level_names)

    # Build field name mapping: (level_name, original_name) -> merged_name
    # This allows the scraper to map extracted values to the correct merged field names
    field_name_mapping = {}
    for field in merged_schema.get("fields", []):
        source_level = field.get("source_level")
        original_name = field.get("original_name")
        merged_name = field.get("name")
        if source_level and original_name:
            key = f"{source_level}:{original_name}"
            field_name_mapping[key] = merged_name

    # Get fields with selectors from merged schema
    extraction_fields = []
    final_field_names = []  # List of field names in the final merged schema
    for field in merged_schema.get("fields", []):
        field_name = field.get("name")
        final_field_names.append(field_name)
        extraction_fields.append({
            "name": field_name,
            "original_name": field.get("original_name"),
            "type": field.get("type"),
            "source_level": field.get("source_level"),
            "selector": field.get("selector"),
            "attribute": field.get("attribute", "text"),
            "required": field.get("required", False),
            "description": field.get("description")
        })

    return {
        "root_url": discovery_result.get("root_url"),
        "navigation_path": navigation_path,
        "fields": extraction_fields,
        "field_name_mapping": field_name_mapping,
        "final_field_names": final_field_names,  # Authoritative list of fields to extract
        "summary": {
            "path": path_description,
            "depth": len(navigation_path),
            "total_fields": len(extraction_fields),
            "item_name": merged_schema.get("item_name")
        }
    }


def _auto_select_next_link(url: str, dom_summary: dict, schema: dict, unvisited_links: list, on_progress=None) -> tuple:
    """
    Automatically select the next link using LLM analysis.
    Internal function used by discover().

    Returns:
        (should_continue, next_url, nesting_info) tuple
    """
    nesting_result = analyze_nesting(url, dom_summary, schema, unvisited_links, on_progress)

    is_final = nesting_result.get("is_final_level", True)

    if on_progress:
        reasoning = nesting_result.get("reasoning", "")
        on_progress("Nesting analysis", f"Final level: {is_final}")
        if reasoning:
            on_progress("Reason", reasoning)
        drill_selector = nesting_result.get("drill_down_link_selector")
        if drill_selector:
            on_progress("Drill-down selector", drill_selector)

    if is_final:
        return False, None, nesting_result

    link_index = nesting_result.get("recommended_link_index")
    if link_index is None:
        return False, None, nesting_result

    # Ensure link_index is an integer
    try:
        link_index = int(link_index)
    except (TypeError, ValueError):
        if on_progress:
            on_progress("Warning", f"Invalid link index: {link_index}")
        return False, None, nesting_result

    if link_index < 0 or link_index >= len(unvisited_links):
        if on_progress:
            on_progress("Warning", f"Link index {link_index} out of range")
        return False, None, nesting_result

    selected_url = unvisited_links[link_index]

    if on_progress:
        link_reason = nesting_result.get("recommended_link_reason", "")
        on_progress("Drilling deeper", selected_url)
        if link_reason:
            on_progress("Reason", link_reason)

    return True, selected_url, nesting_result
