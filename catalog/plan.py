"""
Plan management functions for the catalog library.

These functions handle creating, loading, saving, and updating CatalogPlans.
"""

from datetime import datetime, timezone

from catalog.types import CatalogPlan
from catalog.util import generate_plan_id
from catalog.state import save_state, load_state


def create_plan(root_url: str) -> CatalogPlan:
    """
    Create a new CatalogPlan for a given root URL.

    This initializes an empty plan that can be populated through discovery.

    Args:
        root_url: The root URL of the catalog to analyze

    Returns:
        A new CatalogPlan instance
    """
    plan_id = generate_plan_id(root_url)
    now = datetime.now(timezone.utc).isoformat()

    return CatalogPlan(
        id=plan_id,
        root_url=root_url,
        item_name="Item",
        nesting_depth=0,
        level_names=[],
        fields=[],
        schema_chain=[],
        visited_urls=[],
        created_at=now,
        updated_at=now,
    )


def load_plan(plan_id: str, plans_dir: str = "plans") -> CatalogPlan | None:
    """
    Load a CatalogPlan by its ID.

    Args:
        plan_id: The ID of the plan to load
        plans_dir: Directory where plans are stored

    Returns:
        The loaded CatalogPlan, or None if not found
    """
    path = f"{plans_dir}/{plan_id}.json"
    data = load_state(path)
    if data is None:
        return None
    return CatalogPlan.from_dict(data)


def save_plan(plan: CatalogPlan, plans_dir: str = "plans") -> str:
    """
    Save a CatalogPlan to disk.

    Args:
        plan: The plan to save
        plans_dir: Directory where plans are stored

    Returns:
        The path where the plan was saved
    """
    # Update the updated_at timestamp
    plan.updated_at = datetime.now(timezone.utc).isoformat()

    path = f"{plans_dir}/{plan.id}.json"
    save_state(plan.to_dict(), path)
    return path


def update_plan(plan: CatalogPlan, **changes) -> CatalogPlan:
    """
    Update a CatalogPlan with the given changes.

    This returns a new CatalogPlan instance with the changes applied.
    The original plan is not modified.

    Args:
        plan: The plan to update
        **changes: Key-value pairs of fields to update

    Returns:
        A new CatalogPlan with the changes applied

    Example:
        updated = update_plan(plan, item_name="Movie", nesting_depth=3)
    """
    # Convert plan to dict, apply changes, convert back
    data = plan.to_dict()

    for key, value in changes.items():
        if key in data:
            data[key] = value
        else:
            raise ValueError(f"Unknown field: {key}")

    # Update timestamp
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    return CatalogPlan.from_dict(data)


def list_plans(plans_dir: str = "plans") -> list[dict]:
    """
    List all saved plans with summary info.

    Args:
        plans_dir: Directory where plans are stored

    Returns:
        List of dicts with plan summaries (id, root_url, item_name, etc.)
    """
    import os

    results = []
    if not os.path.exists(plans_dir):
        return results

    for filename in os.listdir(plans_dir):
        if filename.endswith(".json"):
            path = f"{plans_dir}/{filename}"
            data = load_state(path)
            if data:
                results.append(
                    {
                        "id": data.get("id"),
                        "root_url": data.get("root_url"),
                        "item_name": data.get("item_name"),
                        "nesting_depth": data.get("nesting_depth"),
                        "field_count": len(data.get("fields", [])),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                    }
                )

    return results


def delete_plan(plan_id: str, plans_dir: str = "plans") -> bool:
    """
    Delete a CatalogPlan by its ID.

    Args:
        plan_id: The ID of the plan to delete
        plans_dir: Directory where plans are stored

    Returns:
        True if deleted, False if not found
    """
    import os

    path = f"{plans_dir}/{plan_id}.json"
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
