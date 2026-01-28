"""
Utility functions for the catalog schema discovery tool.
These are stateless helper functions for HTTP, URL handling, and LLM calls.
"""

import requests
import json
import os
from urllib.parse import urljoin
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Default model - can be changed by calling set_model()
_current_model = "gpt-4o-mini"

# Available models for selection
AVAILABLE_MODELS = [
    ("gpt-4o-mini", "GPT-4o Mini - Fast and cost-effective (default)"),
    ("gpt-4o", "GPT-4o - More capable, higher cost"),
    ("gpt-4-turbo", "GPT-4 Turbo - Powerful, higher cost"),
    ("o1-mini", "o1-mini - Reasoning model, slower but more thorough"),
]


def set_model(model: str):
    """Set the model to use for LLM calls."""
    global _current_model
    _current_model = model


def get_model() -> str:
    """Get the current model being used."""
    return _current_model


# -------------------------
# HTTP Functions
# -------------------------

def fetch_html(url: str, on_progress=None) -> str:
    """
    Fetch HTML content from a URL.

    Args:
        url: The URL to fetch
        on_progress: Optional callback(step, detail) for progress reporting

    Returns:
        The HTML content as a string
    """
    if on_progress:
        on_progress("Fetching page content", "")

    headers = {
        "User-Agent": "Mozilla/5.0 (schema-inference-bot)"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    if on_progress:
        on_progress("Page fetched successfully", f"{len(resp.text)} bytes")

    return resp.text


# -------------------------
# LLM Functions
# -------------------------

def call_llm(prompt: str, purpose: str = "", on_progress=None, model: str = None) -> dict:
    """
    Call the LLM with a prompt and return parsed JSON response.

    Args:
        prompt: The prompt to send to the LLM
        purpose: Description of what this call is for (for progress reporting)
        on_progress: Optional callback(step, detail) for progress reporting
        model: Model to use (defaults to current model set by set_model())

    Returns:
        Parsed JSON response as a dict
    """
    import re

    model_to_use = model or _current_model

    if on_progress:
        on_progress("Analyzing with AI", f"{purpose} [{model_to_use}]")

    response = client.chat.completions.create(
        model=model_to_use,
        messages=[
            {"role": "system", "content": "You extract structured information from web pages. Always respond with valid JSON only. Do not wrap in markdown code blocks."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )
    content = response.choices[0].message.content

    if not content:
        raise ValueError(f"LLM returned empty response for: {purpose}")

    # Strip markdown code blocks if present (some models wrap JSON in ```json ... ```)
    content = content.strip()
    if content.startswith("```"):
        # Remove opening code fence (with optional language identifier)
        content = re.sub(r"^```(?:json)?\s*\n?", "", content)
        # Remove closing code fence
        content = re.sub(r"\n?```\s*$", "", content)
        content = content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        # Provide more context in the error
        preview = content[:200] + "..." if len(content) > 200 else content
        raise ValueError(f"LLM returned invalid JSON for '{purpose}': {e}\nResponse preview: {preview}")


# -------------------------
# URL Helper Functions
# -------------------------

def resolve_url(base_url: str, link: str) -> str:
    """Resolve a potentially relative URL against a base URL."""
    return urljoin(base_url, link)


def is_valid_drill_link(link: str, base_url: str) -> bool:
    """
    Check if a link is valid for drilling deeper.

    Filters out:
    - Empty links
    - Fragment-only links (#)
    - JavaScript/mailto/tel links
    - Links that resolve to the same page
    """
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
    """
    Resolve all links to absolute URLs, filtering out invalid ones.

    Args:
        base_url: The base URL to resolve against
        link_samples: List of (potentially relative) links

    Returns:
        List of resolved absolute URLs (deduplicated)
    """
    result = []
    for link in link_samples:
        if is_valid_drill_link(link, base_url):
            resolved = resolve_url(base_url, link)
            # Deduplicate
            if resolved not in result:
                result.append(resolved)
    return result
