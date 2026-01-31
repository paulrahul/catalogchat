"""
State persistence functions for the catalog library.

These functions handle saving and loading state to/from disk.
They are used by adapters (CLI, API, etc.) but not by core logic.
"""

import json
import os
from typing import Any


def save_state(obj: dict | Any, path: str) -> None:
    """
    Save an object to a JSON file.

    Args:
        obj: The object to save (must be JSON-serializable or have to_dict())
        path: The file path to save to

    Raises:
        OSError: If the file cannot be written
    """
    # Ensure the directory exists
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)

    # Convert to dict if the object has a to_dict method
    if hasattr(obj, "to_dict"):
        data = obj.to_dict()
    else:
        data = obj

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_state(path: str) -> dict | None:
    """
    Load state from a JSON file.

    Args:
        path: The file path to load from

    Returns:
        The loaded dict, or None if the file doesn't exist or is invalid
    """
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def state_exists(path: str) -> bool:
    """
    Check if a state file exists.

    Args:
        path: The file path to check

    Returns:
        True if the file exists, False otherwise
    """
    return os.path.exists(path)


def delete_state(path: str) -> bool:
    """
    Delete a state file.

    Args:
        path: The file path to delete

    Returns:
        True if deleted, False if not found
    """
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def get_result_path(url: str, results_dir: str = "results") -> str:
    """
    Get the file path for storing results for a given URL.

    Args:
        url: The URL to generate a path for
        results_dir: The directory to store results in

    Returns:
        A safe file path based on the URL
    """
    import re

    safe_filename = re.sub(r"[^\w\-.]", "_", url)[:100]
    file_name = f"{results_dir}/{safe_filename}.json"
    return file_name
