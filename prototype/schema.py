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

def build_schema_prompt(url: str, dom_summary: dict) -> str:
    """Build the prompt for schema inference."""
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
    "fields": [
      {{
        "name": "string",
        "type": "string | number | boolean | url | date",
        "required": true | false,
        "description": "string"
      }}
    ]
  }},
  "reasoning": "short explanation"
}}

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

Available links on this page (INDEX: URL):
{numbered_links}

Output STRICT JSON:
{{
  "is_final_level": true | false,
  "reasoning": "why this is/isn't the final level",
  "recommended_link_index": null | <index number from the list above>,
  "recommended_link_reason": "why this link is the best choice to explore deeper"
}}

IMPORTANT: recommended_link_index must be the exact index number from the list above (0, 1, 2, etc.)

If is_final_level is true, set recommended_link_index to null.
If is_final_level is false, you MUST provide a valid index number from the list.

DO NOT include markdown.
DO NOT include extra commentary.
"""


# -------------------------
# Schema Inference (Single Page)
# -------------------------

def infer_schema(url: str, dom_summary: dict, on_progress=None) -> dict:
    """
    Infer catalog schema from DOM summary.

    Args:
        url: The page URL
        dom_summary: DOM summary from summarize_dom()
        on_progress: Optional callback(step, detail) for progress reporting

    Returns:
        Schema dict with is_catalog, catalog_type, confidence, archetype, item_schema, reasoning
    """
    prompt = build_schema_prompt(url, dom_summary)
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


def traverse(url: str, on_progress=None) -> dict:
    """
    Traverse a single page and infer its schema.
    This is the main entry point for single-page schema inference.

    Args:
        url: The URL to analyze
        on_progress: Optional callback(step, detail) for progress reporting

    Returns:
        Dict containing:
        - url: The analyzed URL
        - schema: The inferred schema
        - dom_summary: The DOM summary
        - link_samples: List of links found on the page
    """
    html = fetch_html(url, on_progress)
    dom_summary = summarize_dom(html, on_progress=on_progress)
    schema = infer_schema(url, dom_summary, on_progress)
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
    select_next_link=None
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
                         that returns (should_continue, next_url).
                         If None, uses automatic LLM-based detection.

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

    while level <= max_depth:
        # Check for cycles
        if current_url in visited_urls:
            if on_progress:
                on_progress("Warning", f"URL already visited, stopping to avoid cycle")
            break

        visited_urls.add(current_url)

        if on_progress:
            on_progress(f"Level {level}", current_url)

        # Traverse the current page
        result = traverse(current_url, on_progress)
        schema = result["schema"]
        dom_summary = result["dom_summary"]
        link_samples = result["link_samples"]

        schema_chain.append({
            "level": level,
            "url": current_url,
            "schema": schema
        })

        # Notify about inferred schema
        if on_schema_inferred:
            on_schema_inferred(level, current_url, schema)

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
            should_continue, next_url = select_next_link(
                current_url, dom_summary, schema, unvisited_links, visited_urls
            )
        else:
            # Use automatic LLM-based detection
            should_continue, next_url = _auto_select_next_link(
                current_url, dom_summary, schema, unvisited_links, on_progress
            )

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


def _auto_select_next_link(url: str, dom_summary: dict, schema: dict, unvisited_links: list, on_progress=None) -> tuple:
    """
    Automatically select the next link using LLM analysis.
    Internal function used by discover().

    Returns:
        (should_continue, next_url) tuple
    """
    nesting_result = analyze_nesting(url, dom_summary, schema, unvisited_links, on_progress)

    is_final = nesting_result.get("is_final_level", True)

    if on_progress:
        reasoning = nesting_result.get("reasoning", "")
        on_progress("Nesting analysis", f"Final level: {is_final}")
        if reasoning:
            on_progress("Reason", reasoning)

    if is_final:
        return False, None

    link_index = nesting_result.get("recommended_link_index")
    if link_index is None:
        return False, None

    # Ensure link_index is an integer
    try:
        link_index = int(link_index)
    except (TypeError, ValueError):
        if on_progress:
            on_progress("Warning", f"Invalid link index: {link_index}")
        return False, None

    if link_index < 0 or link_index >= len(unvisited_links):
        if on_progress:
            on_progress("Warning", f"Link index {link_index} out of range")
        return False, None

    selected_url = unvisited_links[link_index]

    if on_progress:
        link_reason = nesting_result.get("recommended_link_reason", "")
        on_progress("Drilling deeper", selected_url)
        if link_reason:
            on_progress("Reason", link_reason)

    return True, selected_url
