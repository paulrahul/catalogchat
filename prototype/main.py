import requests
import json
import re
import sys
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from collections import Counter
from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# -------------------------
# Progress Indicators
# -------------------------

def print_progress(step: str, detail: str = ""):
    """Print a progress indicator."""
    prefix = f"  → {step}"
    if detail:
        print(f"{prefix}: {detail}")
    else:
        print(prefix)


def print_section(title: str):
    """Print a section header."""
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def print_level(level: int, url: str):
    """Print the current nesting level."""
    print(f"\n{'═' * 60}")
    print(f"  LEVEL {level}: Analyzing page")
    print(f"  URL: {url}")
    print(f"{'═' * 60}")


# -------------------------
# Step 1: Fetch HTML
# -------------------------

def fetch_html(url: str) -> str:
    print_progress("Fetching page content")
    headers = {
        "User-Agent": "Mozilla/5.0 (schema-inference-bot)"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    print_progress("Page fetched successfully", f"{len(resp.text)} bytes")
    return resp.text


# -------------------------
# Step 2: DOM summarization
# -------------------------

def summarize_dom(html: str, max_blocks=20):
    """
    Extracts repeated DOM patterns and text samples.
    This is intentionally lossy — we don't want to dump full HTML to the LLM.
    """
    print_progress("Parsing and summarizing DOM structure")
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

    print_progress("DOM analysis complete", f"{len(common_classes)} patterns, {len(links)} links")

    return {
        "title": soup.title.string if soup.title else None,
        "common_classes": common_classes,
        "samples": samples,
        "link_samples": links
    }


# -------------------------
# Step 3: Prompt construction
# -------------------------

def build_schema_prompt(url: str, dom_summary: dict) -> str:
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
    """Prompt to determine if page has nested catalogs and identify the best link."""
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
# Step 4: LLM Calls
# -------------------------

def call_llm(prompt: str, purpose: str) -> dict:
    """Generic LLM call with progress indicator."""
    print_progress(f"Analyzing with AI", purpose)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You extract structured information from web pages. Always respond with valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )
    content = response.choices[0].message.content
    return json.loads(content)


def infer_schema(url: str, dom_summary: dict) -> dict:
    """Infer catalog schema from a page."""
    prompt = build_schema_prompt(url, dom_summary)
    return call_llm(prompt, "schema inference")


def analyze_nesting(url: str, dom_summary: dict, schema: dict, link_samples: list) -> dict:
    """Analyze if page has nested content and recommend next link."""
    prompt = build_nesting_analysis_prompt(url, dom_summary, schema, link_samples)
    return call_llm(prompt, "nesting detection")


# -------------------------
# Step 5: Orchestrator
# -------------------------

def infer_catalog_schema(url: str) -> tuple:
    """Returns schema, dom_summary, and link_samples."""
    html = fetch_html(url)
    dom_summary = summarize_dom(html)
    schema = infer_schema(url, dom_summary)
    link_samples = dom_summary.get("link_samples", [])
    return schema, dom_summary, link_samples


# -------------------------
# Step 6: Display Functions
# -------------------------

def display_schema(schema: dict):
    """Display the inferred schema in a user-friendly format."""
    print_section("Inferred Schema")

    print(f"  Is Catalog: {schema.get('is_catalog')}")
    print(f"  Catalog Type: {schema.get('catalog_type')}")
    print(f"  Confidence: {schema.get('confidence')}")
    print(f"  Archetype: {schema.get('archetype')}")

    item_schema = schema.get("item_schema")
    if item_schema:
        print(f"\n  Item Name: {item_schema.get('item_name')}")
        print("  Fields:")
        fields = item_schema.get("fields", [])
        for i, field in enumerate(fields, 1):
            req = "required" if field.get("required") else "optional"
            print(f"    {i}. {field.get('name')} ({field.get('type')}, {req})")

    print(f"\n  Reasoning: {schema.get('reasoning')}")


def display_final_schema(merged_schema: dict, show_header: bool = True):
    """Display the final merged schema."""
    if show_header:
        print(f"\n{'█' * 60}")
        print("  FINAL MERGED SCHEMA")
        print(f"{'█' * 60}")

    print(f"\n  Item Name: {merged_schema.get('item_name')}")
    print(f"  Nesting Depth: {merged_schema.get('nesting_depth')} levels")
    print(f"  Levels: {' → '.join(merged_schema.get('level_names', []))}")
    print(f"\n  Fields ({len(merged_schema.get('fields', []))} total):")

    for i, field in enumerate(merged_schema.get("fields", []), 1):
        req = "required" if field.get("required") else "optional"
        source = f"[from: {field.get('source_level')}]" if field.get('source_level') else ""

        # Show if the field was renamed due to conflict
        name_display = field.get('name')
        original_name = field.get('original_name')
        if original_name and original_name != field.get('name'):
            name_display = f"{field.get('name')} (was: {original_name})"

        print(f"    {i}. {name_display} ({field.get('type')}, {req}) {source}")
        if field.get("description"):
            print(f"       {field.get('description')}")

    print()


# -------------------------
# Step 11: Schema Editing
# -------------------------

def edit_schema_interactive(merged_schema: dict) -> dict:
    """Allow user to edit/delete fields from the merged schema."""
    print_section("Schema Editor")
    print("  You can now edit the final schema.")
    print("  Commands:")
    print("    d <num>        - Delete field by number (e.g., 'd 3')")
    print("    d <num1,num2>  - Delete multiple fields (e.g., 'd 1,3,5')")
    print("    e <num>        - Edit field by number (e.g., 'e 2')")
    print("    r <num> <name> - Rename field (e.g., 'r 2 movie_title')")
    print("    done           - Finish editing")
    print()

    schema = merged_schema.copy()
    schema["fields"] = [f.copy() for f in merged_schema.get("fields", [])]

    while True:
        display_final_schema(schema, show_header=False)

        cmd = input("  Command (or 'done'): ").strip().lower()

        if cmd in ("done", "d one", ""):
            if cmd == "":
                confirm = input("  Press Enter again to confirm, or type a command: ").strip()
                if confirm == "":
                    break
                cmd = confirm.lower()
            else:
                break

        parts = cmd.split(maxsplit=2)
        action = parts[0] if parts else ""

        if action == "d" and len(parts) >= 2:
            # Delete field(s)
            try:
                indices = [int(x.strip()) - 1 for x in parts[1].split(",")]
                # Sort in reverse to delete from end first
                indices = sorted(set(indices), reverse=True)
                deleted = []
                for idx in indices:
                    if 0 <= idx < len(schema["fields"]):
                        deleted.append(schema["fields"][idx]["name"])
                        del schema["fields"][idx]
                if deleted:
                    print(f"  Deleted: {', '.join(deleted)}")
                else:
                    print("  No valid fields to delete.")
            except ValueError:
                print("  Invalid field number(s). Use 'd <num>' or 'd <num1,num2,...>'")

        elif action == "e" and len(parts) >= 2:
            # Edit field
            try:
                idx = int(parts[1]) - 1
                if 0 <= idx < len(schema["fields"]):
                    field = schema["fields"][idx]
                    print(f"\n  Editing field: {field.get('name')}")
                    print(f"  Current values:")
                    print(f"    Name: {field.get('name')}")
                    print(f"    Type: {field.get('type')}")
                    print(f"    Required: {field.get('required')}")
                    print(f"    Description: {field.get('description')}")
                    print()
                    print("  Enter new values (press Enter to keep current):")

                    new_name = input(f"    Name [{field.get('name')}]: ").strip()
                    if new_name:
                        field["name"] = new_name

                    new_type = input(f"    Type [{field.get('type')}]: ").strip()
                    if new_type:
                        field["type"] = new_type

                    new_req = input(f"    Required (true/false) [{field.get('required')}]: ").strip().lower()
                    if new_req in ("true", "t", "yes", "y"):
                        field["required"] = True
                    elif new_req in ("false", "f", "no", "n"):
                        field["required"] = False

                    new_desc = input(f"    Description [{field.get('description', '')}]: ").strip()
                    if new_desc:
                        field["description"] = new_desc

                    print(f"  Updated field: {field.get('name')}")
                else:
                    print(f"  Invalid field number. Use 1-{len(schema['fields'])}")
            except ValueError:
                print("  Invalid field number. Use 'e <num>'")

        elif action == "r" and len(parts) >= 3:
            # Rename field
            try:
                idx = int(parts[1]) - 1
                new_name = parts[2]
                if 0 <= idx < len(schema["fields"]):
                    old_name = schema["fields"][idx]["name"]
                    schema["fields"][idx]["name"] = new_name
                    print(f"  Renamed: {old_name} → {new_name}")
                else:
                    print(f"  Invalid field number. Use 1-{len(schema['fields'])}")
            except ValueError:
                print("  Invalid field number. Use 'r <num> <new_name>'")

        else:
            print("  Unknown command. Use 'd', 'e', 'r', or 'done'.")

    return schema


# -------------------------
# Step 7: URL Helpers
# -------------------------

def resolve_url(base_url: str, link: str) -> str:
    """Resolve a potentially relative URL against a base URL."""
    return urljoin(base_url, link)


def is_valid_drill_link(link: str, base_url: str) -> bool:
    """Check if a link is valid for drilling deeper."""
    if not link:
        return False
    # Skip fragments, javascript, mailto, etc.
    if link.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
        return False
    # Skip if it resolves to the same page
    resolved = resolve_url(base_url, link)
    # Remove trailing slashes and fragments for comparison
    base_normalized = base_url.rstrip('/').split('#')[0].split('?')[0]
    resolved_normalized = resolved.rstrip('/').split('#')[0].split('?')[0]
    if base_normalized == resolved_normalized:
        return False
    return True


def get_resolved_links(base_url: str, link_samples: list) -> list:
    """Resolve all links to absolute URLs, filtering out invalid ones."""
    result = []
    for link in link_samples:
        if is_valid_drill_link(link, base_url):
            resolved = resolve_url(base_url, link)
            # Deduplicate
            if resolved not in result:
                result.append(resolved)
    return result


# -------------------------
# Step 8: Schema Merging
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


def merge_schemas(schema_chain: list) -> dict:
    """
    Merge schemas from all nesting levels into a single unified schema.
    Fields with the same name but from different levels are kept separate
    with level-prefixed names.
    """
    print_progress("Merging schemas from all levels")

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

    print_progress("Schema merge complete", f"{len(merged_fields)} unique fields")

    return {
        "item_name": final_item_name,
        "nesting_depth": len(schema_chain),
        "fields": merged_fields,
        "level_names": [s["schema"].get("catalog_type", f"level_{s['level']}") for s in schema_chain]
    }


# -------------------------
# Step 9: Interactive Mode
# -------------------------

def prompt_manual_nesting(schema: dict, link_samples: list, current_url: str, visited_urls: set) -> tuple:
    """
    Interactive mode: Ask user if they want to drill deeper.
    Returns (should_continue: bool, selected_url: str or None)
    """
    if not link_samples:
        print("  No links found on this page. Cannot drill deeper.")
        return False, None

    resolved_links = get_resolved_links(current_url, link_samples)

    # Filter out already visited URLs
    unvisited_links = [link for link in resolved_links if link not in visited_urls]

    if not unvisited_links:
        print("  All links on this page have already been visited.")
        return False, None

    print("\n  Is this the final detail level, or should we drill deeper?")
    response = input("  Enter 'done' if this is the final level, or 'more' to go deeper: ").strip().lower()

    if response in ("done", "d", ""):
        return False, None

    print("\n  Available links (excluding already visited):")
    for i, link in enumerate(unvisited_links, 1):
        display_link = link if len(link) <= 70 else link[:67] + "..."
        print(f"    {i}. {display_link}")

    while True:
        choice = input(f"\n  Select a link (1-{len(unvisited_links)}): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(unvisited_links):
                selected = unvisited_links[idx]
                print(f"\n  Selected: {selected}")
                return True, selected
            else:
                print(f"  Please enter a number between 1 and {len(unvisited_links)}")
        except ValueError:
            print("  Please enter a valid number")


# -------------------------
# Step 10: Automatic Mode
# -------------------------

def auto_detect_nesting(url: str, dom_summary: dict, schema: dict, link_samples: list, visited_urls: set) -> tuple:
    """
    Automatic mode: Use LLM to detect if we should drill deeper.
    Returns (should_continue: bool, selected_url: str or None)
    """
    if not link_samples:
        print_progress("No links found", "treating as final level")
        return False, None

    resolved_links = get_resolved_links(url, link_samples)

    # Filter out already visited URLs
    unvisited_links = [link for link in resolved_links if link not in visited_urls]

    if not unvisited_links:
        print_progress("All links already visited", "treating as final level")
        return False, None

    nesting_result = analyze_nesting(url, dom_summary, schema, unvisited_links)

    is_final = nesting_result.get("is_final_level", True)
    reasoning = nesting_result.get("reasoning", "")

    print_progress("Nesting analysis complete")
    print(f"      Final level: {is_final}")
    print(f"      Reason: {reasoning}")

    if is_final:
        return False, None

    link_index = nesting_result.get("recommended_link_index")
    if link_index is None:
        print_progress("Warning", "No link index provided, treating as final level")
        return False, None

    # Ensure link_index is an integer
    try:
        link_index = int(link_index)
    except (TypeError, ValueError):
        print_progress("Warning", f"Invalid link index type: {link_index}, treating as final level")
        return False, None

    if link_index < 0 or link_index >= len(unvisited_links):
        print_progress("Warning", f"Link index {link_index} out of range (0-{len(unvisited_links)-1}), treating as final level")
        return False, None

    selected_url = unvisited_links[link_index]
    link_reason = nesting_result.get("recommended_link_reason", "")

    print_progress("Drilling deeper")
    print(f"      Index: {link_index}")
    print(f"      URL: {selected_url}")
    if link_reason:
        print(f"      Reason: {link_reason}")

    return True, selected_url


# -------------------------
# Main Entry Point
# -------------------------

def run_discovery(start_url: str, mode: str = "auto", max_depth: int = 10):
    """
    Main discovery loop.
    mode: "auto" for automatic discovery, "interactive" for manual guidance
    """
    current_url = start_url
    schema_chain = []
    visited_urls = set()
    level = 1

    while level <= max_depth:
        # Check for cycles
        if current_url in visited_urls:
            print_progress("Warning", f"URL already visited, stopping to avoid cycle: {current_url}")
            break

        visited_urls.add(current_url)
        print_level(level, current_url)

        # Fetch and analyze page
        schema, dom_summary, link_samples = infer_catalog_schema(current_url)
        schema_chain.append({
            "level": level,
            "url": current_url,
            "schema": schema
        })

        # Display current schema
        display_schema(schema)

        # Check if this is a catalog at all
        if not schema.get("is_catalog"):
            print_progress("Not a catalog page", "stopping discovery")
            break

        # Determine if we should go deeper
        if mode == "auto":
            should_continue, next_url = auto_detect_nesting(
                current_url, dom_summary, schema, link_samples, visited_urls
            )
        else:
            should_continue, next_url = prompt_manual_nesting(
                schema, link_samples, current_url, visited_urls
            )

        if not should_continue:
            print_progress("Reached final level", "discovery complete")
            break

        current_url = next_url
        level += 1

    if level > max_depth:
        print_progress("Warning", f"Reached maximum depth ({max_depth})")

    # Merge all schemas
    print_section("Building Final Schema")
    merged_schema = merge_schemas(schema_chain)
    display_final_schema(merged_schema)

    # Allow user to edit the schema
    print("  Would you like to edit the schema? (delete/rename/modify fields)")
    edit_choice = input("  Enter 'yes' to edit or press Enter to skip: ").strip().lower()

    if edit_choice in ("yes", "y"):
        merged_schema = edit_schema_interactive(merged_schema)
        print_section("Final Schema After Editing")
        display_final_schema(merged_schema, show_header=False)

    return {
        "root_url": start_url,
        "final_url": schema_chain[-1]["url"] if schema_chain else start_url,
        "mode": mode,
        "schema_chain": schema_chain,
        "merged_schema": merged_schema
    }


# -------------------------
# CLI
# -------------------------

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║          CATALOG SCHEMA DISCOVERY TOOL                       ║
║          Automatically discover nested catalog structures    ║
╚══════════════════════════════════════════════════════════════╝
    """)

    test_url = input("Enter root URL: ").strip()

    print("\nDiscovery Mode:")
    print("  1. Automatic Discovery (recommended)")
    print("     AI automatically detects nesting and follows the most likely path")
    print("  2. Interactive Discovery")
    print("     You manually choose which links to follow at each level")

    mode_choice = input("\nSelect mode [1]: ").strip()
    mode = "interactive" if mode_choice == "2" else "auto"

    print(f"\n  Starting {mode} discovery...")

    result = run_discovery(test_url, mode=mode)

    # Save results
    os.makedirs("results", exist_ok=True)
    safe_filename = re.sub(r'[^\w\-.]', '_', test_url)[:100]
    filename = f"results/{safe_filename}.json"

    with open(filename, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n  Results saved to: {filename}")
    print("\nDiscovery complete!")
