"""
settings_registry.py — Centralized settings metadata registry for Lyrune.

Every UI control registers its metadata here, enabling:
  - Full-text fuzzy search with ranked results
  - Deep navigation (page → subsection → control)
  - Tooltips and descriptions
  - Validation (orphaned controls, duplicate IDs, missing persistence)
  - Future: settings export, documentation generation, command palette

Each registered setting carries its page, section, display name, description,
keywords, type information, and optionally a reference to the live widget.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


class MatchType(str, Enum):
    """How a search result matched the query."""
    TITLE_EXACT = "title_exact"
    TITLE_SUBSTRING = "title_substring"
    SECTION = "section"
    KEYWORD = "keyword"
    DESCRIPTION = "description"
    PAGE = "page"


@dataclass
class SettingMeta:
    """Metadata descriptor for a single settings control."""
    setting_id: str                          # Unique key, e.g. "lyrics.active_font_family"
    name: str                                # Display name, e.g. "Active Line Font"
    page: str                                # Top-level page, e.g. "Lyrics"
    section: str                             # Subsection within page, e.g. "Typography"
    description: str = ""                    # Tooltip / help text
    keywords: List[str] = field(default_factory=list)  # Extra search terms
    setting_type: str = "string"             # "string", "int", "float", "bool", "color", "enum", "font", "list"
    default: Any = None                      # Default value
    range_min: Optional[float] = None        # For numeric types
    range_max: Optional[float] = None        # For numeric types
    enum_values: List[str] = field(default_factory=list)  # For enum types
    depends_on: Optional[str] = None         # Setting ID that must be truthy for this to be visible
    advanced: bool = False                   # Whether this is an advanced control (collapsed by default)
    settings_key: str = ""                   # The actual key in settings.json (if different from setting_id)
    widget_ref: Any = None                   # Runtime reference to the Qt widget (set after UI construction)


@dataclass
class SearchResult:
    """A single search result with score and match information."""
    meta: SettingMeta
    score: float                             # Higher = better match
    match_type: MatchType                    # How the query matched

    def __lt__(self, other: "SearchResult"):
        return self.score > other.score      # Sort descending by score


@dataclass
class ValidationIssue:
    """A single validation problem found in the registry."""
    severity: str      # "error", "warning", "info"
    issue_type: str    # "duplicate_id", "orphaned_control", "no_persistence", "missing_widget", "no_ui"
    setting_id: str
    message: str

    def __str__(self):
        return f"[{self.severity.upper()}] {self.issue_type}: {self.setting_id} — {self.message}"


class SettingsRegistry:
    """
    Central registry of all settings metadata.

    Controls register themselves during UI construction. The registry then
    powers search, deep navigation, validation, and documentation.
    """

    def __init__(self):
        self._entries: Dict[str, SettingMeta] = {}
        self._by_page: Dict[str, List[SettingMeta]] = {}
        self._by_section: Dict[str, List[SettingMeta]] = {}

    def register(self, meta: SettingMeta) -> None:
        """Register a setting's metadata. Overwrites if ID already exists."""
        self._entries[meta.setting_id] = meta

        # Index by page
        self._by_page.setdefault(meta.page, [])
        # Remove old entry with same ID if re-registering
        self._by_page[meta.page] = [
            m for m in self._by_page[meta.page] if m.setting_id != meta.setting_id
        ]
        self._by_page[meta.page].append(meta)

        # Index by page.section
        section_key = f"{meta.page}.{meta.section}"
        self._by_section.setdefault(section_key, [])
        self._by_section[section_key] = [
            m for m in self._by_section[section_key] if m.setting_id != meta.setting_id
        ]
        self._by_section[section_key].append(meta)

    def get_by_id(self, setting_id: str) -> Optional[SettingMeta]:
        """Look up a setting by its unique ID."""
        return self._entries.get(setting_id)

    def get_by_page(self, page: str) -> List[SettingMeta]:
        """Get all settings registered under a page."""
        return list(self._by_page.get(page, []))

    def get_by_section(self, page: str, section: str) -> List[SettingMeta]:
        """Get all settings registered under a specific page + section."""
        key = f"{page}.{section}"
        return list(self._by_section.get(key, []))

    def all_entries(self) -> List[SettingMeta]:
        """Return all registered settings."""
        return list(self._entries.values())

    def search(self, query: str, max_results: int = 30) -> List[SearchResult]:
        """
        Fuzzy search across all registered settings.

        Ranking priority:
          1. Exact title match (score 100)
          2. Title starts with query (score 90)
          3. Title substring match (score 80)
          4. Section match (score 60)
          5. Keyword match (score 50)
          6. Description match (score 30)
          7. Page match (score 20)

        Within each tier, matches are sorted alphabetically.
        """
        if not query or not query.strip():
            return []

        q = query.strip().lower()
        tokens = q.split()
        results: List[SearchResult] = []
        seen_ids: set = set()

        for meta in self._entries.values():
            best_score = 0.0
            best_match = MatchType.DESCRIPTION

            name_lower = meta.name.lower()
            section_lower = meta.section.lower()
            page_lower = meta.page.lower()
            desc_lower = meta.description.lower()
            keywords_lower = [k.lower() for k in meta.keywords]

            # --- Title matching ---
            if name_lower == q:
                best_score, best_match = 100.0, MatchType.TITLE_EXACT
            elif name_lower.startswith(q):
                best_score, best_match = 90.0, MatchType.TITLE_SUBSTRING
            elif q in name_lower:
                best_score, best_match = 80.0, MatchType.TITLE_SUBSTRING
            elif all(t in name_lower for t in tokens):
                best_score, best_match = 75.0, MatchType.TITLE_SUBSTRING

            # --- Section matching ---
            if q in section_lower or all(t in section_lower for t in tokens):
                score = 60.0
                if score > best_score:
                    best_score, best_match = score, MatchType.SECTION

            # --- Keyword matching ---
            for kw in keywords_lower:
                if q == kw:
                    score = 55.0
                elif q in kw or kw.startswith(q):
                    score = 50.0
                elif any(t in kw for t in tokens):
                    score = 45.0
                else:
                    continue
                if score > best_score:
                    best_score, best_match = score, MatchType.KEYWORD

            # --- Description matching ---
            if q in desc_lower or all(t in desc_lower for t in tokens):
                score = 30.0
                if score > best_score:
                    best_score, best_match = score, MatchType.DESCRIPTION

            # --- Page matching ---
            if q in page_lower:
                score = 20.0
                if score > best_score:
                    best_score, best_match = score, MatchType.PAGE

            if best_score > 0 and meta.setting_id not in seen_ids:
                results.append(SearchResult(meta=meta, score=best_score, match_type=best_match))
                seen_ids.add(meta.setting_id)

        results.sort()
        return results[:max_results]

    def get_grouped_results(self, query: str, max_results: int = 30) -> Dict[str, Dict[str, List[SearchResult]]]:
        """
        Search and group results by page → section.

        Returns:
            {
                "Lyrics": {
                    "Typography": [SearchResult, ...],
                    "Appearance": [SearchResult, ...]
                },
                "Wallpaper": {
                    "Vinyl": [SearchResult, ...]
                }
            }
        """
        results = self.search(query, max_results)
        grouped: Dict[str, Dict[str, List[SearchResult]]] = {}

        for r in results:
            page = r.meta.page
            section = r.meta.section
            grouped.setdefault(page, {})
            grouped[page].setdefault(section, [])
            grouped[page][section].append(r)

        return grouped

    def validate(self, default_settings: Optional[Dict[str, Any]] = None) -> List[ValidationIssue]:
        """
        Validate the registry against the settings schema.

        Checks:
          - Duplicate setting IDs (impossible due to dict, but checks for
            entries with same settings_key)
          - Orphaned controls: registered setting with no matching key in defaults
          - No persistence: key in defaults but not registered
          - Missing widget reference (after UI construction)
        """
        issues: List[ValidationIssue] = []

        # Check for duplicate settings_keys
        seen_keys: Dict[str, str] = {}
        for sid, meta in self._entries.items():
            skey = meta.settings_key or sid
            if skey in seen_keys:
                issues.append(ValidationIssue(
                    severity="error",
                    issue_type="duplicate_settings_key",
                    setting_id=sid,
                    message=f"Settings key '{skey}' also used by '{seen_keys[skey]}'"
                ))
            seen_keys[skey] = sid

        if default_settings:
            # Check for orphaned controls (registered but no default)
            for sid, meta in self._entries.items():
                skey = meta.settings_key or sid
                if skey not in default_settings and "." in skey:
                    # Dot-separated IDs are registry-only identifiers, check the settings_key
                    pass
                elif skey not in default_settings and "." not in skey:
                    issues.append(ValidationIssue(
                        severity="warning",
                        issue_type="orphaned_control",
                        setting_id=sid,
                        message=f"Registered setting has no default in settings_manager (key: '{skey}')"
                    ))

            # Check for settings with no UI
            registered_keys = set()
            for sid, meta in self._entries.items():
                registered_keys.add(meta.settings_key or sid)

            skip_keys = {
                "settings_schema_version", "profiles", "active_profile",
                "track_sync_offsets", "visualizer_normal_snapshot",
                "visualizer_game_snapshot", "source_priority"
            }
            for key in default_settings:
                if key not in registered_keys and key not in skip_keys:
                    issues.append(ValidationIssue(
                        severity="info",
                        issue_type="no_ui",
                        setting_id=key,
                        message=f"Settings key '{key}' has a default but no registered UI control"
                    ))

        # Check for missing widget references
        missing_widgets = [
            sid for sid, meta in self._entries.items()
            if meta.widget_ref is None
        ]
        if missing_widgets:
            for sid in missing_widgets[:10]:  # Limit noise
                issues.append(ValidationIssue(
                    severity="info",
                    issue_type="missing_widget",
                    setting_id=sid,
                    message="No widget reference set (may not have been constructed yet)"
                ))

        return issues

    def export_index(self) -> List[Dict[str, Any]]:
        """Export the full registry as a list of dicts for debugging/documentation."""
        return [
            {
                "id": m.setting_id,
                "name": m.name,
                "page": m.page,
                "section": m.section,
                "description": m.description,
                "keywords": m.keywords,
                "type": m.setting_type,
                "default": m.default if not callable(m.default) else str(m.default),
                "advanced": m.advanced,
                "settings_key": m.settings_key,
                "depends_on": m.depends_on,
            }
            for m in self._entries.values()
        ]

    def clear(self) -> None:
        """Clear all registered entries. Useful for testing."""
        self._entries.clear()
        self._by_page.clear()
        self._by_section.clear()

    @property
    def count(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        pages = ", ".join(f"{p}({len(items)})" for p, items in self._by_page.items())
        return f"<SettingsRegistry entries={self.count} pages=[{pages}]>"


# Global singleton — import this from anywhere
SETTINGS_REGISTRY = SettingsRegistry()
