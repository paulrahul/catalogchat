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

def call_llm(prompt: str, purpose: str = "", on_progress=None) -> dict:
    """
    Call the LLM with a prompt and return parsed JSON response.

    Args:
        prompt: The prompt to send to the LLM
        purpose: Description of what this call is for (for progress reporting)
        on_progress: Optional callback(step, detail) for progress reporting

    Returns:
        Parsed JSON response as a dict
    """
    if on_progress:
        on_progress("Analyzing with AI", purpose)

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
