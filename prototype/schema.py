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

    # Extract structural elements for detail pages (elements with classes/ids containing meaningful text)
    # This captures containers that might only appear once but contain important data
    structural_elements = []
    seen_selectors = set()

    # Look for semantic containers that might hold field data
    semantic_tags = ["main", "article", "section", "header", "aside", "div", "dl", "ul", "ol", "table", "figure"]

    for tag_name in semantic_tags:
        for el in soup.find_all(tag_name)[:15]:  # Limit per tag
            classes = el.get("class", [])
            el_id = el.get("id", "")

            # Build selector
            if el_id:
                selector = f"#{el_id}"
            elif classes:
                selector = f"{tag_name}.{'.'.join(classes)}"
            else:
                continue  # Skip elements without class or id

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
                if hasattr(child, 'name') and child.name:
                    child_classes = child.get("class", [])
                    child_id = child.get("id", "")
                    child_text = " ".join(child.stripped_strings)[:100] if hasattr(child, 'stripped_strings') else ""

                    if child_text:  # Only include children with text
                        children.append({
                            "tag": child.name,
                            "class": ".".join(child_classes) if child_classes else None,
                            "id": child_id or None,
                            "text": child_text
                        })

            if children:  # Only include if has meaningful children
                structural_elements.append({
                    "selector": selector,
                    "tag": tag_name,
                    "text_preview": direct_text[:150],
                    "children": children[:10]  # Limit children shown
                })

    # Sort by likely importance (elements with more specific classes first)
    structural_elements.sort(key=lambda x: len(x.get("children", [])), reverse=True)
    structural_elements = structural_elements[:25]  # Limit total

    if on_progress:
        on_progress("DOM analysis complete", f"{len(common_classes)} patterns, {len(structural_elements)} structures")

    return {
        "title": soup.title.string if soup.title else None,
        "common_classes": common_classes,
        "samples": samples,
        "link_samples": links,
        "structural_elements": structural_elements
    }


# -------------------------
# Prompt Builders
# -------------------------

def build_schema_prompt(url: str, dom_summary: dict, is_final_level: bool = False) -> str:
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
    from bs4 import BeautifulSoup
    import re

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

        # Get element info
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
                parent_chain.append({
                    "tag": current.name,
                    "classes": p_classes,
                    "id": p_id
                })
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

        # Get text preview
        text = element.strip()[:100]

        results.append({
            "tag": tag_name,
            "classes": classes,
            "id": elem_id,
            "parent_chain": parent_chain,
            "text_preview": text,
            "selector_hint": " ".join(selector_parts),
            "full_text": str(parent.get_text(strip=True))[:200]
        })

    # Also search in attribute values (for images, links, etc.)
    for attr in ["alt", "title", "value", "placeholder", "aria-label"]:
        if len(results) >= max_results:
            break
        for element in soup.find_all(attrs={attr: re.compile(re.escape(search_text), re.IGNORECASE)}):
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

            results.append({
                "tag": tag_name,
                "classes": classes,
                "id": elem_id,
                "parent_chain": [],
                "text_preview": f"[{attr}] {attr_value[:100]}",
                "selector_hint": " ".join(selector_parts),
                "attribute_found": attr,
                "full_text": attr_value[:200]
            })

    return results


def build_field_correction_prompt(
    field_name: str,
    current_container_selector: str,
    current_selector: str,
    current_attribute: str,
    current_value: str,
    user_feedback: str,
    expected_value: str,
    dom_summary: dict,
    item_container_selector: str,
    found_elements: list = None
) -> str:
    """Build prompt for correcting a field's selector."""

    # Build found elements section if we found the expected value
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


def correct_field_selector(
    field_name: str,
    current_container_selector: str,
    current_selector: str,
    current_attribute: str,
    current_value: str,
    user_feedback: str,
    expected_value: str,
    dom_summary: dict,
    item_container_selector: str,
    found_elements: list = None,
    on_progress=None
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
    prompt = build_field_correction_prompt(
        field_name=field_name,
        current_container_selector=current_container_selector,
        current_selector=current_selector,
        current_attribute=current_attribute,
        current_value=current_value,
        user_feedback=user_feedback,
        expected_value=expected_value,
        dom_summary=dom_summary,
        found_elements=found_elements,
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

    # Second pass: identify which field names appear at multiple levels
    # Use level_num (not level_name) since multiple levels can have same catalog_type
    field_occurrences = {}  # field_name -> list of {level_num, level_name, description}
    for entry in all_fields:
        field = entry["field"]
        field_name = field.get("name")
        level_num = entry["level_num"]
        level_name = entry["level_name"]
        description = field.get("description", "")

        if field_name not in field_occurrences:
            field_occurrences[field_name] = []

        # Check if this EXACT level (by number) already has this field
        level_exists = any(
            occ["level_num"] == level_num
            for occ in field_occurrences[field_name]
        )
        if not level_exists:
            field_occurrences[field_name].append({
                "level_num": level_num,
                "level_name": level_name,
                "description": description
            })

    # Identify fields that need prefixing (appear at multiple levels)
    fields_needing_prefix = {
        name for name, occurrences in field_occurrences.items()
        if len(occurrences) > 1
    }

    # Third pass: build merged fields with appropriate naming
    # For fields appearing at multiple levels, use the LAST (deepest) level's definition
    # since that's typically the most detailed (e.g., detail page fields)
    merged_fields = []
    seen_field_names = set()  # Track original field names we've processed

    # Process in reverse order so we keep the deepest level's definition
    for entry in reversed(all_fields):
        field = entry["field"]
        level_num = entry["level_num"]
        level_name = entry["level_name"]
        field_name = field.get("name")

        # Skip if we've already processed this field name
        if field_name in seen_field_names:
            continue
        seen_field_names.add(field_name)

        # Determine the final field name
        if field_name in fields_needing_prefix:
            # Use level number in prefix if multiple levels have same catalog_type
            occurrences = field_occurrences[field_name]
            level_names_unique = len(set(occ["level_name"] for occ in occurrences))
            if level_names_unique < len(occurrences):
                # Multiple levels have same name, use level number
                prefix = f"level_{level_num}"
            else:
                prefix = normalize_level_name(level_name)
            final_name = f"{prefix}_{field_name}"
        else:
            final_name = field_name

        merged_field = field.copy()
        merged_field["name"] = final_name
        merged_field["original_name"] = field_name
        merged_field["source_level"] = level_name
        merged_field["source_level_num"] = level_num
        merged_fields.append(merged_field)

    # Reverse to restore original order (deepest fields last)
    merged_fields.reverse()

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
                "container_selector": field.get("container_selector"),
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

    # Build extraction_fields from navigation_path to ensure consistency
    # This guarantees that extraction_fields uses the same selector data as navigation_path
    extraction_fields = []
    final_field_names = []

    # Create a lookup: (level_num, original_name) -> navigation_path field
    nav_field_lookup = {}
    for level_plan in navigation_path:
        level_num = level_plan.get("level")
        for field in level_plan.get("fields", []):
            key = (level_num, field.get("name"))
            nav_field_lookup[key] = field

    # Build extraction_fields using merged_schema for metadata but navigation_path for selectors
    for merged_field in merged_schema.get("fields", []):
        merged_name = merged_field.get("name")
        original_name = merged_field.get("original_name")
        source_level = merged_field.get("source_level")
        source_level_num = merged_field.get("source_level_num")

        final_field_names.append(merged_name)

        # Look up the selector from navigation_path using level_num
        nav_field = nav_field_lookup.get((source_level_num, original_name), {}) if source_level_num else {}

        extraction_fields.append({
            "name": merged_name,
            "original_name": original_name,
            "type": merged_field.get("type"),
            "source_level": source_level,
            "source_level_num": source_level_num,
            # Use selectors from navigation_path (same source, ensures consistency)
            "container_selector": nav_field.get("container_selector", merged_field.get("container_selector")),
            "selector": nav_field.get("selector", merged_field.get("selector")),
            "attribute": nav_field.get("attribute", merged_field.get("attribute", "text")),
            "required": merged_field.get("required", False),
            "description": merged_field.get("description")
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
