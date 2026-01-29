"""
Catalog - A Python library for AI-assisted catalog schema discovery and data extraction.

This library provides a clean, stateless API for:
- Discovering nested catalog structures from websites
- Inferring data schemas using AI
- Extracting structured data from web catalogs

The library is designed to be adapter-agnostic - it can be used from CLI,
web APIs, Streamlit apps, or any other interface.
"""

from catalog.types import (
    CatalogPlan,
    DecisionType,
    DiscoveryState,
    ExtractionPlan,
    SampleResult,
    Decision,
    Field,
    LevelPlan,
)

from catalog.plan import (
    create_plan,
    load_plan,
    save_plan,
    update_plan,
)

from catalog.discovery import (
    start_discovery,
    advance_discovery,
)

from catalog.schema import (
    apply_schema_edits,
    validate_schema,
)

from catalog.extraction import (
    build_extraction_plan,
    scrape_sample,
    scrape_all,
    analyze_sample,
    apply_field_fix,
)

from catalog.state import (
    save_state,
    load_state,
)

__version__ = "0.1.0"

__all__ = [
    # Types
    "CatalogPlan",
    "DiscoveryState",
    "ExtractionPlan",
    "SampleResult",
    "Decision",
    "Field",
    "LevelPlan",
    # Plan management
    "create_plan",
    "load_plan",
    "save_plan",
    "update_plan",
    # Discovery
    "start_discovery",
    "advance_discovery",
    # Schema
    "apply_schema_edits",
    "validate_schema",
    # Extraction
    "build_extraction_plan",
    "scrape_sample",
    "scrape_all",
    "analyze_sample",
    "apply_field_fix",
    # State
    "save_state",
    "load_state",
]
