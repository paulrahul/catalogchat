"""
CLI interface for the Catalog Schema Discovery Tool.
This module provides the command-line interface and user interaction.
"""

import json
import re
import os

from prototype.schema import discover, build_extraction_plan, correct_field_selector, summarize_dom, find_value_in_html
from prototype.scraper import scrape_sample
from prototype.util import fetch_html, set_model, get_model, AVAILABLE_MODELS


# -------------------------
# Progress Indicators (CLI-specific)
# -------------------------

def print_progress(step: str, detail: str = ""):
    """Print a progress indicator."""
    prefix = f"  -> {step}"
    if detail:
        print(f"{prefix}: {detail}")
    else:
        print(prefix)


def print_section(title: str):
    """Print a section header."""
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}")


def print_level(level: int, url: str):
    """Print the current nesting level."""
    print(f"\n{'=' * 60}")
    print(f"  LEVEL {level}: Analyzing page")
    print(f"  URL: {url}")
    print(f"{'=' * 60}")


# -------------------------
# Display Functions (CLI-specific)
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
        print(f"\n{'#' * 60}")
        print("  FINAL MERGED SCHEMA")
        print(f"{'#' * 60}")

    print(f"\n  Item Name: {merged_schema.get('item_name')}")
    print(f"  Nesting Depth: {merged_schema.get('nesting_depth')} levels")
    print(f"  Levels: {' -> '.join(merged_schema.get('level_names', []))}")
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


def display_extraction_plan(plan: dict):
    """Display the extraction plan in a user-friendly format."""
    print(f"\n{'*' * 60}")
    print("  EXTRACTION PLAN")
    print(f"{'*' * 60}")

    summary = plan.get("summary", {})
    print(f"\n  Path: {summary.get('path')}")
    print(f"  Depth: {summary.get('depth')} levels")
    print(f"  Total Fields: {summary.get('total_fields')}")
    print(f"  Item Name: {summary.get('item_name')}")

    print(f"\n  Navigation Path:")
    for level in plan.get("navigation_path", []):
        level_num = level.get("level")
        catalog_type = level.get("catalog_type") or f"Level {level_num}"
        is_final = level.get("is_final_level", True)

        print(f"\n    Level {level_num}: {catalog_type}")
        print(f"      Sample URL: {level.get('sample_url')}")
        print(f"      Item container: {level.get('item_container_selector') or 'N/A'}")

        if not is_final:
            print(f"      Drill-down link: {level.get('drill_down_link_selector') or 'N/A'}")
        else:
            print(f"      (Final level - no further drilling)")

        if level.get("fields"):
            print(f"      Fields at this level:")
            for field in level.get("fields", []):
                selector = field.get("selector") or "N/A"
                attr = field.get("attribute", "text")
                print(f"        - {field.get('name')}: {selector} [{attr}]")

    print()


def display_sample_data(sample_result: dict):
    """Display sample scraped data in a table format."""
    print(f"\n{'~' * 60}")
    print("  SAMPLE DATA PREVIEW")
    print(f"{'~' * 60}")

    target_level = sample_result.get("target_level")
    rows = sample_result.get("rows", [])
    errors = sample_result.get("errors", [])
    field_names = sample_result.get("field_names", [])

    print(f"\n  Target Level: {target_level}")
    print(f"  Rows: {len(rows)}")
    print(f"  Fields: {len(field_names)}")

    if errors:
        print(f"\n  Warnings/Errors:")
        for err in errors[:5]:  # Show at most 5 errors
            print(f"    - {err}")

    if not rows:
        print("\n  No data extracted. Check that the selectors are correct.")
        return

    if not field_names:
        print("\n  No fields defined for the levels.")
        return

    # Calculate column widths (cap at 30 chars per column for readability)
    max_col_width = 30
    col_widths = {}
    for name in field_names:
        max_width = len(name)
        for row in rows:
            value = str(row.get(name) or "")
            max_width = max(max_width, min(len(value), max_col_width))
        col_widths[name] = min(max_width + 2, max_col_width + 2)

    # Print header
    print()
    header = "  "
    separator = "  "
    for name in field_names:
        display_name = name[:max_col_width] if len(name) > max_col_width else name
        header += display_name.ljust(col_widths[name])
        separator += "-" * (col_widths[name] - 1) + " "
    print(header)
    print(separator)

    # Print rows
    for i, row in enumerate(rows, 1):
        line = "  "
        for name in field_names:
            value = str(row.get(name) or "")
            # Truncate long values
            if len(value) > max_col_width - 3:
                value = value[:max_col_width - 3] + "..."
            line += value.ljust(col_widths[name])
        print(line)

    print()


# -------------------------
# Field Correction (CLI-specific)
# -------------------------

def collect_field_corrections(
    sample_result: dict,
    extraction_plan: dict,
    on_progress=None
) -> dict:
    """
    Interactive loop to collect user feedback on wrong fields and correct them using AI.

    Args:
        sample_result: The sample scrape result with rows and field_names
        extraction_plan: The current extraction plan to update
        on_progress: Optional progress callback

    Returns:
        Updated extraction plan with corrected selectors
    """
    rows = sample_result.get("rows", [])
    field_names = sample_result.get("field_names", [])

    if not rows or not field_names:
        print("  No data to correct.")
        return extraction_plan

    # We need DOM summaries for each level to help AI correct selectors
    # Cache them as we fetch
    dom_cache = {}

    while True:
        print_section("Field Correction")
        print("  Do any fields have incorrect data?")
        print("  Enter field numbers to correct (comma-separated), or 'done' to finish.")
        print()

        # Show numbered field list with sample values
        for i, name in enumerate(field_names, 1):
            sample_value = rows[0].get(name) if rows else None
            sample_str = str(sample_value)[:40] if sample_value else "(empty)"
            if len(str(sample_value or "")) > 40:
                sample_str += "..."
            print(f"    {i}. {name}: {sample_str}")

        choice = input("\n  Fields to correct (e.g., '1,3' or 'done'): ").strip().lower()

        if choice in ("done", "d", ""):
            break

        # Parse field numbers
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
            selected_fields = [field_names[i] for i in indices if 0 <= i < len(field_names)]
        except (ValueError, IndexError):
            print("  Invalid input. Use numbers like '1,3' or 'done'.")
            continue

        if not selected_fields:
            print("  No valid fields selected.")
            continue

        # Process each selected field
        for field_name in selected_fields:
            print(f"\n  Correcting field: {field_name}")

            # Find current value
            current_value = rows[0].get(field_name) if rows else None
            print(f"  Current value: {current_value or '(empty)'}")

            # Get user feedback
            user_feedback = input("  What's wrong with this value? ").strip()
            if not user_feedback:
                print("  Skipping (no feedback provided).")
                continue

            expected_value = input("  What value did you expect? (example) ").strip()
            if not expected_value:
                print("  Skipping (no expected value provided).")
                continue

            # Find which level this field belongs to
            field_level = None
            field_info = None
            for level_plan in extraction_plan.get("navigation_path", []):
                for field in level_plan.get("fields", []):
                    # Check both original name and mapped name
                    level_name = level_plan.get("level_name") or level_plan.get("catalog_type")
                    mapping_key = f"{level_name}:{field.get('name')}"
                    mapped_name = extraction_plan.get("field_name_mapping", {}).get(mapping_key, field.get("name"))

                    if mapped_name == field_name or field.get("name") == field_name:
                        field_level = level_plan
                        field_info = field
                        break
                if field_info:
                    break

            if not field_level or not field_info:
                print(f"  Could not find field '{field_name}' in extraction plan.")
                continue

            # Get DOM summary and HTML for this level (fetch if not cached)
            level_url = field_level.get("sample_url")
            if level_url not in dom_cache:
                print(f"  Fetching page to analyze DOM...")
                try:
                    html = fetch_html(level_url)
                    dom_cache[level_url] = {
                        "html": html,
                        "dom_summary": summarize_dom(html)
                    }
                except Exception as e:
                    print(f"  Error fetching page: {e}")
                    continue

            cached = dom_cache[level_url]
            dom_summary = cached["dom_summary"]
            html = cached["html"]
            item_container = field_level.get("item_container_selector", "")

            # Search for the expected value in the HTML
            print(f"  Searching for '{expected_value}' in the page...")
            found_elements = find_value_in_html(html, expected_value)

            if found_elements:
                print(f"  Found {len(found_elements)} element(s) containing the expected value:")
                for i, elem in enumerate(found_elements[:3], 1):  # Show first 3
                    selector_hint = elem.get("selector_hint", "?")
                    text_preview = elem.get("text_preview", "")[:50]
                    print(f"    {i}. {selector_hint}: \"{text_preview}...\"")
            else:
                print(f"  Expected value not found in page (may be formatted differently)")

            print(f"  Asking AI to suggest a better selector...")

            # Call AI to correct the selector
            try:
                correction = correct_field_selector(
                    field_name=field_info.get("name"),
                    current_container_selector=field_info.get("container_selector"),
                    current_selector=field_info.get("selector"),
                    current_attribute=field_info.get("attribute", "text"),
                    current_value=str(current_value) if current_value else "",
                    user_feedback=user_feedback,
                    expected_value=expected_value,
                    dom_summary=dom_summary,
                    item_container_selector=item_container,
                    found_elements=found_elements,
                    on_progress=on_progress
                )

                new_container_selector = correction.get("corrected_container_selector")
                new_selector = correction.get("corrected_selector")
                new_attribute = correction.get("corrected_attribute", "text")
                reasoning = correction.get("reasoning", "")
                confidence = correction.get("confidence", 0)

                print(f"\n  AI Suggestion:")
                print(f"    Container selector: {new_container_selector or '(use item container)'}")
                print(f"    Field selector: {new_selector or '(none)'}")
                print(f"    Attribute: {new_attribute}")
                print(f"    Confidence: {confidence}")
                print(f"    Reasoning: {reasoning}")

                if new_selector:
                    apply = input("\n  Apply this correction? (yes/no) [yes]: ").strip().lower()
                    if apply in ("yes", "y", ""):
                        # Update the field in navigation_path
                        field_info["container_selector"] = new_container_selector
                        field_info["selector"] = new_selector
                        field_info["attribute"] = new_attribute

                        # Also update the field in extraction_plan["fields"] (the merged schema fields)
                        # This ensures the correction is saved to the results JSON
                        for ext_field in extraction_plan.get("fields", []):
                            if ext_field.get("name") == field_name:
                                ext_field["container_selector"] = new_container_selector
                                ext_field["selector"] = new_selector
                                ext_field["attribute"] = new_attribute
                                break

                        print(f"  Updated selectors for '{field_name}'.")
                    else:
                        print("  Correction skipped.")
                else:
                    print("  AI could not suggest a better selector.")

            except Exception as e:
                print(f"  Error getting AI correction: {e}")

        # Ask if user wants to re-scrape to verify
        rescrape = input("\n  Re-scrape to verify corrections? (yes/no) [yes]: ").strip().lower()
        if rescrape in ("yes", "y", ""):
            return extraction_plan  # Return updated plan so caller can re-scrape

    return extraction_plan


# -------------------------
# Schema Editor (CLI-specific)
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
                    print(f"  Renamed: {old_name} -> {new_name}")
                else:
                    print(f"  Invalid field number. Use 1-{len(schema['fields'])}")
            except ValueError:
                print("  Invalid field number. Use 'r <num> <new_name>'")

        else:
            print("  Unknown command. Use 'd', 'e', 'r', or 'done'.")

    return schema


# -------------------------
# Interactive Link Selection (CLI-specific)
# -------------------------

def cli_select_next_link(url: str, dom_summary: dict, schema: dict, unvisited_links: list, visited_urls: set) -> tuple:
    """
    Interactive mode: Ask user if they want to drill deeper.
    This is the CLI callback for discover()'s select_next_link parameter.

    Returns:
        (should_continue: bool, selected_url: str or None, nesting_info: dict or None)
    """
    if not unvisited_links:
        print("  No unvisited links found on this page.")
        return False, None, {"is_final_level": True, "reasoning": "No links available"}

    print("\n  Is this the final detail level, or should we drill deeper?")
    print("    1. Done - This is the final level (extract detail fields)")
    print("    2. More - Drill deeper into nested content")
    response = input("  Select [1]: ").strip().lower()

    if response in ("1", "done", "d", ""):
        # User confirmed this is final - trigger re-analysis with detail prompt
        return False, None, {
            "is_final_level": True,
            "user_confirmed_final": True,
            "reasoning": "User confirmed this is the final detail level"
        }

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
                nesting_info = {
                    "is_final_level": False,
                    "reasoning": "User selected to drill deeper",
                    "recommended_link_index": idx,
                    "drill_down_link_selector": None  # Not available in interactive mode
                }
                return True, selected, nesting_info
            else:
                print(f"  Please enter a number between 1 and {len(unvisited_links)}")
        except ValueError:
            print("  Please enter a valid number")


# -------------------------
# CLI Progress Callback
# -------------------------

class CLIProgressTracker:
    """Tracks progress and displays it in CLI format."""

    def __init__(self):
        self.current_level = 0
        self.current_url = ""

    def on_progress(self, step: str, detail: str = ""):
        """Progress callback for backend functions."""
        # Handle level changes specially
        if step.startswith("Level "):
            try:
                self.current_level = int(step.split()[1])
                self.current_url = detail
                print_level(self.current_level, detail)
                return
            except (IndexError, ValueError):
                pass

        print_progress(step, detail)

    def on_schema_inferred(self, schema: dict):
        """Called when a schema is inferred."""
        display_schema(schema)


# -------------------------
# Main Discovery Loop (CLI-specific wrapper)
# -------------------------

def cli_confirm_drilling(nesting_info: dict, recommended_url: str) -> str:
    """
    Ask user to confirm drilling deeper in auto mode.

    Args:
        nesting_info: The LLM's nesting analysis result
        recommended_url: The URL the LLM recommends drilling into

    Returns:
        "continue" to proceed, "final" to mark current as final level, "stop" to stop
    """
    print_section("AI Recommendation")

    reasoning = nesting_info.get("reasoning", "No reasoning provided")
    link_reason = nesting_info.get("recommended_link_reason", "")
    drill_selector = nesting_info.get("drill_down_link_selector", "N/A")

    print(f"  The AI thinks this page has nested content to explore.")
    print(f"\n  Reasoning: {reasoning}")
    if link_reason:
        print(f"  Link choice: {link_reason}")
    print(f"  Drill-down selector: {drill_selector}")
    print(f"\n  Recommended next URL:")
    print(f"    {recommended_url}")

    print("\n  Options:")
    print("    1. Continue - Follow the recommended link (default)")
    print("    2. Final   - This IS the final level, extract detail fields here")
    print("    3. Stop    - Stop discovery here")

    choice = input("\n  Select [1]: ").strip().lower()

    if choice in ("2", "final", "f"):
        return "final"
    elif choice in ("3", "stop", "s"):
        return "stop"
    else:
        return "continue"


def run_discovery_cli(start_url: str, mode: str = "auto", max_depth: int = 10) -> dict:
    """
    Run discovery with CLI output.

    Args:
        start_url: The URL to start from
        mode: "auto" or "interactive"
        max_depth: Maximum nesting depth

    Returns:
        Discovery result dict
    """
    tracker = CLIProgressTracker()

    def on_schema_inferred(level, url, schema):
        """Called after each page's schema is inferred."""
        display_schema(schema)

    if mode == "interactive":
        # Interactive mode: user selects links
        result = discover(
            start_url,
            max_depth=max_depth,
            on_progress=tracker.on_progress,
            on_schema_inferred=on_schema_inferred,
            select_next_link=cli_select_next_link
        )
    else:
        # Auto mode: LLM selects links with user confirmation
        result = discover(
            start_url,
            max_depth=max_depth,
            on_progress=tracker.on_progress,
            on_schema_inferred=on_schema_inferred,
            confirm_drilling=cli_confirm_drilling
        )

    print_section("Building Final Schema")
    return result


# -------------------------
# Model Selection (CLI-specific)
# -------------------------

def select_model_interactive():
    """Let user select which LLM model to use."""
    print_section("Model Selection")
    print("  Select the AI model to use for schema inference:")
    print()

    for i, (model_id, description) in enumerate(AVAILABLE_MODELS, 1):
        print(f"    {i}. {description}")

    print()
    choice = input("  Select model [1]: ").strip()

    try:
        idx = int(choice) - 1 if choice else 0
        if 0 <= idx < len(AVAILABLE_MODELS):
            model_id, description = AVAILABLE_MODELS[idx]
            set_model(model_id)
            print(f"\n  Using model: {model_id}")
            return
    except ValueError:
        pass

    # Default to first option
    model_id, _ = AVAILABLE_MODELS[0]
    set_model(model_id)
    print(f"\n  Using default model: {model_id}")


# -------------------------
# Result Caching
# -------------------------

def get_result_filename(url: str) -> str:
    """Get the filename for a URL's result."""
    safe_filename = re.sub(r'[^\w\-.]', '_', url)[:100]
    return f"results/{safe_filename}.json"


def load_existing_result(url: str) -> dict | None:
    """Load existing result for a URL if it exists."""
    filename = get_result_filename(url)
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None


def check_and_prompt_reuse(url: str) -> dict | None:
    """
    Check if result exists for URL and prompt user to reuse or rescan.
    Returns the existing result if user wants to reuse, None otherwise.
    """
    existing = load_existing_result(url)
    if existing is None:
        return None

    print_section("Existing Result Found")
    print(f"  A previous scan result exists for this URL.")

    # Show summary of existing result
    merged = existing.get("merged_schema", {})
    print(f"\n  Previous scan summary:")
    print(f"    Item Name: {merged.get('item_name')}")
    print(f"    Nesting Depth: {merged.get('nesting_depth')} levels")
    print(f"    Fields: {len(merged.get('fields', []))}")
    print(f"    Path: {' -> '.join(merged.get('level_names', []))}")

    print("\n  Would you like to:")
    print("    1. Reuse existing result (recommended)")
    print("    2. Scan afresh")

    choice = input("\n  Select [1]: ").strip()

    if choice == "2":
        print("\n  Starting fresh scan...")
        return None

    print("\n  Reusing existing result...")
    return existing


# -------------------------
# CLI Entry Point
# -------------------------

if __name__ == "__main__":
    print("""
+==============================================================+
|          CATALOG SCHEMA DISCOVERY TOOL                       |
|          Automatically discover nested catalog structures    |
+==============================================================+
    """)

    # Let user select model
    select_model_interactive()

    test_url = input("\nEnter root URL: ").strip()

    # Check for existing result
    result = check_and_prompt_reuse(test_url)

    if result is None:
        # No existing result or user wants fresh scan
        print("\nDiscovery Mode:")
        print("  1. Automatic Discovery (recommended)")
        print("     AI automatically detects nesting and follows the most likely path")
        print("  2. Interactive Discovery")
        print("     You manually choose which links to follow at each level")

        mode_choice = input("\nSelect mode [1]: ").strip()
        mode = "interactive" if mode_choice == "2" else "auto"

        print(f"\n  Starting {mode} discovery...")

        result = run_discovery_cli(test_url, mode=mode)

    # Display final schema
    display_final_schema(result["merged_schema"])

    # Allow user to edit the schema
    print("  Would you like to edit the schema? (delete/rename/modify fields)")
    edit_choice = input("  Enter 'yes' to edit or press Enter to skip: ").strip().lower()

    if edit_choice in ("yes", "y"):
        result["merged_schema"] = edit_schema_interactive(result["merged_schema"])
        print_section("Final Schema After Editing")
        display_final_schema(result["merged_schema"], show_header=False)

    # Build and display extraction plan
    extraction_plan = build_extraction_plan(result)
    display_extraction_plan(extraction_plan)

    # Add extraction plan to result
    result["extraction_plan"] = extraction_plan

    # Offer to show sample data
    num_levels = len(extraction_plan.get("navigation_path", []))
    print("  Would you like to see sample scraped data?")
    sample_choice = input("  Enter 'yes' to preview sample data or press Enter to skip: ").strip().lower()

    sample_data = None  # Will store the final sample result

    if sample_choice in ("yes", "y"):
        while True:
            # If multiple levels, let user choose target depth
            if num_levels > 1:
                print(f"\n  How deep to scrape? (1-{num_levels})")
                print("  (Scrapes from level 1 down to the selected level,")
                print("   carrying parent-level fields as context)")
                print()
                for lp in extraction_plan.get("navigation_path", []):
                    lnum = lp.get("level")
                    ltype = lp.get("catalog_type") or f"Level {lnum}"
                    print(f"    {lnum}. {ltype}")

                level_choice = input(f"\n  Select target level [{num_levels}]: ").strip()
                try:
                    target_level = int(level_choice) if level_choice else num_levels
                except ValueError:
                    target_level = num_levels
            else:
                target_level = 1

            # Scrape and correction loop
            while True:
                print(f"\n  Scraping sample data (levels 1-{target_level})...")
                sample_result = scrape_sample(
                    extraction_plan,
                    target_level=target_level,
                    max_total_rows=1,
                    on_progress=print_progress
                )
                display_sample_data(sample_result)

                # Store the sample data (keep the last one scraped)
                sample_data = sample_result

                # Ask if data looks correct
                if sample_result.get("rows"):
                    print("  Does the extracted data look correct?")
                    correct_choice = input("  Enter 'yes' if correct, or 'fix' to correct fields: ").strip().lower()

                    if correct_choice in ("fix", "f", "no", "n"):
                        # Run field correction
                        extraction_plan = collect_field_corrections(
                            sample_result,
                            extraction_plan,
                            on_progress=print_progress
                        )
                        # Update the extraction plan in result
                        result["extraction_plan"] = extraction_plan
                        # Loop to re-scrape
                        continue
                    else:
                        # Data looks good - ask if user wants more rows
                        while True:
                            print("\n  Would you like to fetch more sample rows?")
                            more_choice = input("  Enter exact number of total rows to fetch, or 'done' to finish: ").strip().lower()

                            if more_choice in ("done", "d", ""):
                                break

                            try:
                                num_rows = int(more_choice)
                                if num_rows <= 0:
                                    print("  Please enter a positive number.")
                                    continue

                                print(f"\n  Fetching exactly {num_rows} rows (levels 1-{target_level})...")
                                sample_result = scrape_sample(
                                    extraction_plan,
                                    target_level=target_level,
                                    max_total_rows=num_rows,
                                    on_progress=print_progress
                                )
                                display_sample_data(sample_result)

                                # Update stored sample data
                                sample_data = sample_result

                            except ValueError:
                                print("  Invalid input. Enter a number or 'done'.")
                                continue

                        # Exit the correction loop
                        break
                else:
                    # No data extracted, exit correction loop
                    break

            # Ask if user wants to see another level
            if num_levels > 1:
                another = input("  Try a different depth? (yes/no) [no]: ").strip().lower()
                if another not in ("yes", "y"):
                    break
            else:
                break

    # Add sample data to result if scraped
    if sample_data:
        result["sample_data"] = sample_data

    # Save results
    os.makedirs("results", exist_ok=True)
    filename = get_result_filename(test_url)

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n  Results saved to: {filename}")
    print("\nDiscovery complete!")
