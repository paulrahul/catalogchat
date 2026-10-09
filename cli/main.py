"""
CLI interface for the Catalog Schema Discovery Tool.

This module provides the command-line interface.
It uses the catalog library for all core logic.
"""

import json
import os

from catalog import (
    CatalogPlan,
    DiscoveryState,
    ExtractionPlan,
    SampleResult,
    Decision,
    DecisionType,
    create_plan,
    start_discovery,
    advance_discovery,
    build_extraction_plan,
    scrape_sample,
    apply_schema_edits,
    apply_field_fix,
    prepare_field_correction,
)
from catalog.util import set_model, get_model, AVAILABLE_MODELS, fetch_html
from catalog.schema import correct_field_selector
from catalog.state import save_state, load_state, get_result_path


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


def display_plan(plan: CatalogPlan):
    """Display the catalog plan in a user-friendly format."""
    print(f"\n{'#' * 60}")
    print("  CATALOG PLAN")
    print(f"{'#' * 60}")

    print(f"\n  Item Name: {plan.item_name}")
    print(f"  Nesting Depth: {plan.nesting_depth} levels")
    print(f"  Levels: {' -> '.join(plan.level_names)}")

    total_fields = sum(len(ls.fields) for ls in plan.schema_chain)
    print(f"\n  Fields ({total_fields} total):")

    for level_schema in plan.schema_chain:
        level_name = level_schema.catalog_type or f"Level {level_schema.level}"
        print(f"\n    [{level_name}]")
        for i, field in enumerate(level_schema.fields, 1):
            req = "required" if field.required else "optional"
            print(f"      {i}. {field.name} ({field.type}, {req})")
            if field.description:
                print(f"         {field.description}")

    print()


def display_extraction_plan(plan: ExtractionPlan):
    """Display the extraction plan in a user-friendly format."""
    print(f"\n{'*' * 60}")
    print("  EXTRACTION PLAN")
    print(f"{'*' * 60}")

    summary = plan.summary
    print(f"\n  Path: {summary.get('path')}")
    print(f"  Depth: {summary.get('depth')} levels")
    print(f"  Total Fields: {summary.get('total_fields')}")
    print(f"  Item Name: {summary.get('item_name')}")

    print(f"\n  Navigation Path:")
    for level in plan.navigation_path:
        level_num = level.level
        catalog_type = level.catalog_type or f"Level {level_num}"
        is_final = level.is_final_level

        print(f"\n    Level {level_num}: {catalog_type}")
        print(f"      Sample URL: {level.sample_url}")
        print(f"      Item container: {level.item_container_selector or 'N/A'}")

        if not is_final:
            print(f"      Drill-down link: {level.drill_down_link_selector or 'N/A'}")
        else:
            print(f"      (Final level - no further drilling)")

        if level.fields:
            print(f"      Fields at this level:")
            for field in level.fields:
                selector = field.selector or "N/A"
                attr = field.attribute or "text"
                print(f"        - {field.name}: {selector} [{attr}]")

    print()


def display_sample_data(sample: SampleResult):
    """Display sample scraped data as JSON."""
    print(f"\n{'~' * 60}")
    print("  SAMPLE DATA PREVIEW")
    print(f"{'~' * 60}")

    print(f"\n  Target Level: {sample.target_level}")
    print(f"  Rows: {len(sample.rows)}")
    print(f"  Fields: {len(sample.field_names)}")

    if sample.errors:
        print(f"\n  Warnings/Errors:")
        for err in sample.errors[:5]:
            print(f"    - {err}")

    if not sample.rows:
        print("\n  No data extracted. Check that the selectors are correct.")
        return

    if not sample.field_names:
        print("\n  No fields defined for the levels.")
        return

    # Display each row as formatted JSON
    print()
    for i, row in enumerate(sample.rows, 1):
        print(f"  --- Row {i} ---")
        print(json.dumps(row, indent=4, ensure_ascii=False))
        print()

    print()


# -------------------------
# Decision Handlers (CLI-specific)
# -------------------------


def handle_decision(decision: Decision) -> dict:
    """Handle a Decision by prompting the user for input."""
    if decision.type == DecisionType.CONFIRM_DRILLING:
        return handle_confirm_drilling(decision)
    elif decision.type == DecisionType.SELECT_LINK:
        return handle_select_link(decision)
    elif decision.type == DecisionType.FIX_FIELD:
        return handle_fix_field(decision)
    else:
        # Default: return first option
        return {"choice": decision.options[0] if decision.options else "continue"}


def handle_confirm_drilling(decision: Decision) -> dict:
    """Handle CONFIRM_DRILLING decision."""
    print_section("AI Recommendation")

    ctx = decision.context
    reasoning = ctx.get("reasoning", "No reasoning provided")
    link_reason = ctx.get("link_reason", "")
    drill_selector = ctx.get("drill_down_selector", "N/A")
    recommended_url = ctx.get("recommended_url", "")

    print(f"  AI detected nested content to explore.")
    print(f"\n  Reasoning: {reasoning}")
    if link_reason:
        print(f"  Link choice: {link_reason}")
    print(f"  Drill-down selector: {drill_selector}")
    print(f"\n  Recommended URL: {recommended_url}")

    choice = input("\n  Drill deeper? (y/n) [y]: ").strip().lower()

    if choice == "n":
        return {"choice": "final"}
    else:
        return {"choice": "continue"}


def handle_select_link(decision: Decision) -> dict:
    """Handle SELECT_LINK decision."""
    ctx = decision.context
    available_links = ctx.get("available_links", [])

    response = input("\n  Drill deeper into nested content? (y/n) [n]: ").strip().lower()

    if response != "y":
        return {"choice": "final"}

    print("\n  Available links:")
    for i, link in enumerate(available_links, 1):
        display_link = link if len(link) <= 70 else link[:67] + "..."
        print(f"    {i}. {display_link}")

    while True:
        choice = input(f"\n  Select link (1-{len(available_links)}): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(available_links):
                return {"choice": "drill", "link_index": idx}
            else:
                print(f"  Enter a number between 1 and {len(available_links)}")
        except ValueError:
            print("  Enter a valid number")


def handle_fix_field(decision: Decision) -> dict:
    """Handle FIX_FIELD decision."""
    ctx = decision.context
    issues = ctx.get("issues", [])

    print_section("Data Quality Issues")
    for issue in issues:
        print(f"  - {issue}")

    choice = input("\n  Fix field selectors? (y/n) [n]: ").strip().lower()
    if choice == "y":
        return {"choice": "fix"}
    return {"choice": "skip"}


# -------------------------
# Field Correction (CLI-specific)
# -------------------------


def collect_field_corrections(
    sample: SampleResult,
    extraction_plan: ExtractionPlan,
    on_progress=None,
) -> ExtractionPlan:
    """
    Interactive loop to collect user feedback on wrong fields and correct them using AI.

    This is a thin CLI wrapper that:
    - Displays field values and collects user input
    - Delegates to core library for field lookup, DOM analysis, and correction
    """
    rows = sample.rows
    field_names = sample.field_names

    if not rows or not field_names:
        print("  No data to correct.")
        return extraction_plan

    # Cache HTML by URL
    html_cache = {}

    while True:
        print_section("Field Correction")
        print()

        # Show numbered field list with sample values
        for i, name in enumerate(field_names, 1):
            sample_value = rows[0].get(name) if rows else None
            sample_str = str(sample_value)[:40] if sample_value else "(empty)"
            if len(str(sample_value or "")) > 40:
                sample_str += "..."
            print(f"    {i}. {name}: {sample_str}")

        choice = input("\n  Fields to fix (e.g., '1,3') or press Enter to finish: ").strip()

        if choice == "":
            break

        # Parse field numbers
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
            selected_fields = [field_names[i] for i in indices if 0 <= i < len(field_names)]
        except (ValueError, IndexError):
            print("  Invalid input. Enter field numbers like '1,3'.")
            continue

        if not selected_fields:
            print("  No valid fields selected.")
            continue

        # Process each selected field
        for field_name in selected_fields:
            print(f"\n  Correcting field: {field_name}")

            current_value = rows[0].get(field_name) if rows else None
            print(f"  Current value: {current_value or '(empty)'}")

            user_feedback = input("  What's wrong? ").strip()
            if not user_feedback:
                print("  Skipping (no feedback provided).")
                continue

            expected_value = input("  Expected value? ").strip()
            if not expected_value:
                print("  Skipping (no expected value provided).")
                continue

            # Use core library to prepare correction context
            # First, we need HTML - find which level this field belongs to
            from catalog import find_field_in_plan
            level_plan, field_info = find_field_in_plan(extraction_plan, field_name)

            if not level_plan or not field_info:
                print(f"  Could not find field '{field_name}' in extraction plan.")
                continue

            level_url = level_plan.sample_url
            if level_url not in html_cache:
                print(f"  Fetching page...")
                try:
                    html_cache[level_url] = fetch_html(level_url)
                except Exception as e:
                    print(f"  Error fetching page: {e}")
                    continue

            html = html_cache[level_url]

            # Use core library to prepare correction context
            print(f"  Analyzing page structure...")
            context = prepare_field_correction(
                extraction_plan=extraction_plan,
                field_name=field_name,
                expected_value=expected_value,
                html=html,
                on_progress=on_progress,
            )

            if not context:
                print(f"  Could not prepare correction context.")
                continue

            # Display found elements to user
            found_elements = context["found_elements"]
            if found_elements:
                print(f"  Found {len(found_elements)} element(s) matching '{expected_value}':")
                for i, elem in enumerate(found_elements[:3], 1):
                    selector_hint = elem.get("selector_hint", "?")
                    text_preview = elem.get("text_preview", "")[:50]
                    print(f"    {i}. {selector_hint}: \"{text_preview}...\"")
            else:
                print(f"  Expected value not found (may be formatted differently)")

            print(f"  Asking AI to suggest a better selector...")

            # Call AI to correct the selector (core library function)
            try:
                correction = correct_field_selector(
                    field_name=field_info.name,
                    current_container_selector=field_info.container_selector,
                    current_selector=field_info.selector,
                    current_attribute=field_info.attribute or "text",
                    current_value=str(current_value) if current_value else "",
                    user_feedback=user_feedback,
                    expected_value=expected_value,
                    dom_summary=context["dom_summary"],
                    item_container_selector=context["item_container_selector"],
                    found_elements=found_elements,
                    on_progress=on_progress,
                )

                new_container_selector = correction.get("corrected_container_selector")
                new_selector = correction.get("corrected_selector")
                new_attribute = correction.get("corrected_attribute", "text")
                reasoning = correction.get("reasoning", "")
                confidence = correction.get("confidence", 0)

                print(f"\n  AI Suggestion:")
                print(f"    Container: {new_container_selector or '(use item container)'}")
                print(f"    Selector: {new_selector or '(none)'}")
                print(f"    Attribute: {new_attribute}")
                print(f"    Confidence: {confidence}")
                print(f"    Reasoning: {reasoning}")

                if new_selector:
                    apply_choice = input("\n  Apply this fix? (y/n) [y]: ").strip().lower()
                    if apply_choice != "n":
                        # Use core library to apply the fix
                        extraction_plan = apply_field_fix(
                            extraction_plan=extraction_plan,
                            field_name=field_name,
                            fix={
                                "container_selector": new_container_selector,
                                "selector": new_selector,
                                "attribute": new_attribute,
                            },
                        )
                        print(f"  Updated '{field_name}'.")
                    else:
                        print("  Skipped.")
                else:
                    print("  AI could not suggest a better selector.")

            except Exception as e:
                print(f"  Error getting AI correction: {e}")

        # Ask if user wants to re-scrape
        rescrape = input("\n  Re-scrape to verify? (y/n) [y]: ").strip().lower()
        if rescrape != "n":
            return extraction_plan

    return extraction_plan


# -------------------------
# Schema Editor (CLI-specific)
# -------------------------


def edit_schema_interactive(plan: CatalogPlan) -> CatalogPlan:
    """Allow user to delete or rename fields from the plan.

    Fields are numbered sequentially across all levels for easy reference.
    """
    print_section("Schema Editor")
    print("  Commands:")
    print("    d <nums>       - Delete fields (e.g., 'd 1,3,5')")
    print("    r <num> <name> - Rename field (e.g., 'r 2 movie_title')")
    print()

    def _get_flat_fields():
        """Return a flat list of (level_schema, field_index, field) tuples."""
        flat = []
        for ls in plan.schema_chain:
            for fi, f in enumerate(ls.fields):
                flat.append((ls, fi, f))
        return flat

    while True:
        display_plan(plan)

        cmd = input("  Command (or press Enter to finish): ").strip()

        if cmd == "":
            break

        flat_fields = _get_flat_fields()

        # Check for rename command
        if cmd.lower().startswith("r "):
            parts = cmd.split(maxsplit=2)
            if len(parts) >= 3:
                try:
                    idx = int(parts[1]) - 1
                    new_name = parts[2]
                    if 0 <= idx < len(flat_fields):
                        _, _, field = flat_fields[idx]
                        old_name = field.name
                        field.name = new_name
                        print(f"  Renamed: {old_name} -> {new_name}")
                    else:
                        print(f"  Invalid field number. Use 1-{len(flat_fields)}")
                except ValueError:
                    print("  Invalid format. Use 'r <num> <new_name>'")
            else:
                print("  Invalid format. Use 'r <num> <new_name>'")
            continue

        # Check for delete command
        if cmd.lower().startswith("d "):
            parts = cmd.split(maxsplit=1)
            if len(parts) >= 2:
                try:
                    indices = [int(x.strip()) - 1 for x in parts[1].split(",")]
                    indices = sorted(set(indices), reverse=True)
                    deleted = []
                    for idx in indices:
                        if 0 <= idx < len(flat_fields):
                            ls, fi, field = flat_fields[idx]
                            deleted.append(field.name)
                            del ls.fields[fi]
                            # Refresh flat_fields after deletion
                            flat_fields = _get_flat_fields()
                    if deleted:
                        print(f"  Deleted: {', '.join(deleted)}")
                    else:
                        print("  No valid fields to delete.")
                except ValueError:
                    print("  Invalid format. Use 'd <nums>' (e.g., 'd 1,3,5')")
            else:
                print("  Invalid format. Use 'd <nums>' (e.g., 'd 1,3,5')")
            continue

        print("  Unknown command. Use 'd <nums>' or 'r <num> <name>'")

    return plan


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

    model_id, _ = AVAILABLE_MODELS[0]
    set_model(model_id)
    print(f"\n  Using default model: {model_id}")


# -------------------------
# Result Caching
# -------------------------


def check_and_prompt_reuse(url: str) -> CatalogPlan | None:
    """Check if result exists for URL and prompt user to reuse or rescan."""
    path = get_result_path(url)
    existing = load_state(path)
    if existing is None:
        return None

    print_section("Existing Result Found")
    print(f"  A previous scan result exists for this URL.")

    # Show summary
    plan_data = existing.get("plan", {})
    total_fields = sum(
        len(level.get("fields", []))
        for level in plan_data.get("schema_chain", [])
    )
    print(f"\n  Previous scan summary:")
    print(f"    Item Name: {plan_data.get('item_name')}")
    print(f"    Nesting Depth: {plan_data.get('nesting_depth')} levels")
    print(f"    Fields: {total_fields}")
    print(f"    Path: {' -> '.join(plan_data.get('level_names', []))}")

    print("\n  Would you like to:")
    print("    1. Reuse existing result (recommended)")
    print("    2. Scan afresh")

    choice = input("\n  Select [1]: ").strip()

    if choice == "2":
        print("\n  Starting fresh scan...")
        return None

    print("\n  Reusing existing result...")
    return CatalogPlan.from_dict(plan_data)


# -------------------------
# Main Discovery Loop (CLI-specific)
# -------------------------


def run_discovery_cli(start_url: str, mode: str = "auto", max_depth: int = 10) -> CatalogPlan:
    """Run discovery with CLI output."""
    plan = create_plan(start_url)
    state = start_discovery(plan, mode, max_depth)

    def on_progress(step: str, detail: str = ""):
        if step.startswith("Level "):
            try:
                level_num = int(step.split()[1])
                print_level(level_num, detail)
                return
            except (IndexError, ValueError):
                pass
        print_progress(step, detail)

    while not state.done:
        state, decision = advance_discovery(
            state,
            user_input=None,
            mode=mode,
            max_depth=max_depth,
            on_progress=on_progress,
        )

        if decision:
            user_input = handle_decision(decision)
            state, decision = advance_discovery(
                state,
                user_input=user_input,
                mode=mode,
                max_depth=max_depth,
                on_progress=on_progress,
            )

    print_section("Building Final Schema")
    return state.plan


# -------------------------
# CLI Entry Point
# -------------------------


def main():
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
    plan = check_and_prompt_reuse(test_url)

    if plan is None:
        # Run discovery
        print("\nDiscovery Mode:")
        print("  1. Automatic Discovery (recommended)")
        print("     AI automatically detects nesting and follows the most likely path")
        print("  2. Interactive Discovery")
        print("     You manually choose which links to follow at each level")

        mode_choice = input("\nSelect mode [1]: ").strip()
        mode = "interactive" if mode_choice == "2" else "auto"

        print(f"\n  Starting {mode} discovery...")
        plan = run_discovery_cli(test_url, mode=mode)

    # Display plan
    display_plan(plan)

    # Allow user to edit schema (delete/rename fields)
    edit_choice = input("\n  Delete or rename any fields? (y/n) [n]: ").strip().lower()
    if edit_choice == "y":
        plan = edit_schema_interactive(plan)
        print_section("Final Schema After Editing")
        display_plan(plan)

    # Build and display extraction plan
    extraction_plan = build_extraction_plan(plan)
    display_extraction_plan(extraction_plan)

    # Always scrape at the deepest (leaf) level
    num_levels = len(extraction_plan.navigation_path)
    target_level = num_levels

    sample_data = None
    num_rows = 1

    # Scrape and correction loop - always show sample data
    while True:
        print(f"\n  Scraping {num_rows} sample row(s) at deepest level...")
        sample_result = scrape_sample(
            extraction_plan,
            target_level=target_level,
            max_rows=num_rows,
            on_progress=print_progress,
        )
        display_sample_data(sample_result)
        sample_data = sample_result

        if sample_result.rows:
            # Ask if data looks correct
            correct_choice = input("  Does the data look correct? (y/n) [y]: ").strip().lower()
            if correct_choice == "n":
                extraction_plan = collect_field_corrections(
                    sample_result,
                    extraction_plan,
                    on_progress=print_progress,
                )
                continue

            # Ask if user wants more rows
            more_choice = input("  Fetch more rows? (y/n) [n]: ").strip().lower()
            if more_choice == "y":
                rows_choice = input("  How many rows? [5]: ").strip()
                try:
                    num_rows = int(rows_choice) if rows_choice else 5
                    if num_rows <= 0:
                        num_rows = 5
                except ValueError:
                    num_rows = 5
                continue
            break
        else:
            # No data extracted
            fix_choice = input("  No data extracted. Fix field selectors? (y/n) [n]: ").strip().lower()
            if fix_choice == "y":
                extraction_plan = collect_field_corrections(
                    sample_result,
                    extraction_plan,
                    on_progress=print_progress,
                )
                continue
            break

    # Save results
    os.makedirs("results", exist_ok=True)
    path = get_result_path(test_url)

    result = {
        "plan": plan.to_dict(),
        "extraction_plan": extraction_plan.to_dict(),
    }
    if sample_data:
        result["sample_data"] = sample_data.to_dict()

    save_state(result, path)

    print(f"\n  Results saved to: {path}")
    print("\nDiscovery complete!")


if __name__ == "__main__":
    main()
