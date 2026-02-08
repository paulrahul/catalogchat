"""
Core type definitions for the catalog library.

These dataclasses define the domain objects used throughout the library.
All types are designed to be serializable to/from JSON for persistence.
"""

from dataclasses import dataclass, field
from typing import Any, Literal
from enum import Enum


class DecisionType(Enum):
    """Types of decisions that require user input."""
    CONFIRM_DRILLING = "confirm_drilling"
    SELECT_LINK = "select_link"
    CONFIRM_FINAL_LEVEL = "confirm_final_level"
    FIX_FIELD = "fix_field"
    EDIT_SCHEMA = "edit_schema"
    SCRAPE_MORE = "scrape_more"


# Decision ID constants - stable semantic identifiers for routing
class DecisionId:
    """
    Stable semantic identifiers for decision types.

    These IDs are used for routing in the generic wait_response API.
    They should remain stable across versions.
    """
    # Discovery phase decisions
    CONFIRM_DRILLING = "confirm_drilling"
    SELECT_LINK = "select_link"
    CONFIRM_FINAL_LEVEL = "confirm_final_level"

    # Sample/extraction phase decisions
    FIX_FIELD = "fix_field"
    EDIT_SCHEMA = "edit_schema"
    SCRAPE_MORE = "scrape_more"

    # Plan phase decisions (future)
    REUSE_EXISTING_PLAN = "reuse_existing_plan"
    CHOOSE_NEXT_LINK = "choose_next_link"
    CONFIRM_SAMPLE_DATA = "confirm_sample_data"


# Step identifiers for tracking which phase the decision is from
class DecisionStep:
    """
    Identifiers for the phase/step where a decision was created.

    Useful for debugging, logging, and analytics.
    """
    PLAN_CHECK = "plan_check"
    DISCOVERY = "discovery"
    SCHEMA_INFERENCE = "schema_inference"
    NESTING_ANALYSIS = "nesting_analysis"
    SAMPLE_ANALYSIS = "sample_analysis"
    FIELD_CORRECTION = "field_correction"
    EXTRACTION = "extraction"


@dataclass
class Decision:
    """
    Represents a decision point that requires user input.

    This is the core mechanism for human-in-the-loop interactions.
    Instead of blocking for input, functions return Decision objects
    that describe what input is needed.

    Attributes:
        id: Stable semantic identifier for this decision type (e.g., "confirm_drilling").
            Used for routing in the wait_response API.
        type: The DecisionType enum value (for backward compatibility).
        step: The phase/step where this decision was created (e.g., "discovery").
        prompt: Human-readable question to ask the user.
        options: Available choices (action values like "continue", "final", "stop").
        input_schema: JSON schema for complex input (when options aren't sufficient).
        context: Additional context for the UI to render the decision.
    """
    type: DecisionType
    prompt: str
    options: list[str] | None = None
    input_schema: dict | None = None
    context: dict = field(default_factory=dict)
    id: str | None = None  # Semantic decision ID
    step: str | None = None  # Phase/step identifier

    def __post_init__(self):
        """Auto-generate id from type if not provided."""
        if self.id is None:
            self.id = self.type.value

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "step": self.step,
            "prompt": self.prompt,
            "options": self.options,
            "input_schema": self.input_schema,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Decision":
        return cls(
            type=DecisionType(data["type"]),
            prompt=data["prompt"],
            options=data.get("options"),
            input_schema=data.get("input_schema"),
            context=data.get("context", {}),
            id=data.get("id"),
            step=data.get("step"),
        )


@dataclass
class Field:
    """
    Represents a field in a catalog schema.

    Fields define what data to extract and how to extract it using CSS selectors.
    """
    name: str
    type: str = "string"
    required: bool = False
    description: str = ""
    container_selector: str | None = None
    selector: str | None = None
    attribute: str = "text"
    original_name: str | None = None
    source_level: str | None = None
    source_level_num: int | None = None
    sample_value: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "description": self.description,
            "container_selector": self.container_selector,
            "selector": self.selector,
            "attribute": self.attribute,
            "original_name": self.original_name,
            "source_level": self.source_level,
            "source_level_num": self.source_level_num,
            "sample_value": self.sample_value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Field":
        return cls(
            name=data.get("name", ""),
            type=data.get("type", "string"),
            required=data.get("required", False),
            description=data.get("description", ""),
            container_selector=data.get("container_selector"),
            selector=data.get("selector"),
            attribute=data.get("attribute", "text"),
            original_name=data.get("original_name"),
            source_level=data.get("source_level"),
            source_level_num=data.get("source_level_num"),
            sample_value=data.get("sample_value"),
        )


@dataclass
class LevelPlan:
    """
    Represents the extraction plan for a single level in the catalog hierarchy.
    """
    level: int
    level_name: str
    sample_url: str
    catalog_type: str | None = None
    item_name: str | None = None
    item_container_selector: str | None = None
    is_final_level: bool = True
    drill_down_link_selector: str | None = None
    fields: list[Field] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "level_name": self.level_name,
            "sample_url": self.sample_url,
            "catalog_type": self.catalog_type,
            "item_name": self.item_name,
            "item_container_selector": self.item_container_selector,
            "is_final_level": self.is_final_level,
            "drill_down_link_selector": self.drill_down_link_selector,
            "fields": [f.to_dict() for f in self.fields],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LevelPlan":
        return cls(
            level=data.get("level", 1),
            level_name=data.get("level_name", ""),
            sample_url=data.get("sample_url", ""),
            catalog_type=data.get("catalog_type"),
            item_name=data.get("item_name"),
            item_container_selector=data.get("item_container_selector"),
            is_final_level=data.get("is_final_level", True),
            drill_down_link_selector=data.get("drill_down_link_selector"),
            fields=[Field.from_dict(f) for f in data.get("fields", [])],
        )


@dataclass
class LevelSchema:
    """
    Represents the inferred schema for a single page/level.
    """
    level: int
    url: str
    is_catalog: bool = False
    catalog_type: str | None = None
    confidence: float = 0.0
    archetype: str | None = None
    item_name: str | None = None
    item_container_selector: str | None = None
    fields: list[Field] = field(default_factory=list)
    reasoning: str = ""
    nesting_analysis: dict | None = None

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "url": self.url,
            "is_catalog": self.is_catalog,
            "catalog_type": self.catalog_type,
            "confidence": self.confidence,
            "archetype": self.archetype,
            "item_name": self.item_name,
            "item_container_selector": self.item_container_selector,
            "fields": [f.to_dict() for f in self.fields],
            "reasoning": self.reasoning,
            "nesting_analysis": self.nesting_analysis,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LevelSchema":
        return cls(
            level=data.get("level", 1),
            url=data.get("url", ""),
            is_catalog=data.get("is_catalog", False),
            catalog_type=data.get("catalog_type"),
            confidence=data.get("confidence", 0.0),
            archetype=data.get("archetype"),
            item_name=data.get("item_name"),
            item_container_selector=data.get("item_container_selector"),
            fields=[Field.from_dict(f) for f in data.get("fields", [])],
            reasoning=data.get("reasoning", ""),
            nesting_analysis=data.get("nesting_analysis"),
        )


@dataclass
class CatalogPlan:
    """
    Represents the complete plan for a catalog, including root URL and merged schema.

    This is the primary object representing a catalog's structure.
    It is created by discovery and used as input for extraction.
    """
    id: str
    root_url: str
    item_name: str = "Item"
    nesting_depth: int = 1
    level_names: list[str] = field(default_factory=list)
    fields: list[Field] = field(default_factory=list)
    schema_chain: list[LevelSchema] = field(default_factory=list)
    visited_urls: list[str] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "root_url": self.root_url,
            "item_name": self.item_name,
            "nesting_depth": self.nesting_depth,
            "level_names": self.level_names,
            "fields": [f.to_dict() for f in self.fields],
            "schema_chain": [s.to_dict() for s in self.schema_chain],
            "visited_urls": self.visited_urls,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CatalogPlan":
        return cls(
            id=data.get("id", ""),
            root_url=data.get("root_url", ""),
            item_name=data.get("item_name", "Item"),
            nesting_depth=data.get("nesting_depth", 1),
            level_names=data.get("level_names", []),
            fields=[Field.from_dict(f) for f in data.get("fields", [])],
            schema_chain=[LevelSchema.from_dict(s) for s in data.get("schema_chain", [])],
            visited_urls=data.get("visited_urls", []),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class DiscoveryState:
    """
    Represents the current state of the discovery process.

    This allows discovery to be paused, resumed, and driven step-by-step.
    """
    plan: CatalogPlan
    current_url: str
    current_level: int = 1
    visited_urls: set[str] = field(default_factory=set)
    done: bool = False
    pending_decision: Decision | None = None

    # Internal state for the discovery process
    _current_html: str | None = field(default=None, repr=False)
    _current_dom_summary: dict | None = field(default=None, repr=False)
    _current_schema: dict | None = field(default=None, repr=False)
    _unvisited_links: list[str] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        return {
            "plan": self.plan.to_dict(),
            "current_url": self.current_url,
            "current_level": self.current_level,
            "visited_urls": list(self.visited_urls),
            "done": self.done,
            "pending_decision": self.pending_decision.to_dict() if self.pending_decision else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DiscoveryState":
        return cls(
            plan=CatalogPlan.from_dict(data.get("plan", {})),
            current_url=data.get("current_url", ""),
            current_level=data.get("current_level", 1),
            visited_urls=set(data.get("visited_urls", [])),
            done=data.get("done", False),
            pending_decision=Decision.from_dict(data["pending_decision"]) if data.get("pending_decision") else None,
        )


@dataclass
class ExtractionPlan:
    """
    Represents the plan for extracting data from a catalog.

    This is derived from a CatalogPlan and contains all the information
    needed to actually scrape data from the catalog.
    """
    root_url: str
    navigation_path: list[LevelPlan] = field(default_factory=list)
    fields: list[Field] = field(default_factory=list)
    field_name_mapping: dict[str, str] = field(default_factory=dict)
    final_field_names: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "root_url": self.root_url,
            "navigation_path": [lp.to_dict() for lp in self.navigation_path],
            "fields": [f.to_dict() for f in self.fields],
            "field_name_mapping": self.field_name_mapping,
            "final_field_names": self.final_field_names,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractionPlan":
        return cls(
            root_url=data.get("root_url", ""),
            navigation_path=[LevelPlan.from_dict(lp) for lp in data.get("navigation_path", [])],
            fields=[Field.from_dict(f) for f in data.get("fields", [])],
            field_name_mapping=data.get("field_name_mapping", {}),
            final_field_names=data.get("final_field_names", []),
            summary=data.get("summary", {}),
        )


@dataclass
class SampleResult:
    """
    Represents the result of a sample scrape operation.
    """
    rows: list[dict] = field(default_factory=list)
    field_names: list[str] = field(default_factory=list)
    target_level: int = 1
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rows": self.rows,
            "field_names": self.field_names,
            "target_level": self.target_level,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SampleResult":
        return cls(
            rows=data.get("rows", []),
            field_names=data.get("field_names", []),
            target_level=data.get("target_level", 1),
            errors=data.get("errors", []),
        )
