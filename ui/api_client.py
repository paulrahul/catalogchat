"""
HTTP client for communicating with the CatalogChat API.
"""
import logging
from pathlib import Path

import httpx
from typing import Optional, Any
from dataclasses import dataclass

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

_file_handler = logging.FileHandler(LOG_DIR / "api_client.log")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
)
logger.addHandler(_file_handler)


@dataclass
class DiscoveryState:
    """Discovery state from API response."""
    current_url: str
    current_level: int
    visited_urls: list[str]
    done: bool
    has_pending_decision: bool


@dataclass
class Decision:
    """Decision object from API response."""
    id: str
    type: str
    step: str
    prompt: str
    options: list[str]
    context: dict[str, Any]


@dataclass
class DiscoveryResponse:
    """Response from /plan/discovery endpoint."""
    url: str
    state: Optional[DiscoveryState]
    decision: Optional[Decision]
    done: bool
    plan: Optional[dict]

    @classmethod
    def from_dict(cls, data: dict) -> "DiscoveryResponse":
        state = None
        if data.get("state"):
            state = DiscoveryState(
                current_url=data["state"].get("current_url", ""),
                current_level=data["state"].get("current_level", 1),
                visited_urls=data["state"].get("visited_urls", []),
                done=data["state"].get("done", False),
                has_pending_decision=data["state"].get("has_pending_decision", False),
            )

        decision = None
        if data.get("decision"):
            decision = Decision(
                id=data["decision"].get("id", ""),
                type=data["decision"].get("type", ""),
                step=data["decision"].get("step", ""),
                prompt=data["decision"].get("prompt", ""),
                options=data["decision"].get("options", []),
                context=data["decision"].get("context", {}),
            )

        return cls(
            url=data.get("url", ""),
            state=state,
            decision=decision,
            done=data.get("done", False),
            plan=data.get("plan"),
        )


class CatalogChatAPI:
    """Client for CatalogChat HTTP API."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(120.0, connect=10.0)
        logger.info("Initialized CatalogChatAPI with base_url=%s", self.base_url)

    def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[dict] = None,
        params: Optional[dict] = None
    ) -> dict:
        """Make HTTP request to API."""
        url = f"{self.base_url}{endpoint}"
        logger.debug("%s %s params=%s json=%s", method, url, params, json_data)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                if method == "GET":
                    response = client.get(url, params=params)
                elif method == "POST":
                    response = client.post(url, json=json_data)
                elif method == "PUT":
                    response = client.put(url, json=json_data)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                logger.debug("Response %s %s -> %d", method, endpoint, response.status_code)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error %s %s: %d %s", method, endpoint, e.response.status_code, e.response.text)
            raise
        except httpx.RequestError as e:
            logger.error("Request failed %s %s: %s", method, endpoint, e)
            raise

    def check_plan_exists(self, url: str) -> dict:
        """Check if a plan already exists for the given URL."""
        logger.info("check_plan_exists url=%s", url)
        try:
            return self._make_request("GET", "/plan", params={"url": url})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info("No existing plan found for url=%s", url)
                return {"error": "not_found", "plan": None}
            raise

    def create_plan(self, url: str) -> dict:
        """Create or load a plan for the given URL."""
        logger.info("create_plan url=%s", url)
        return self._make_request("POST", "/plan", json_data={"url": url})

    def start_discovery(self, url: str, mode: str = "auto") -> DiscoveryResponse:
        """Start discovery for a URL."""
        logger.info("start_discovery url=%s mode=%s", url, mode)
        # API uses "interactive" instead of "manual"
        api_mode = "interactive" if mode == "manual" else "auto"
        data = self._make_request(
            "POST",
            "/plan/discovery",
            json_data={"url": url, "mode": api_mode}
        )
        return DiscoveryResponse.from_dict(data)

    def advance_discovery(
        self,
        url: str,
        user_input: dict,
        mode: str = "auto"
    ) -> DiscoveryResponse:
        """Advance discovery with user input."""
        logger.info("advance_discovery url=%s mode=%s user_input=%s", url, mode, user_input)
        # API uses "interactive" instead of "manual"
        api_mode = "interactive" if mode == "manual" else "auto"
        data = self._make_request(
            "POST",
            "/plan/discovery",
            json_data={"url": url, "user_input": user_input, "mode": api_mode}
        )
        return DiscoveryResponse.from_dict(data)

    def get_extraction_plan(self, url: str) -> dict:
        """Get the extraction plan for a URL."""
        logger.info("get_extraction_plan url=%s", url)
        response = self._make_request(
            "POST",
            "/plan/extraction-plan",
            json_data={"url": url}
        )
        # The API returns {url, extraction_plan}
        return response.get("extraction_plan", {})

    def get_sample_data(self, url: str, num_rows: int = 3) -> dict:
        """Fetch sample data for verification."""
        logger.info("get_sample_data url=%s num_rows=%d", url, num_rows)
        response = self._make_request(
            "POST",
            "/plan/sample",
            json_data={"url": url, "num_rows": num_rows}
        )
        # The API returns {url, sample, decision}
        # Transform to a more usable format
        sample = response.get("sample", {})
        return {
            "rows": sample.get("rows", []),
            "field_names": sample.get("field_names", []),
            "decision": response.get("decision"),
        }

    def fix_fields(self, url: str, fixes: list[dict]) -> dict:
        """Apply field fixes."""
        logger.info("fix_fields url=%s fixes=%s", url, fixes)
        return self._make_request(
            "POST",
            "/plan/fix-fields",
            json_data={"url": url, "fixes": fixes}
        )

    def suggest_correction(
        self,
        url: str,
        field_name: str,
        expected_value: str,
        user_feedback: str = ""
    ) -> dict:
        """Get AI-suggested correction for a field."""
        logger.info("suggest_correction url=%s field=%s expected=%s", url, field_name, expected_value)
        return self._make_request(
            "POST",
            "/plan/suggest-correction",
            json_data={
                "url": url,
                "field_name": field_name,
                "expected_value": expected_value,
                "user_feedback": user_feedback or f"Expected value should be: {expected_value}"
            }
        )

    def scrape_data(self, url: str, max_rows: Optional[int] = None) -> dict:
        """Perform full scrape."""
        logger.info("scrape_data url=%s max_rows=%s", url, max_rows)
        json_data = {"url": url}
        if max_rows is not None:
            json_data["max_rows"] = max_rows
        return self._make_request("POST", "/plan/scrape", json_data=json_data)

    def apply_schema_edits(self, url: str, edits: list[dict]) -> dict:
        """Apply schema edits to the plan."""
        logger.info("apply_schema_edits url=%s edits=%s", url, edits)
        return self._make_request(
            "PUT",
            "/plan",
            json_data={"url": url, "edits": edits}
        )
