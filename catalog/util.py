"""
Utility functions for the catalog library.

These are stateless helper functions for HTTP, URL handling, and LLM calls.
No I/O to console - all functions work with data in/data out.
"""

import json
import os
import re
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from openai import OpenAI

# Initialize OpenAI client
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Get or create the OpenAI client."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


# Default model - can be changed by calling set_model()
_current_model = "gpt-4o-mini"

# Available models for selection
AVAILABLE_MODELS = [
    ("gpt-4o-mini", "GPT-4o Mini - Fast and cost-effective (default)"),
    ("gpt-4o", "GPT-4o - More capable, higher cost"),
    ("gpt-4-turbo", "GPT-4 Turbo - Powerful, higher cost"),
    ("o1-mini", "o1-mini - Reasoning model, slower but more thorough"),
]


def set_model(model: str) -> None:
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

    Raises:
        requests.RequestException: If the request fails
    """
    if on_progress:
        on_progress("Fetching page content", "")

    headers = {"User-Agent": "Mozilla/5.0 (schema-inference-bot)"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    if on_progress:
        on_progress("Page fetched successfully", f"{len(resp.text)} bytes")

    return resp.text


# -------------------------
# LLM Functions
# -------------------------


def call_llm(
    prompt: str, purpose: str = "", on_progress=None, model: str | None = None
) -> dict:
    """
    Call the LLM with a prompt and return parsed JSON response.

    Args:
        prompt: The prompt to send to the LLM
        purpose: Description of what this call is for (for progress reporting)
        on_progress: Optional callback(step, detail) for progress reporting
        model: Model to use (defaults to current model set by set_model())

    Returns:
        Parsed JSON response as a dict

    Raises:
        ValueError: If the LLM returns empty or invalid JSON
    """
    model_to_use = model or _current_model

    if on_progress:
        on_progress("Analyzing with AI", f"{purpose} [{model_to_use}]")

    client = _get_client()
    response = client.chat.completions.create(
        model=model_to_use,
        messages=[
            {
                "role": "system",
                "content": "You extract structured information from web pages. Always respond with valid JSON only. Do not wrap in markdown code blocks.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
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
        raise ValueError(
            f"LLM returned invalid JSON for '{purpose}': {e}\nResponse preview: {preview}"
        )


# -------------------------
# URL Helper Functions
# -------------------------


def normalize_url(url: str) -> str:
    """
    Normalize a URL for consistent identification.

    Normalizations applied:
    - Upgrade http to https
    - Remove trailing slash from path
    - Remove fragment (#...)
    - Sort query parameters alphabetically
    - Lowercase scheme and host

    Args:
        url: The URL to normalize

    Returns:
        Normalized URL string
    """
    parsed = urlparse(url)

    # Upgrade http to https
    scheme = "https" if parsed.scheme in ("http", "https") else parsed.scheme

    # Lowercase the host
    netloc = parsed.netloc.lower()

    # Remove trailing slash from path (but keep "/" for root)
    path = parsed.path.rstrip("/") or "/"

    # Sort query parameters
    query_params = parse_qsl(parsed.query)
    sorted_query = urlencode(sorted(query_params)) if query_params else ""

    # Reconstruct without fragment
    normalized = urlunparse((scheme, netloc, path, "", sorted_query, ""))

    return normalized


def url_to_hash(url: str) -> str:
    """
    Convert a URL to a short hash for use as a file key.

    Args:
        url: The URL (should be normalized first)

    Returns:
        12-character hex hash
    """
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()[:12]


def resolve_url(base_url: str, link: str) -> str:
    """Resolve a potentially relative URL against a base URL."""
    return urljoin(base_url, link)


def is_same_domain(base_url: str, candidate_url: str) -> bool:
    """Check if candidate_url is on the same domain as base_url."""
    base_parsed = urlparse(base_url)
    cand_parsed = urlparse(candidate_url)
    return base_parsed.netloc.lower() == cand_parsed.netloc.lower()


def score_drill_link(root_url: str, candidate_url: str) -> float:
    """
    Score how likely a candidate URL is to be a drill-down from root_url.

    Returns a float where higher means more likely to be a catalog item link:
    - 1.0: candidate extends root_url's path (e.g. /program/film-slug/ from /program/)
    - 0.3: same domain but a sibling/unrelated path
    - 0.0: cross-domain
    """
    root_parsed = urlparse(root_url)
    cand_parsed = urlparse(candidate_url)

    if root_parsed.netloc.lower() != cand_parsed.netloc.lower():
        return 0.0

    root_path = root_parsed.path.rstrip("/")
    cand_path = cand_parsed.path.rstrip("/")

    if cand_path.startswith(root_path + "/"):
        return 1.0

    return 0.3


def is_valid_drill_link(link: str, base_url: str) -> bool:
    """
    Check if a link is valid for drilling deeper.

    Filters out:
    - Empty links
    - Fragment-only links (#)
    - JavaScript/mailto/tel links
    - Links that resolve to the same page
    - Cross-domain links
    """
    if not link:
        return False
    # Skip fragments, javascript, mailto, etc.
    if link.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    # Skip if it resolves to the same page
    resolved = resolve_url(base_url, link)
    base_normalized = base_url.rstrip("/").split("#")[0].split("?")[0]
    resolved_normalized = resolved.rstrip("/").split("#")[0].split("?")[0]
    if base_normalized == resolved_normalized:
        return False
    # Skip cross-domain links
    if not is_same_domain(base_url, resolved):
        return False
    return True


def get_resolved_links(base_url: str, link_samples: list) -> list[str]:
    """
    Resolve all links to absolute URLs, filtering out invalid ones.

    Args:
        base_url: The base URL to resolve against
        link_samples: List of links — either str hrefs or dicts with an 'href' key

    Returns:
        List of resolved absolute URLs (deduplicated, same order as input)
    """
    result = []
    for link in link_samples:
        href = link["href"] if isinstance(link, dict) else link
        if is_valid_drill_link(href, base_url):
            resolved = resolve_url(base_url, href)
            if resolved not in result:
                result.append(resolved)
    return result


# -------------------------
# ID Generation
# -------------------------


def generate_plan_id(url: str) -> str:
    """Generate a unique ID for a catalog plan based on its root URL."""
    import hashlib
    from datetime import datetime

    # Create a hash of the URL + timestamp for uniqueness
    timestamp = datetime.utcnow().isoformat()
    hash_input = f"{url}:{timestamp}"
    hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:12]

    # Create a readable prefix from the URL
    safe_prefix = re.sub(r"[^\w\-]", "_", url)[:30]
    safe_prefix = safe_prefix.strip("_")

    return f"{safe_prefix}_{hash_value}"
