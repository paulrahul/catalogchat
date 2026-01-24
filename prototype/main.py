"""
CLI interface for the Catalog Schema Discovery Tool.
This module provides the command-line interface and user interaction.
"""

import json
import re
import os

from prototype.schema import discover


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
        (should_continue: bool, selected_url: str or None)
    """
    # Display the schema first
    display_schema(schema)

    if not unvisited_links:
        print("  No unvisited links found on this page.")
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
        # Auto mode: LLM selects links
        result = discover(
            start_url,
            max_depth=max_depth,
            on_progress=tracker.on_progress,
            on_schema_inferred=on_schema_inferred
        )

    print_section("Building Final Schema")
    return result


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

    test_url = input("Enter root URL: ").strip()

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

    # Save results
    os.makedirs("results", exist_ok=True)
    safe_filename = re.sub(r'[^\w\-.]', '_', test_url)[:100]
    filename = f"results/{safe_filename}.json"

    with open(filename, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n  Results saved to: {filename}")
    print("\nDiscovery complete!")
