"""
Schema inference and manipulation functions.

This module contains:
- DOM summarization for LLM analysis
- Schema inference using LLM
- Nesting analysis
- Field correction
- Schema editing and validation
"""

import json
import re
from collections import Counter

from bs4 import BeautifulSoup

from catalog.types import CatalogPlan, Field
from catalog.util import call_llm


# -------------------------
# DOM Summarization
# -------------------------


def summarize_dom(html: str, max_blocks: int = 20, on_progress=None) -> dict:
    """
    Extract DOM structure and patterns from HTML for LLM analysis.

    Args:
        html: The HTML content to analyze
        max_blocks: Maximum number of CSS class patterns to extract
        on_progress: Optional callback(step, detail) for progress reporting

    Returns:
        Dict containing title, common_classes, samples, link_samples, and structural_elements
    """
    if on_progress:
        on_progress("Parsing and summarizing DOM structure", "")

    soup = BeautifulSoup(html, "html.parser")

    # Remove noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # Find candidate repeated blocks (for list/catalog pages)
    elements = soup.find_all(True)
    class_counter = Counter()

    for el in elements:
        classes = el.get("class")
        if classes:
            for c in classes:
                class_counter[c] += 1

    common_classes = [c for c, count in class_counter.items() if count >= 5][
        :max_blocks
    ]

    samples = []
    for cls in common_classes:
        nodes = soup.select(f".{cls}")[:3]
        for n in nodes:
            text = " ".join(n.stripped_strings)
            text = re.sub(r"\s+", " ", text)
            samples.append({"class": cls, "tag": n.name, "text_sample": text[:300]})

    link_samples = []
    seen_hrefs: set[str] = set()
    for a in soup.find_all("a", href=True)[:60]:
        href = a.get("href", "")
        if not href or href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        text = a.get_text(strip=True)[:60]
        parent = a.parent
        parent_tag = parent.name if parent else ""
        parent_cls = " ".join(parent.get("class", []))[:50] if parent else ""
        in_nav = bool(a.find_parent(["nav", "header", "footer"]))
        link_samples.append({
            "href": href,
            "text": text,
            "parent_tag": parent_tag,
            "parent_class": parent_cls,
            "in_nav": in_nav,
        })

    # Extract structural elements for detail pages
    structural_elements = []
    seen_selectors = set()

    # Look for semantic containers that might hold field data
    semantic_tags = [
        "main",
        "article",
        "section",
        "header",
        "aside",
        "div",
        "dl",
        "ul",
        "ol",
        "table",
        "figure",
    ]

    for tag_name in semantic_tags:
        for el in soup.find_all(tag_name)[:15]:
            classes = el.get("class", [])
            el_id = el.get("id", "")

            # Build selector
            if el_id:
                selector = f"#{el_id}"
            elif classes:
                selector = f"{tag_name}.{'.'.join(classes)}"
            else:
                continue

            if selector in seen_selectors:
                continue
            seen_selectors.add(selector)

            # Get direct text and child structure
            direct_text = " ".join(el.stripped_strings)[:200]
            if not direct_text:
                continue

            # Get immediate children summary
            children = []
            for child in el.children:
                if hasattr(child, "name") and child.name:
                    child_classes = child.get("class", [])
                    child_id = child.get("id", "")
                    child_text = (
                        " ".join(child.stripped_strings)[:100]
                        if hasattr(child, "stripped_strings")
                        else ""
                    )

                    if child_text:
                        children.append(
                            {
                                "tag": child.name,
                                "class": ".".join(child_classes) if child_classes else None,
                                "id": child_id or None,
                                "text": child_text,
                            }
                        )

            if children:
                structural_elements.append(
                    {
                        "selector": selector,
                        "tag": tag_name,
                        "text_preview": direct_text[:150],
                        "children": children[:10],
                    }
                )

    structural_elements.sort(key=lambda x: len(x.get("children", [])), reverse=True)
    structural_elements = structural_elements[:25]

    if on_progress:
        on_progress(
            "DOM analysis complete",
            f"{len(common_classes)} patterns, {len(structural_elements)} structures",
        )

    return {
        "title": soup.title.string if soup.title else None,
        "common_classes": common_classes,
        "samples": samples,
        "link_samples": link_samples,
        "structural_elements": structural_elements,
    }


# -------------------------
# Prompt Builders
# -------------------------


def _build_schema_prompt(url: str, dom_summary: dict, is_final_level: bool = False) -> str:
    """Build the prompt for schema inference."""
    if is_final_level:
        # Prompt optimized for detail/final pages
        return f"""
You are an expert web data extraction system. Your goal is COMPLETENESS - extract ALL descriptive fields visible on the page.

Your task is to analyze a DETAIL PAGE - a page that shows information about a SINGLE ITEM
(e.g., a product detail page, a movie info page, an article page).

IMPORTANT: Be THOROUGH and COMPLETE. Extract EVERY visible descriptive field, not just the obvious ones.

FIELD CATEGORIES TO LOOK FOR (extract ALL that are present):

1. IDENTIFICATION:
   - title, name, headline
   - subtitle, tagline
   - id, sku, catalog_number, isbn

2. MEDIA:
   - image, poster, thumbnail, cover_image
   - gallery_images, video_url

3. CATEGORIZATION:
   - category, genre, type, department
   - tags, keywords, labels
   - collection, series

4. PEOPLE/CREATORS:
   - author, writer, creator
   - director, producer, cast, actors
   - artist, designer, manufacturer, brand

5. DATES & TIMES:
   - date, publish_date, release_date, release_year
   - created_at, updated_at
   - duration, runtime, length

6. DESCRIPTION:
   - description, summary, synopsis, overview
   - details, specifications, features
   - content, body_text

7. METRICS & RATINGS:
   - rating, score, stars
   - reviews_count, review_count
   - popularity, rank

8. PRICING & AVAILABILITY:
   - price, sale_price, original_price
   - currency, discount
   - availability, stock_status, in_stock

9. PHYSICAL ATTRIBUTES:
   - size, dimensions, weight
   - color, material, format

10. LINKS & REFERENCES:
    - url, link, canonical_url
    - source_url, external_link

DO NOT extract:
- Navigation links to other pages (home, about, contact, etc.)
- Related items or "you may also like" recommendations
- Footer/header content
- Social media sharing links
- Login/signup links
- Shopping cart or checkout links

Output STRICT JSON in the following format:

{{
  "is_catalog": true,
  "catalog_type": "string (what type of item this is, e.g., 'film', 'product', 'article')",
  "confidence": 0.0-1.0,
  "archetype": "detail_page",
  "item_schema": {{
    "item_name": "string (singular name of the item type)",
    "item_container_selector": "CSS selector for the main content area (e.g., 'body', 'main', 'article')",
    "fields": [
      {{
        "name": "string (use snake_case names like: title, description, price, rating, director, release_year, etc.)",
        "type": "string | number | boolean | url | date",
        "required": true | false,
        "description": "string",
        "container_selector": "CSS selector for the container holding this specific field (e.g., '.product-header', '.sidebar', '.main-content')",
        "selector": "CSS selector relative to container_selector to find this field (e.g., 'h1', '.price', 'img')",
        "attribute": "attribute to extract - 'text' for inner text content, 'href' for links, 'src' for images"
      }}
    ]
  }},
  "reasoning": "short explanation of what item this page describes"
}}

SELECTOR GUIDELINES:
- container_selector: The parent element containing this specific field. Different fields can have different containers.
- selector: CSS selector RELATIVE to container_selector to find the field element
- For example, if title is in <div class="header"><h1>Title</h1></div>, use container_selector=".header", selector="h1"
- If a field cannot be reliably selected, set both container_selector and selector to null

CONSISTENCY RULES:
- Always use snake_case for field names (e.g., release_year, not releaseYear or "Release Year")
- Use consistent naming: "title" not "name" for the main title, "description" not "summary" for main description
- Include ALL fields you can identify, even if you're not 100% sure about the selector
- Better to include a field with selector=null than to omit it entirely

IMPORTANT: Focus on extracting CONTENT fields, not navigation. This is the final detail level.
Scan the ENTIRE page systematically - header area, main content, sidebars, metadata sections.

Page URL:
{url}

Page title:
{dom_summary.get("title")}

STRUCTURAL ELEMENTS (containers with their children - USE THESE FOR SELECTORS):
{json.dumps(dom_summary.get("structural_elements", []), indent=2, ensure_ascii=False)}

Common CSS classes detected:
{dom_summary.get("common_classes")}

DOM samples (class, tag, text):
{json.dumps(dom_summary.get("samples"), indent=2, ensure_ascii=False)}

Link samples (for context only, do NOT extract these as fields):
{json.dumps(dom_summary.get("link_samples"), indent=2, ensure_ascii=False)}

IMPORTANT: Use the STRUCTURAL ELEMENTS above to determine the correct container_selector and selector.
Each structural element shows its CSS selector, tag, and children with their text content.
Match the expected field values to the text shown in children to find the right selector.
"""
    else:
        # Prompt for catalog/list pages
        return f"""
You are an expert web data extraction system. Your goal is COMPLETENESS - extract ALL visible fields for each item.

Your task is to analyze a webpage summary and infer whether it represents
a CATALOG (a list of similar objects such as products, movies, articles, books, etc).

If it is a catalog:
- Identify the object type
- Extract ALL visible fields for each item (be thorough!)
- Use consistent snake_case field names
- Infer data types accurately
- Identify CSS selectors for extracting the data

If it is NOT a catalog, clearly say so.

FIELD CATEGORIES TO LOOK FOR IN EACH ITEM (extract ALL that are visible):

1. IDENTIFICATION: title, name, id, sku
2. MEDIA: image, thumbnail, icon
3. CATEGORIZATION: category, type, genre, tags
4. PEOPLE: author, creator, director, artist, brand
5. DATES: date, publish_date, release_date, release_year
6. DESCRIPTION: description, summary, excerpt, subtitle
7. METRICS: rating, score, stars, reviews_count, popularity
8. PRICING: price, sale_price, currency, discount
9. STATUS: availability, stock_status, badge, label
10. LINKS: url, link (the link to the item's detail page)

Supported catalog archetypes:
- card_grid: Items displayed as cards in a grid layout
- list: Items displayed in a vertical list
- table: Items displayed in a table with rows and columns

Output STRICT JSON in the following format:

{{
  "is_catalog": true | false,
  "catalog_type": "string | null (e.g., 'product', 'film', 'article', 'book')",
  "confidence": 0.0-1.0,
  "archetype": "card_grid | list | table | unknown",
  "item_schema": {{
    "item_name": "string (singular name, e.g., 'product', 'film', 'article')",
    "item_container_selector": "CSS selector to find each repeated item container",
    "fields": [
      {{
        "name": "string (use snake_case: title, price, release_date, etc.)",
        "type": "string | number | boolean | url | date",
        "required": true | false,
        "description": "string",
        "container_selector": "CSS selector for this field's container (use null to inherit item_container_selector, or specify if field is in a different container)",
        "selector": "CSS selector relative to container to find this field",
        "attribute": "attribute to extract (e.g., 'href', 'src', 'text') - use 'text' for inner text content"
      }}
    ]
  }},
  "reasoning": "short explanation"
}}

SELECTOR GUIDELINES:
- item_container_selector: CSS selector that matches ALL repeated items on the page (e.g., ".product-card", "tr.item-row", ".listing")
- container_selector: Per-field container. Set to null if field is inside item_container_selector, or specify a different selector if field is elsewhere
- selector: CSS selector RELATIVE to the container (item_container_selector or container_selector) to find the field
- attribute: what to extract - "text" for inner text content, "href" for links, "src" for images, or any HTML attribute
- Use the common CSS classes provided below to identify the right selectors
- If a field cannot be reliably selected, set selector to null but STILL INCLUDE THE FIELD

CONSISTENCY RULES:
- Always use snake_case for field names (title, not Title; release_date, not releaseDate)
- Use "title" for the main name/title field
- Use "image" for the main image (not "thumbnail" or "poster" unless that's more accurate)
- Use "url" or "link" for the detail page link
- Never return null for item_schema. Set it to an empty object when applicable.
- Include ALL visible fields, even with selector=null if uncertain
- Examine EVERY item card/row to identify all possible fields

DO NOT include markdown.
DO NOT include extra commentary.

Page URL:
{url}

Page title:
{dom_summary.get("title")}

STRUCTURAL ELEMENTS (containers with children - use for selector hints):
{json.dumps(dom_summary.get("structural_elements", [])[:15], indent=2, ensure_ascii=False)}

Common CSS classes detected:
{dom_summary.get("common_classes")}

DOM samples (class, tag, text):
{json.dumps(dom_summary.get("samples"), indent=2, ensure_ascii=False)}

Link samples:
{json.dumps(dom_summary.get("link_samples"), indent=2, ensure_ascii=False)}
"""


def _build_nesting_analysis_prompt(
    url: str, dom_summary: dict, schema: dict, link_samples: list
) -> str:
    """Build the prompt for nesting analysis.

    link_samples may be list[str] (legacy) or list[dict] with keys
    href, text, in_nav (produced by enriched summarize_dom or item extraction).
    """
    from urllib.parse import urlparse
    root_path = urlparse(url).path.rstrip("/")

    formatted_links = []
    for i, link in enumerate(link_samples):
        if isinstance(link, dict):
            href = link.get("href", "")
            text = link.get("text", "").strip()
            in_nav = link.get("in_nav", False)
            nav_note = "  ⚠ navigation" if in_nav else ""
            text_part = f'  "{text}"' if text else ""
            formatted_links.append(f"  {i}: {href}{text_part}{nav_note}")
        else:
            formatted_links.append(f"  {i}: {link}")

    numbered_links = "\n".join(formatted_links)

    return f"""
You are an expert web structure analyzer.

You are analyzing a catalog page to determine if it contains NESTED content that should be explored further.

NESTING EXAMPLES:
- A product listing where each item links to a product detail page
- A film index where each title links to a film detail page
- A directory page where each entry links to a full record page

YOUR TASK:
1. Determine if this is a FINAL DETAIL PAGE (no further meaningful nesting) or an INTERMEDIATE PAGE (links lead to richer item detail)
2. If intermediate, rank the best candidate links to follow to reach item details
3. If intermediate, identify the CSS selector to find ALL similar drill-down links on the page

A page is a FINAL DETAIL PAGE if:
- It shows the full details of a single item (specs, synopsis, article body, etc.)
- Links mostly lead to unrelated pages, navigation, or external sites

A page is an INTERMEDIATE PAGE if:
- It is a list/grid of items and clicking an item leads to a richer detail page
- There is a clear repeating link pattern pointing deeper into the same site

CURRENT PAGE INFO:
URL: {url}
Root path: {root_path}
Title: {dom_summary.get("title")}
Detected catalog type: {schema.get("catalog_type")}
Item name: {schema.get("item_schema", {}).get("item_name", "unknown")}
Item container selector: {schema.get("item_schema", {}).get("item_container_selector", "unknown")}

LINK SELECTION RULES — follow these strictly:
1. IGNORE any link marked "⚠ navigation" — those are site nav, not catalog items.
2. PREFER links whose path STARTS WITH "{root_path}/" — these are children of the current page and most likely to be item detail pages.
3. Among child links, prefer those whose anchor text looks like a specific item name (film title, product name, article headline) rather than a generic section label (Home, About, Selection, Contact).
4. A link that goes to a sibling section (same depth, different branch, e.g. /en/selection/ from /en/program/) is almost certainly NOT the right drill target.

Available links (INDEX: URL  "anchor text"  [nav flag]):
{numbered_links}

Output STRICT JSON — no markdown, no commentary:
{{
  "is_final_level": true | false,
  "reasoning": "concise explanation",
  "recommended_link_index": null | <integer index from the list above>,
  "recommended_link_reason": "why this is the best drill-down candidate",
  "drill_down_link_selector": "CSS selector (relative to item container) to find ALL drill-down links, or null if final level",
  "ranked_candidates": [
    {{
      "link_index": <integer index>,
      "label": "<anchor text if available, else last URL path segment cleaned up>",
      "reason": "<one sentence why this leads to item detail>",
      "confidence": <0.0-1.0>
    }}
  ]
}}

For ranked_candidates:
- List up to 8 candidates, ordered from most to least likely to be item detail links.
- Exclude links marked "⚠ navigation".
- If is_final_level is true, return an empty array for ranked_candidates.
- recommended_link_index must equal ranked_candidates[0].link_index.
"""


def _build_field_correction_prompt(
    field_name: str,
    current_container_selector: str,
    current_selector: str,
    current_attribute: str,
    current_value: str,
    user_feedback: str,
    expected_value: str,
    dom_summary: dict,
    item_container_selector: str,
    found_elements: list | None = None,
) -> str:
    """Build prompt for correcting a field's selector."""
    found_elements_section = ""
    if found_elements:
        found_elements_section = f"""
IMPORTANT - EXPECTED VALUE FOUND IN PAGE:
We searched the page for "{expected_value}" and found it in these elements:

{json.dumps(found_elements, indent=2, ensure_ascii=False)}

Use this information to determine the correct selector. The selector_hint and parent_chain
show where the expected value is located in the DOM.
"""
    else:
        found_elements_section = f"""
NOTE: We searched the page for "{expected_value}" but did not find an exact match.
The value might be formatted differently, split across elements, or dynamically loaded.
"""

    return f"""
You are an expert web data extraction system helping to fix an incorrect CSS selector.

A user is trying to extract data from a webpage, but one of the fields is extracting wrong data.

CURRENT EXTRACTION SETUP:
- Field name: {field_name}
- Level item container selector: {item_container_selector}
- Field's container_selector: {current_container_selector or "None (using item container)"}
- Field's selector (relative to container): {current_selector or "None"}
- Attribute being extracted: {current_attribute}
- Current extracted value: {current_value or "Nothing extracted"}

USER FEEDBACK:
- What's wrong: {user_feedback}
- Expected value (example): {expected_value}
{found_elements_section}
PAGE STRUCTURE:
Common CSS classes detected:
{dom_summary.get("common_classes")}

DOM samples (class, tag, text):
{json.dumps(dom_summary.get("samples"), indent=2, ensure_ascii=False)}

YOUR TASK:
Analyze the DOM structure and suggest CORRECTED selectors that will extract the expected value.
- container_selector: The parent container for this field (can be different from item container, or null to use item container)
- selector: CSS selector RELATIVE to the container to find the field element

Output STRICT JSON:
{{
  "corrected_container_selector": "CSS selector for field's container, or null to use item container",
  "corrected_selector": "CSS selector relative to container",
  "corrected_attribute": "text | href | src | or other attribute",
  "reasoning": "explanation of why these selectors should work",
  "confidence": 0.0-1.0
}}

If you cannot determine good selectors, set both to null and explain in reasoning.

DO NOT include markdown.
DO NOT include extra commentary.
"""


# -------------------------
# Schema Inference (Single Page)
# -------------------------


def infer_schema(
    url: str, dom_summary: dict, on_progress=None, is_final_level: bool = False
) -> dict:
    """
    Infer catalog schema from DOM summary.

    Args:
        url: The page URL
        dom_summary: DOM summary from summarize_dom()
        on_progress: Optional callback(step, detail) for progress reporting
        is_final_level: If True, uses detail-page optimized prompt

    Returns:
        Schema dict with is_catalog, catalog_type, confidence, archetype, item_schema, reasoning
    """
    prompt = _build_schema_prompt(url, dom_summary, is_final_level=is_final_level)
    return call_llm(prompt, "schema inference", on_progress)


def analyze_nesting(
    url: str, dom_summary: dict, schema: dict, link_samples: list, on_progress=None
) -> dict:
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
    prompt = _build_nesting_analysis_prompt(url, dom_summary, schema, link_samples)
    return call_llm(prompt, "nesting detection", on_progress)


# -------------------------
# Field Correction
# -------------------------


def find_value_in_html(html: str, expected_value: str, max_results: int = 5) -> list:
    """
    Search for an expected value in HTML and return information about elements containing it.

    Args:
        html: The HTML content to search
        expected_value: The value to find
        max_results: Maximum number of matching elements to return

    Returns:
        List of dicts with element info: tag, classes, id, parent_classes, text_preview, selector_hint
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove script and style tags
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    results = []
    search_text = expected_value.lower().strip()

    # Search for elements containing the text
    for element in soup.find_all(string=re.compile(re.escape(search_text), re.IGNORECASE)):
        if len(results) >= max_results:
            break

        parent = element.parent
        if not parent or parent.name in ["script", "style", "noscript"]:
            continue

        tag_name = parent.name
        classes = parent.get("class", [])
        elem_id = parent.get("id", "")

        # Get parent chain for context
        parent_chain = []
        current = parent.parent
        depth = 0
        while current and current.name and depth < 3:
            p_classes = current.get("class", [])
            p_id = current.get("id", "")
            if p_classes or p_id:
                parent_chain.append({"tag": current.name, "classes": p_classes, "id": p_id})
            current = current.parent
            depth += 1

        # Build a selector hint
        selector_parts = []
        if elem_id:
            selector_parts.append(f"#{elem_id}")
        elif classes:
            selector_parts.append(f"{tag_name}.{'.'.join(classes)}")
        else:
            selector_parts.append(tag_name)

        text = element.strip()[:100]

        results.append(
            {
                "tag": tag_name,
                "classes": classes,
                "id": elem_id,
                "parent_chain": parent_chain,
                "text_preview": text,
                "selector_hint": " ".join(selector_parts),
                "full_text": str(parent.get_text(strip=True))[:200],
            }
        )

    # Also search in attribute values
    for attr in ["alt", "title", "value", "placeholder", "aria-label"]:
        if len(results) >= max_results:
            break
        for element in soup.find_all(
            attrs={attr: re.compile(re.escape(search_text), re.IGNORECASE)}
        ):
            if len(results) >= max_results:
                break

            tag_name = element.name
            classes = element.get("class", [])
            elem_id = element.get("id", "")
            attr_value = element.get(attr, "")

            selector_parts = []
            if elem_id:
                selector_parts.append(f"#{elem_id}")
            elif classes:
                selector_parts.append(f"{tag_name}.{'.'.join(classes)}")
            else:
                selector_parts.append(tag_name)

            results.append(
                {
                    "tag": tag_name,
                    "classes": classes,
                    "id": elem_id,
                    "parent_chain": [],
                    "text_preview": f"[{attr}] {attr_value[:100]}",
                    "selector_hint": " ".join(selector_parts),
                    "attribute_found": attr,
                    "full_text": attr_value[:200],
                }
            )

    return results


def correct_field_selector(
    field_name: str,
    current_container_selector: str | None,
    current_selector: str | None,
    current_attribute: str,
    current_value: str,
    user_feedback: str,
    expected_value: str,
    dom_summary: dict,
    item_container_selector: str,
    found_elements: list | None = None,
    on_progress=None,
) -> dict:
    """
    Use AI to correct a field's selector based on user feedback.

    Args:
        field_name: Name of the field to correct
        current_container_selector: Current container selector for this field
        current_selector: Current CSS selector being used
        current_attribute: Current attribute being extracted
        current_value: What's currently being extracted
        user_feedback: User's description of what's wrong
        expected_value: What the user expects to see
        dom_summary: DOM summary from the page
        item_container_selector: The level's item container selector
        found_elements: List of elements where expected_value was found in the page
        on_progress: Optional callback

    Returns:
        Dict with corrected_container_selector, corrected_selector, corrected_attribute, reasoning, confidence
    """
    prompt = _build_field_correction_prompt(
        field_name=field_name,
        current_container_selector=current_container_selector or "",
        current_selector=current_selector or "",
        current_attribute=current_attribute,
        current_value=current_value,
        user_feedback=user_feedback,
        expected_value=expected_value,
        dom_summary=dom_summary,
        found_elements=found_elements,
        item_container_selector=item_container_selector,
    )
    return call_llm(prompt, f"correcting {field_name} selector", on_progress)


# -------------------------
# Schema Editing
# -------------------------


def apply_schema_edits(plan: CatalogPlan, edits: list[dict]) -> CatalogPlan:
    """
    Apply edits to a CatalogPlan's schema.

    Edits are applied directly to schema_chain[level].fields.

    Args:
        plan: The plan to edit
        edits: List of edit operations

    Returns:
        Updated CatalogPlan with edits applied

    Edit operations:
        {"action": "rename", "field": "old_name", "new_name": "new_name", "level": 0}
        {"action": "delete", "field": "field_name", "level": 0}
        {"action": "update", "field": "field_name", "level": 0, "type": "string", "required": True, ...}
        {"action": "add", "name": "field_name", "level": 0, "type": "string", ...}
    """
    data = plan.to_dict()
    schema_chain = data.get("schema_chain", [])

    for edit in edits:
        action = edit.get("action")
        level = edit.get("level", 0)

        if level is None or level < 0 or level >= len(schema_chain):
            continue

        level_fields = schema_chain[level].get("fields", [])

        if action == "rename":
            old_name = edit.get("field")
            new_name = edit.get("new_name")
            for f in level_fields:
                if f.get("name") == old_name:
                    f["name"] = new_name
                    break

        elif action == "delete":
            field_name = edit.get("field")
            schema_chain[level]["fields"] = [
                f for f in level_fields if f.get("name") != field_name
            ]

        elif action == "update":
            field_name = edit.get("field")
            for f in level_fields:
                if f.get("name") == field_name:
                    for key, value in edit.items():
                        if key not in ("action", "field", "level"):
                            f[key] = value
                    break

        elif action == "add":
            new_field = {
                "name": edit.get("name"),
                "type": edit.get("type", "string"),
                "required": edit.get("required", False),
                "description": edit.get("description", ""),
                "container_selector": edit.get("container_selector"),
                "selector": edit.get("selector"),
                "attribute": edit.get("attribute", "text"),
            }
            level_fields.append(new_field)

    data["schema_chain"] = schema_chain
    return CatalogPlan.from_dict(data)


def validate_schema(plan: CatalogPlan) -> list[str]:
    """
    Validate a CatalogPlan's schema and return any warnings/errors.

    Args:
        plan: The plan to validate

    Returns:
        List of warning/error messages (empty if valid)
    """
    warnings = []

    if not plan.root_url:
        warnings.append("Missing root URL")

    # Collect all fields from schema_chain
    all_fields = []
    for level in plan.schema_chain:
        all_fields.extend(level.fields)

    if not all_fields:
        warnings.append("No fields defined")

    # Check for fields without selectors
    fields_without_selectors = [f.name for f in all_fields if not f.selector]
    if fields_without_selectors:
        warnings.append(
            f"Fields without selectors: {', '.join(fields_without_selectors)}"
        )

    # Check for required fields without selectors
    required_without_selectors = [
        f.name for f in all_fields if f.required and not f.selector
    ]
    if required_without_selectors:
        warnings.append(
            f"Required fields without selectors: {', '.join(required_without_selectors)}"
        )

    return warnings


