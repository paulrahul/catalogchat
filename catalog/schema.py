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

    links = [a.get("href") for a in soup.find_all("a", href=True)][:20]

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
        "link_samples": links,
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
    """Build the prompt for nesting analysis."""
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

    Args:
        plan: The plan to edit
        edits: List of edit operations

    Returns:
        Updated CatalogPlan with edits applied

    Edit operations:
        {"action": "rename", "field": "old_name", "new_name": "new_name", "level": 0}
        {"action": "delete", "field": "field_name", "level": 0}
        {"action": "update", "field": "field_name", "type": "string", "required": True, ...}
        {"action": "add", "name": "field_name", "type": "string", ...}

    When "level" is provided (schema_chain index), edits are applied to both
    schema_chain[level].fields and the corresponding merged field in plan.fields.
    """
    # Work with a copy
    data = plan.to_dict()
    fields = data.get("fields", [])
    schema_chain = data.get("schema_chain", [])

    for edit in edits:
        action = edit.get("action")
        level = edit.get("level")  # schema_chain index (optional)

        # Resolve the actual level number from schema_chain for matching
        # against source_level_num in merged fields.
        level_num = None
        if level is not None and 0 <= level < len(schema_chain):
            level_num = schema_chain[level].get("level", level + 1)

        if action == "rename":
            old_name = edit.get("field")
            new_name = edit.get("new_name")

            # Update in schema_chain
            if level is not None and 0 <= level < len(schema_chain):
                for f in schema_chain[level].get("fields", []):
                    if f.get("name") == old_name:
                        f["name"] = new_name
                        break

            # Update in merged fields
            if level_num is not None:
                for f in fields:
                    if f.get("original_name") == old_name and f.get("source_level_num") == level_num:
                        f["original_name"] = new_name
                        current_name = f.get("name", "")
                        if current_name.endswith(f"_{old_name}"):
                            prefix = current_name[: -len(old_name)]
                            f["name"] = f"{prefix}{new_name}"
                        else:
                            f["name"] = new_name
                        break
            else:
                for f in fields:
                    if f.get("name") == old_name:
                        f["name"] = new_name
                        break

        elif action == "delete":
            field_name = edit.get("field")

            # Delete from schema_chain
            if level is not None and 0 <= level < len(schema_chain):
                level_fields = schema_chain[level].get("fields", [])
                schema_chain[level]["fields"] = [
                    f for f in level_fields if f.get("name") != field_name
                ]

            # Delete from merged fields
            if level_num is not None:
                fields = [
                    f for f in fields
                    if not (f.get("original_name") == field_name and f.get("source_level_num") == level_num)
                ]
            else:
                fields = [f for f in fields if f.get("name") != field_name]
            data["fields"] = fields

        elif action == "update":
            field_name = edit.get("field")
            for f in fields:
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
            fields.append(new_field)

    data["fields"] = fields
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

    if not plan.fields:
        warnings.append("No fields defined")

    # Check for duplicate field names
    field_names = [f.name for f in plan.fields]
    duplicates = [name for name in field_names if field_names.count(name) > 1]
    if duplicates:
        warnings.append(f"Duplicate field names: {', '.join(set(duplicates))}")

    # Check for fields without selectors
    fields_without_selectors = [f.name for f in plan.fields if not f.selector]
    if fields_without_selectors:
        warnings.append(
            f"Fields without selectors: {', '.join(fields_without_selectors)}"
        )

    # Check for required fields without selectors
    required_without_selectors = [
        f.name for f in plan.fields if f.required and not f.selector
    ]
    if required_without_selectors:
        warnings.append(
            f"Required fields without selectors: {', '.join(required_without_selectors)}"
        )

    return warnings


# -------------------------
# Schema Merging
# -------------------------


def _normalize_level_name(name: str) -> str:
    """Convert a level name to a valid field prefix (snake_case)."""
    if not name:
        return "level"
    normalized = name.lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = normalized.strip("_")
    return normalized or "level"


def merge_schemas(schema_chain: list[dict], on_progress=None) -> dict:
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

        item_schema = schema.get("item_schema") or {}
        fields = item_schema.get("fields") or []

        for field in fields:
            all_fields.append(
                {"field": field, "level_num": level_num, "level_name": level_name}
            )

    # Second pass: identify which field names appear at multiple levels
    field_occurrences = {}
    for entry in all_fields:
        field = entry["field"]
        field_name = field.get("name")
        level_num = entry["level_num"]
        level_name = entry["level_name"]
        description = field.get("description", "")

        if field_name not in field_occurrences:
            field_occurrences[field_name] = []

        level_exists = any(
            occ["level_num"] == level_num for occ in field_occurrences[field_name]
        )
        if not level_exists:
            field_occurrences[field_name].append(
                {"level_num": level_num, "level_name": level_name, "description": description}
            )

    # Identify fields that need prefixing
    fields_needing_prefix = {
        name for name, occurrences in field_occurrences.items() if len(occurrences) > 1
    }

    # Third pass: build merged fields with appropriate naming
    merged_fields = []
    seen_field_names = set()

    for entry in reversed(all_fields):
        field = entry["field"]
        level_num = entry["level_num"]
        level_name = entry["level_name"]
        field_name = field.get("name")

        if field_name in seen_field_names:
            continue
        seen_field_names.add(field_name)

        if field_name in fields_needing_prefix:
            occurrences = field_occurrences[field_name]
            level_names_unique = len(set(occ["level_name"] for occ in occurrences))
            if level_names_unique < len(occurrences):
                prefix = f"level_{level_num}"
            else:
                prefix = _normalize_level_name(level_name)
            final_name = f"{prefix}_{field_name}"
        else:
            final_name = field_name

        merged_field = field.copy()
        merged_field["name"] = final_name
        merged_field["original_name"] = field_name
        merged_field["source_level"] = level_name
        merged_field["source_level_num"] = level_num
        merged_fields.append(merged_field)

    merged_fields.reverse()

    final_level = schema_chain[-1]
    final_item_schema = final_level["schema"].get("item_schema") or {}
    final_item_name = final_item_schema.get("item_name") or "Item"

    if on_progress:
        on_progress("Schema merge complete", f"{len(merged_fields)} unique fields")

    # Build level_names, ensuring no None values
    level_names = []
    for s in schema_chain:
        catalog_type = s["schema"].get("catalog_type")
        level_names.append(catalog_type if catalog_type else f"level_{s['level']}")

    return {
        "item_name": final_item_name,
        "nesting_depth": len(schema_chain),
        "fields": merged_fields,
        "level_names": level_names,
    }
