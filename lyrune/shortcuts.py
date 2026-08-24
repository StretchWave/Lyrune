"""
shortcuts.py — Centralized hotkey and shortcut action manager.

Provides shortcut conflict detection, key normalization, and registry definitions.
"""

from typing import Dict, List, Tuple, Any, Optional


SHORTCUT_DEFINITIONS = [
    {
        "key_id": "shortcut_toggle_overlay",
        "name": "Toggle Lyrics Overlay",
        "description": "Show or hide the desktop floating lyrics window",
        "default": "Ctrl+H",
        "category": "Lyrics"
    },
    {
        "key_id": "shortcut_refresh",
        "name": "Refresh Lyrics",
        "description": "Force a fresh lyrics search and reload from LRCLIB",
        "default": "Ctrl+R",
        "category": "Lyrics"
    },
    {
        "key_id": "shortcut_nudge_minus",
        "name": "Nudge Sync Earlier (-250ms)",
        "description": "Shift lyric timing earlier by 250 milliseconds",
        "default": "Ctrl+Left",
        "category": "Lyrics"
    },
    {
        "key_id": "shortcut_nudge_plus",
        "name": "Nudge Sync Later (+250ms)",
        "description": "Shift lyric timing later by 250 milliseconds",
        "default": "Ctrl+Right",
        "category": "Lyrics"
    },
    {
        "key_id": "shortcut_toggle_visualizer",
        "name": "Toggle Visualizer Window",
        "description": "Show or hide the standalone floating audio visualizer",
        "default": "Ctrl+Shift+V",
        "category": "Visualizer"
    },
    {
        "key_id": "shortcut_toggle_game_overlay",
        "name": "Toggle Game Overlay Mode",
        "description": "Switch visualizer between normal desktop and Game Overlay HUD",
        "default": "Ctrl+Shift+G",
        "category": "Visualizer"
    },
    {
        "key_id": "shortcut_command_palette",
        "name": "Command Palette",
        "description": "Open omnibox quick search and command palette",
        "default": "Ctrl+K",
        "category": "Studio"
    }
]


def normalize_shortcut_key(seq: str) -> str:
    """Normalizes key sequence string for uniform comparison (e.g. 'ctrl+shift+v' -> 'Ctrl+Shift+V')."""
    if not seq:
        return ""
    parts = [p.strip().capitalize() for p in seq.split("+") if p.strip()]
    return "+".join(parts)


def find_shortcut_conflicts(settings: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Finds conflicting shortcuts that share the same key combination.
    Returns a dict mapping key_id to list of other conflicting action names.
    """
    assigned: Dict[str, List[str]] = {}
    for item in SHORTCUT_DEFINITIONS:
        k_id = item["key_id"]
        val = normalize_shortcut_key(settings.get(k_id, item["default"]))
        if val:
            assigned.setdefault(val.upper(), []).append(k_id)

    conflicts: Dict[str, List[str]] = {}
    for key_comb, ids in assigned.items():
        if len(ids) > 1:
            for k_id in ids:
                other_names = [
                    next((d["name"] for d in SHORTCUT_DEFINITIONS if d["key_id"] == other_id), other_id)
                    for other_id in ids if other_id != k_id
                ]
                conflicts[k_id] = other_names

    return conflicts
