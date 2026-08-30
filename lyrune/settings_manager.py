"""
settings_manager.py — Configuration persistence, schema migrations, profiles, and backup/restore.

Provides robust, versioned JSON configuration persistence in the user's APPDATA/XDG directory
with atomic disk writes, debounced saves, corrupt file recovery, schema migrations, and preset profiles.
"""

import os
import sys
import json
import time
import shutil
from typing import Dict, Any, Optional, List, Tuple
from PyQt6.QtCore import QTimer

# Resolve project root
_LOCAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CURRENT_SCHEMA_VERSION = 3

DEFAULT_SETTINGS: Dict[str, Any] = {
    "settings_schema_version": CURRENT_SCHEMA_VERSION,

    # ══════════════════════════════════════════════════════════════════════
    # LYRICS — Content
    # ══════════════════════════════════════════════════════════════════════
    "lyrics_view_mode": "Multi-line",        # "Multi-line", "Single-line Ticker", "Minimal", "Karaoke"
    "context_lines": 2,
    "context_lines_before": 1,
    "context_lines_after": 2,
    "lyrics_max_lines": 8,
    "lyrics_max_chars": 120,
    "lyrics_unsynced_behavior": "Show static",    # "Show static", "Hide", "Scroll slowly"
    "lyrics_no_lyrics_behavior": "Show message",  # "Show message", "Hide overlay", "Show track info only"
    "auto_search_lyrics": True,
    "show_song_info": True,

    # ══════════════════════════════════════════════════════════════════════
    # LYRICS — Typography: Active Line
    # ══════════════════════════════════════════════════════════════════════
    "font_family": "Segoe UI",
    "font_size": 24,
    "font_bold": True,
    "lyrics_active_font_italic": False,
    "lyrics_active_letter_spacing": 0.0,

    # LYRICS — Typography: Context Lines
    "lyrics_context_font_mode": "Use Active Line Settings",   # "Use Active Line Settings", "Custom"
    "lyrics_context_font_family": "Segoe UI",
    "lyrics_context_font_size": 18,
    "lyrics_context_font_weight": "Normal",
    "lyrics_context_font_italic": False,
    "lyrics_context_letter_spacing": 0.0,

    # LYRICS — Typography: Metadata (Title/Artist)
    "lyrics_title_font_family": "Segoe UI",
    "lyrics_title_font_size": 16,
    "lyrics_title_font_weight": "Bold",
    "lyrics_artist_font_family": "Segoe UI",
    "lyrics_artist_font_size": 12,
    "lyrics_artist_font_weight": "Normal",

    # LYRICS — Typography: Advanced
    "lyrics_line_height": 1.4,
    "lyrics_case_transform": "None",       # "None", "Uppercase", "Lowercase", "Capitalize"
    "lyrics_char_spacing": 0.0,
    "lyrics_rendering_mode": "Default",    # "Default", "Subpixel", "Grayscale"

    # ══════════════════════════════════════════════════════════════════════
    # LYRICS — Layout
    # ══════════════════════════════════════════════════════════════════════
    "lyrics_position_preset": "Bottom",    # "Top", "Bottom", "Center", "Left", "Right", "Custom"
    "text_align": "Center",
    "lyrics_alignment_v": "Center",        # "Top", "Center", "Bottom"
    "lyrics_position_x": -1,
    "lyrics_position_y": -1,
    "window_width": 800,
    "window_height": 220,
    "lyrics_max_width": 1200,
    "lyrics_max_height": 600,
    "lyrics_padding": 12,
    "lyrics_margin": 0,
    "lyrics_safe_area_margin": 0,
    "lyrics_monitor": "Primary",
    "snap_to_corners": True,
    "lock_position": False,
    "auto_resize_height": True,
    "window_x": -1,
    "window_y": -1,

    # ══════════════════════════════════════════════════════════════════════
    # LYRICS — Appearance: Colors
    # ══════════════════════════════════════════════════════════════════════
    "text_color": "#FFFFFF",               # Active line color
    "lyrics_context_color": "#888888",
    "lyrics_title_color": "#FFFFFF",
    "lyrics_artist_color": "#AAAAAA",
    "bg_color": "#000000",
    "lyrics_border_color": "#FFFFFF",

    # LYRICS — Appearance: Color Mode
    "lyrics_color_mode": "Manual",         # "Manual", "Dynamic Album Accent", "Follow Global Theme"
    "adaptive_color": False,

    # LYRICS — Appearance: Opacity
    "active_line_opacity": 100,
    "context_line_opacity": 45,
    "lyrics_title_opacity": 90,
    "lyrics_artist_opacity": 70,
    "bg_opacity": 0,
    "lyrics_border_opacity": 0,
    "link_opacity_levels": True,

    # LYRICS — Appearance: Effects — Shadow
    "shadow_enabled": True,
    "shadow_color": "#000000",
    "shadow_blur": 8,
    "lyrics_shadow_offset_x": 0,
    "lyrics_shadow_offset_y": 2,

    # LYRICS — Appearance: Effects — Outline
    "active_text_outline": True,
    "lyrics_outline_width": 1,
    "lyrics_outline_color": "#000000",

    # LYRICS — Appearance: Effects — Glow
    "lyrics_glow_enabled": False,
    "lyrics_glow_radius": 12,
    "lyrics_glow_color": "#2ED573",
    "lyrics_glow_intensity": 50,

    # LYRICS — Appearance: Effects — Background & Border
    "border_enabled": False,
    "lyrics_border_width": 1,
    "lyrics_border_radius": 12,
    "lyrics_bg_blur": 0,

    # ══════════════════════════════════════════════════════════════════════
    # LYRICS — Animation
    # ══════════════════════════════════════════════════════════════════════
    "lyrics_animation_preset": "Smooth",   # "Smooth", "Fast", "Cinematic", "Off"
    "animation_speed_ms": 400,
    "lyrics_fade_duration_ms": 200,
    "lyrics_scroll_easing": "OutCubic",    # "Linear", "OutCubic", "OutQuint", "InOutCubic"
    "lyrics_track_change_transition": "Fade",  # "Fade", "Scroll", "Instant"
    "lyrics_seek_transition": "Instant",       # "Fade", "Scroll", "Instant"
    "lyrics_auto_resize_anim": True,
    "lyrics_ticker_speed": 50,             # pixels/sec for Single-line Ticker mode
    "lyrics_reduced_motion": False,

    # ══════════════════════════════════════════════════════════════════════
    # LYRICS — Synchronization
    # ══════════════════════════════════════════════════════════════════════
    "sync_offset_ms": 0,
    "track_sync_offsets": {},
    "lyrics_auto_drift_correction": False,
    "lyrics_lrc_metadata_offset": True,
    "lyrics_show_match_confidence": True,

    # ══════════════════════════════════════════════════════════════════════
    # LYRICS — Behavior
    # ══════════════════════════════════════════════════════════════════════
    "always_on_top": True,
    "window_layer_mode": "Top",
    "click_through": False,
    "exclude_from_capture": False,
    "auto_hide_on_pause": False,
    "lyrics_hide_on_stop": True,
    "auto_hide_delay_sec": 5,
    "lyrics_startup_state": "Visible",     # "Visible", "Hidden", "Restore Previous"
    "lyrics_window_lock": False,

    # ══════════════════════════════════════════════════════════════════════
    # MEDIA SOURCE
    # ══════════════════════════════════════════════════════════════════════
    "selected_media_source": "Auto-Detect",
    "prefer_playing_session": True,
    "source_priority": [
        "Spotify Desktop",
        "Spotify Web",
        "YouTube Music",
        "Brave",
        "Chrome",
        "Edge",
        "Firefox",
        "Opera"
    ],

    # ══════════════════════════════════════════════════════════════════════
    # VISUALIZER — Audio
    # ══════════════════════════════════════════════════════════════════════
    "visualizer_enabled": False,
    "visualizer_audio_device": "Default",
    "visualizer_sample_rate": 48000,
    "visualizer_channel": "Stereo",
    "visualizer_fft_size": 1024,
    "visualizer_frequency_scale": "Logarithmic",   # "Logarithmic", "Linear"
    "visualizer_frequency_min": 20,
    "visualizer_frequency_max": 20000,
    "visualizer_noise_floor": -60,
    "visualizer_sensitivity": 100,
    "visualizer_gain": 1.0,
    "visualizer_smoothing": 75,
    "visualizer_attack": 0.8,
    "visualizer_decay": 0.4,
    "visualizer_peak_hold": False,
    "visualizer_bass_boost": 0,
    "visualizer_mid_boost": 0,
    "visualizer_treble_boost": 0,
    "visualizer_preview_mode": "Demo",

    # VISUALIZER — Bars
    "visualizer_style": "Pill Bars",
    "visualizer_shape": "Pill",
    "visualizer_bar_count": 32,
    "visualizer_auto_bar_count": True,
    "visualizer_bar_width": 4,
    "visualizer_bar_spacing": 3,
    "visualizer_max_height": 100,
    "visualizer_min_height": 2,
    "visualizer_corner_radius": 4,
    "visualizer_orientation": "BOTTOM",
    "visualizer_mirror": False,
    "visualizer_symmetry": False,

    # VISUALIZER — Color
    "visualizer_color_mode": "Solid",
    "visualizer_color": "#FFFFFF",
    "visualizer_gradient_stops": [
        {"pos": 0.0, "color": "#FF4D8D"},
        {"pos": 0.5, "color": "#8B5CF6"},
        {"pos": 1.0, "color": "#3B82F6"}
    ],
    "visualizer_gradient_direction": "Follow Visualizer",
    "visualizer_album_accent_color": False,
    "visualizer_active_lyric_color": False,

    # VISUALIZER — Effects
    "visualizer_glow_enabled": False,
    "visualizer_glow_radius": 8,
    "visualizer_glow_color": "#FFFFFF",
    "visualizer_shadow_enabled": False,
    "visualizer_shadow_blur": 4,
    "visualizer_shadow_color": "#000000",
    "visualizer_peak_indicator": False,
    "visualizer_trail_enabled": False,
    "visualizer_reflection_enabled": False,
    "visualizer_blur_enabled": False,

    # VISUALIZER — Position & Window
    "visualizer_position_preset": "Free",  # "Free", "Top", "Bottom", "Left", "Right", "Custom"
    "visualizer_x": -1,
    "visualizer_y": -1,
    "visualizer_width": 320,
    "visualizer_height": 64,
    "visualizer_snap_edge": "BOTTOM",
    "visualizer_opacity": 100,
    "visualizer_margin": 0,
    "visualizer_monitor": "Primary",
    "visualizer_click_through": False,
    "visualizer_always_on_top": True,
    "visualizer_window_layer_mode": "Top",
    "visualizer_exclude_from_capture": False,

    # VISUALIZER — Game Overlay
    "visualizer_overlay_mode": "Normal",
    "visualizer_overlay_screen": "Active Game Monitor",
    "visualizer_overlay_position": "Bottom",
    "visualizer_overlay_margin": 15,
    "visualizer_follow_active_window": False,
    "visualizer_overlay_inactive_behavior": "Keep visible",
    "visualizer_normal_snapshot": {},
    "visualizer_game_snapshot": {},

    # VISUALIZER — Behavior
    "visualizer_pause_on_media_pause": True,
    "visualizer_hide_on_stop": False,
    "visualizer_start_enabled": False,
    "visualizer_fps": 60,
    "visualizer_pause_on_battery": False,

    # ══════════════════════════════════════════════════════════════════════
    # WALLPAPER — Background
    # ══════════════════════════════════════════════════════════════════════
    "wallpaper_enabled": False,
    "wallpaper_type": "static",
    "wallpaper_path": "",
    "wallpaper_scaling_mode": "fill",
    "wallpaper_display_mode": "Primary Display",
    "wallpaper_brightness": 100,
    "wallpaper_contrast": 100,
    "wallpaper_saturation": 100,
    "wallpaper_gamma": 100,
    "wallpaper_blur": 0,
    "wallpaper_vignette": 0,
    "wallpaper_color_overlay": "",
    "wallpaper_dynamic_tint": False,
    "wallpaper_video_loop": True,
    "wallpaper_video_speed": 1.0,
    "wallpaper_video_playback": "Loop",     # "Loop", "Pause at End", "Reverse Loop"

    # WALLPAPER — Canvas
    "wallpaper_canvas_zoom": 100,
    "wallpaper_canvas_guides": False,
    "wallpaper_canvas_grid": False,
    "wallpaper_canvas_snap": True,
    "wallpaper_canvas_safe_area": False,
    "wallpaper_canvas_coordinates": False,

    # WALLPAPER — Vinyl: Transform
    "wallpaper_vinyl_x": 0.78,
    "wallpaper_vinyl_y": 0.65,
    "wallpaper_vinyl_size": 0.20,
    "wallpaper_vinyl_rotation": 0.0,
    "wallpaper_vinyl_scale": 1.0,

    # WALLPAPER — Vinyl: Appearance
    "wallpaper_vinyl_opacity": 100,
    "wallpaper_vinyl_record_style": "Classic",  # "Classic", "Colored", "Picture Disc"
    "wallpaper_vinyl_label_ratio": 38.0,
    "wallpaper_vinyl_label_crop": "Circle",     # "Circle", "Square", "Rounded"
    "wallpaper_vinyl_label_border": True,
    "wallpaper_vinyl_shadow": False,
    "wallpaper_vinyl_shadow_blur": 12,
    "wallpaper_vinyl_reflection": False,
    "wallpaper_vinyl_glow": False,
    "wallpaper_vinyl_glow_color": "#FFFFFF",
    "wallpaper_vinyl_glow_radius": 16,

    # WALLPAPER — Vinyl: Animation
    "wallpaper_rotation_speed": 12.0,
    "wallpaper_vinyl_direction": "Clockwise",  # "Clockwise", "Counter-Clockwise"
    "wallpaper_vinyl_smoothness": 1.0,
    "wallpaper_rotate_while_playing": True,
    "wallpaper_pause_on_music_pause": True,

    # WALLPAPER — Vinyl: Audio Reactivity
    "wallpaper_vinyl_audio_reactive": False,
    "wallpaper_vinyl_bass_response": 50,
    "wallpaper_vinyl_energy_scale": 50,
    "wallpaper_vinyl_pulse_strength": 30,

    # WALLPAPER — Text
    "wallpaper_show_title": True,
    "wallpaper_show_artist": True,
    "wallpaper_text_position": "Below",
    "wallpaper_text_alignment": "Center",
    "wallpaper_text_color": "#FFFFFF",
    "wallpaper_title_font_family": "Segoe UI",
    "wallpaper_title_font_size": 14,
    "wallpaper_title_font_weight": "Bold",
    "wallpaper_artist_font_family": "Segoe UI",
    "wallpaper_artist_font_size": 11,
    "wallpaper_artist_font_weight": "Normal",
    "wallpaper_text_opacity": 100,
    "wallpaper_text_shadow": False,
    "wallpaper_text_outline": False,
    "wallpaper_text_glow": False,
    "wallpaper_text_max_width": 300,
    "wallpaper_text_wrapping": True,
    "wallpaper_text_ellipsis": True,
    "wallpaper_link_title_artist_style": True,

    # WALLPAPER — Lyrics (overlay on wallpaper)
    "wallpaper_lyrics_enabled": False,
    "wallpaper_lyrics_position": "Center",
    "wallpaper_lyrics_width": 400,
    "wallpaper_lyrics_alignment": "Center",
    "wallpaper_lyrics_font_size": 18,
    "wallpaper_lyrics_active_color": "#FFFFFF",
    "wallpaper_lyrics_context_color": "#888888",
    "wallpaper_lyrics_context_lines": 2,
    "wallpaper_lyrics_opacity": 100,
    "wallpaper_lyrics_spacing": 8,
    "wallpaper_lyrics_shadow": True,
    "wallpaper_lyrics_outline": False,
    "wallpaper_lyrics_glow": False,
    "wallpaper_lyrics_bg_enabled": False,
    "wallpaper_lyrics_animation": "Fade",

    # WALLPAPER — Visualizer (embedded in wallpaper)
    "wallpaper_visualizer_enabled": False,
    "wallpaper_visualizer_position": "Bottom",
    "wallpaper_visualizer_size": 100,
    "wallpaper_visualizer_orientation": "Horizontal",
    "wallpaper_visualizer_opacity": 80,
    "wallpaper_visualizer_style": "Pill Bars",
    "wallpaper_visualizer_color_mode": "Gradient",
    "wallpaper_visualizer_bar_count": 32,
    "wallpaper_visualizer_sensitivity": 100,
    "wallpaper_visualizer_smoothing": 75,

    # WALLPAPER — Layers
    "wallpaper_layer_order": [
        "Background", "Visualizer", "Lyrics", "Title", "Artist", "Album Art", "Vinyl"
    ],

    # WALLPAPER — Behavior
    "wallpaper_pause_on_battery": False,
    "wallpaper_pause_on_fullscreen": False,
    "wallpaper_performance_mode": "Balanced",  # "High", "Balanced", "Battery Saver"
    "wallpaper_fps": 30,
    "wallpaper_startup_behavior": "Restore Previous",  # "Enabled", "Disabled", "Restore Previous"
    "wallpaper_snapping": True,
    "wallpaper_debug_hud": False,

    # ══════════════════════════════════════════════════════════════════════
    # GLOBAL APPEARANCE
    # ══════════════════════════════════════════════════════════════════════
    # Appearance — Theme
    "theme_mode": "Dynamic Album Accent",
    # Appearance — Glass
    "glass_intensity": 75,
    "glass_panel_opacity": 70,
    "glass_blur": 20,
    "glass_border_opacity": 10,
    "glass_highlight_intensity": 4,
    "glass_shadow": True,
    # Appearance — Accent
    "manual_accent_color": "#1DB954",
    "accent_clamp_saturation": True,
    "accent_clamp_luminosity": True,
    # Appearance — Background
    "background_style": "Cosmic Nebula",
    "background_intensity": 100,
    "background_blur": 0,
    "background_custom_image": "",
    # Appearance — Motion
    "animation_intensity": "Standard",     # "Subtle", "Standard", "Expressive", "Off"
    "reduced_motion": False,

    # ══════════════════════════════════════════════════════════════════════
    # GLOBAL BEHAVIOR
    # ══════════════════════════════════════════════════════════════════════
    # Behavior — Window
    "window_mode": "Normal",               # "Normal", "Compact", "Fullscreen"
    "remember_geometry": True,
    "start_position": "Last Position",     # "Last Position", "Center", "Top-Left"
    # Behavior — Tray
    "show_tray_icon": True,
    "close_action": "Minimize to Tray",
    "minimize_to_tray": True,
    # Behavior — Interaction
    # (click_through, always_on_top, exclude_from_capture, lock_position — defined above in Lyrics)
    # Behavior — Startup
    "start_with_windows": False,
    "startup_restore_state": True,
    # Behavior — Power
    "power_pause_wallpaper_on_battery": False,
    "power_pause_visualizer_on_battery": False,
    "power_pause_on_fullscreen": False,

    # ══════════════════════════════════════════════════════════════════════
    # SHORTCUTS
    # ══════════════════════════════════════════════════════════════════════
    "shortcut_toggle_overlay": "Ctrl+H",
    "shortcut_refresh": "Ctrl+R",
    "shortcut_nudge_minus": "Ctrl+Left",
    "shortcut_nudge_plus": "Ctrl+Right",
    "shortcut_toggle_visualizer": "Ctrl+Shift+V",
    "shortcut_toggle_game_overlay": "Ctrl+Shift+G",
    "shortcut_command_palette": "Ctrl+K",
    "shortcut_settings_search": "Ctrl+F",

    # ══════════════════════════════════════════════════════════════════════
    # PERFORMANCE
    # ══════════════════════════════════════════════════════════════════════
    "power_profile": "Balanced",
    "preview_fps": 60,
    "background_polling_ms": 80,

    # ══════════════════════════════════════════════════════════════════════
    # PROFILES & PRESETS
    # ══════════════════════════════════════════════════════════════════════
    "active_profile": "Default",
    "profiles": {}
}

# ══════════════════════════════════════════════════════════════════════════════
# LEGACY PROFILES (backward compat)
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    "Default Clean": {
        "text_color": "#FFFFFF",
        "bg_color": "#000000",
        "bg_opacity": 0,
        "border_enabled": False,
        "shadow_enabled": True,
        "shadow_color": "#000000",
        "shadow_blur": 8,
        "font_bold": True,
        "context_lines": 2,
    },
    "Spotify Dark": {
        "text_color": "#1DB954",
        "bg_color": "#121212",
        "bg_opacity": 80,
        "border_enabled": False,
        "shadow_enabled": True,
        "shadow_color": "#000000",
        "shadow_blur": 10,
        "font_bold": True,
        "context_lines": 3,
    },
    "Cinematic Cyan": {
        "text_color": "#00F3FF",
        "bg_color": "#0D0D14",
        "bg_opacity": 75,
        "border_enabled": False,
        "shadow_enabled": True,
        "shadow_color": "#00F3FF",
        "shadow_blur": 14,
        "font_bold": True,
        "context_lines": 2,
    },
    "Neon Spectrum": {
        "text_color": "#FF007F",
        "bg_color": "#0A0A10",
        "bg_opacity": 60,
        "border_enabled": False,
        "shadow_enabled": True,
        "shadow_color": "#FF007F",
        "shadow_blur": 16,
        "font_bold": True,
        "context_lines": 2,
    },
    "Minimal Gaming": {
        "text_color": "#FFFF00",
        "bg_color": "#000000",
        "bg_opacity": 90,
        "border_enabled": False,
        "shadow_enabled": False,
        "shadow_color": "#000000",
        "shadow_blur": 0,
        "font_bold": True,
        "context_lines": 1,
    }
}

PRESETS = DEFAULT_PROFILES

# ══════════════════════════════════════════════════════════════════════════════
# DOMAIN-SPECIFIC PRESETS
# ══════════════════════════════════════════════════════════════════════════════

LYRICS_PRESETS: Dict[str, Dict[str, Any]] = {
    "Default": {
        "lyrics_view_mode": "Multi-line",
        "font_family": "Segoe UI", "font_size": 24, "font_bold": True,
        "text_color": "#FFFFFF", "context_line_opacity": 45,
        "shadow_enabled": True, "shadow_blur": 8,
        "lyrics_animation_preset": "Smooth", "animation_speed_ms": 400,
        "context_lines": 2,
    },
    "Minimal": {
        "lyrics_view_mode": "Single-line Ticker",
        "font_family": "Inter", "font_size": 18, "font_bold": False,
        "text_color": "#E0E0E0", "context_line_opacity": 0,
        "shadow_enabled": False, "shadow_blur": 0,
        "lyrics_animation_preset": "Fast", "animation_speed_ms": 200,
        "context_lines": 0,
    },
    "Cinematic": {
        "lyrics_view_mode": "Multi-line",
        "font_family": "Georgia", "font_size": 32, "font_bold": True,
        "text_color": "#00F3FF", "context_line_opacity": 30,
        "shadow_enabled": True, "shadow_blur": 16,
        "lyrics_glow_enabled": True, "lyrics_glow_radius": 20, "lyrics_glow_color": "#00F3FF",
        "lyrics_animation_preset": "Cinematic", "animation_speed_ms": 600,
        "context_lines": 3,
    },
    "Karaoke": {
        "lyrics_view_mode": "Karaoke",
        "font_family": "Arial Black", "font_size": 28, "font_bold": True,
        "text_color": "#FFFF00", "context_line_opacity": 50,
        "shadow_enabled": True, "shadow_blur": 10,
        "lyrics_animation_preset": "Smooth", "animation_speed_ms": 300,
        "context_lines": 1,
    },
}

WALLPAPER_PRESETS: Dict[str, Dict[str, Any]] = {
    "Default": {
        "wallpaper_vinyl_size": 0.20, "wallpaper_vinyl_opacity": 100,
        "wallpaper_rotation_speed": 12.0, "wallpaper_vinyl_shadow": False,
        "wallpaper_vinyl_audio_reactive": False,
        "wallpaper_show_title": True, "wallpaper_show_artist": True,
    },
    "Minimal": {
        "wallpaper_vinyl_size": 0.15, "wallpaper_vinyl_opacity": 80,
        "wallpaper_rotation_speed": 20.0, "wallpaper_vinyl_shadow": False,
        "wallpaper_vinyl_audio_reactive": False,
        "wallpaper_show_title": True, "wallpaper_show_artist": False,
    },
    "Cinematic": {
        "wallpaper_vinyl_size": 0.28, "wallpaper_vinyl_opacity": 100,
        "wallpaper_rotation_speed": 8.0, "wallpaper_vinyl_shadow": True,
        "wallpaper_vinyl_glow": True, "wallpaper_vinyl_glow_color": "#8B5CF6",
        "wallpaper_vinyl_audio_reactive": True, "wallpaper_vinyl_bass_response": 60,
        "wallpaper_show_title": True, "wallpaper_show_artist": True,
    },
    "Vinyl Focus": {
        "wallpaper_vinyl_size": 0.35, "wallpaper_vinyl_opacity": 100,
        "wallpaper_vinyl_x": 0.50, "wallpaper_vinyl_y": 0.45,
        "wallpaper_rotation_speed": 6.0, "wallpaper_vinyl_shadow": True,
        "wallpaper_vinyl_reflection": True,
        "wallpaper_vinyl_audio_reactive": True, "wallpaper_vinyl_bass_response": 80,
        "wallpaper_show_title": True, "wallpaper_show_artist": True,
    },
}

VISUALIZER_PRESETS: Dict[str, Dict[str, Any]] = {
    "Default": {
        "visualizer_style": "Pill Bars", "visualizer_bar_count": 32,
        "visualizer_smoothing": 75, "visualizer_sensitivity": 100,
        "visualizer_color_mode": "Solid", "visualizer_color": "#FFFFFF",
        "visualizer_glow_enabled": False,
    },
    "Minimal": {
        "visualizer_style": "Standard Bars", "visualizer_bar_count": 16,
        "visualizer_smoothing": 85, "visualizer_sensitivity": 80,
        "visualizer_color_mode": "Solid", "visualizer_color": "#E0E0E0",
        "visualizer_glow_enabled": False,
    },
    "Gaming": {
        "visualizer_style": "Pill Bars", "visualizer_bar_count": 48,
        "visualizer_smoothing": 60, "visualizer_sensitivity": 120,
        "visualizer_color_mode": "Gradient",
        "visualizer_gradient_stops": [
            {"pos": 0.0, "color": "#FF0040"},
            {"pos": 0.5, "color": "#FF8C00"},
            {"pos": 1.0, "color": "#FFD700"}
        ],
        "visualizer_glow_enabled": True, "visualizer_glow_radius": 6,
    },
    "Spectrum": {
        "visualizer_style": "Square Bar", "visualizer_bar_count": 64,
        "visualizer_smoothing": 50, "visualizer_sensitivity": 110,
        "visualizer_color_mode": "Gradient",
        "visualizer_gradient_stops": [
            {"pos": 0.0, "color": "#FF4D8D"},
            {"pos": 0.33, "color": "#8B5CF6"},
            {"pos": 0.66, "color": "#3B82F6"},
            {"pos": 1.0, "color": "#2ED573"}
        ],
        "visualizer_glow_enabled": True, "visualizer_glow_radius": 10,
    },
}


def _get_app_config_dir() -> str:
    """Returns platform-appropriate user config directory."""
    if os.name == 'nt':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        base = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
    config_dir = os.path.join(base, 'Lyrune')
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


class SettingsManager:
    """
    Manages persistent configuration settings for Lyrune.
    Includes schema migrations, corrupt recovery, export/import, and profile presets.
    """

    def __init__(self, filename: str = "settings.json"):
        self.app_dir = _get_app_config_dir()
        self.filepath = os.path.join(self.app_dir, filename)
        self.backup_dir = os.path.join(self.app_dir, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

        # Legacy local settings migration
        legacy_paths = [os.path.join(_LOCAL_DIR, filename), os.path.join(_LOCAL_DIR, 'lyrune', filename)]
        if not os.path.exists(self.filepath):
            for local_path in legacy_paths:
                if os.path.exists(local_path):
                    try:
                        shutil.copy2(local_path, self.filepath)
                    except Exception:
                        pass
                    break

        self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._save_timer: Optional[QTimer] = None
        self._dirty = False
        self.load()

        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.save_immediate)

    def _migrate_schema(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Applies schema migrations to older config files."""
        migrated = dict(raw)
        version = raw.get("settings_schema_version", 1)

        if version < 2:
            from lyrune.logger import log_event
            log_event(f"⚙️ [SettingsManager] Migrating schema from v{version} to v2...")

            # Canonical scaling mode names
            scaling = str(migrated.get("wallpaper_scaling_mode", "fill")).lower()
            if scaling in ("fill", "fit", "stretch", "center"):
                migrated["wallpaper_scaling_mode"] = scaling
            else:
                migrated["wallpaper_scaling_mode"] = "fill"

            # Canonical orientation names
            orientation = str(migrated.get("visualizer_orientation", "BOTTOM")).upper()
            if orientation in ("TOP", "BOTTOM", "LEFT", "RIGHT"):
                migrated["visualizer_orientation"] = orientation

            version = 2

        if version < 3:
            from lyrune.logger import log_event
            log_event(f"⚙️ [SettingsManager] Migrating schema from v{version} to v3...")

            # Map old lyrics_view_mode values
            old_mode = migrated.get("lyrics_view_mode", "Multi-line")
            if old_mode not in ("Multi-line", "Single-line Ticker", "Minimal", "Karaoke"):
                migrated["lyrics_view_mode"] = "Multi-line"

            # Propagate old context_lines to new before/after
            ctx = migrated.get("context_lines", 2)
            if "context_lines_before" not in migrated:
                migrated["context_lines_before"] = max(0, ctx - 1)
            if "context_lines_after" not in migrated:
                migrated["context_lines_after"] = ctx

            version = 3

        # Add missing defaults for any version
        for key, val in DEFAULT_SETTINGS.items():
            if key not in migrated:
                migrated[key] = val

        migrated["settings_schema_version"] = CURRENT_SCHEMA_VERSION
        return migrated

    # === Domain Preset Methods ===

    def apply_domain_preset(self, domain: str, preset_name: str) -> bool:
        """
        Apply a domain-specific preset (Lyrics, Wallpaper, Visualizer).
        Returns True if the preset was found and applied.
        """
        presets_map = {
            "lyrics": LYRICS_PRESETS,
            "wallpaper": WALLPAPER_PRESETS,
            "visualizer": VISUALIZER_PRESETS,
        }
        domain_presets = presets_map.get(domain.lower())
        if not domain_presets or preset_name not in domain_presets:
            return False

        self.settings.update(domain_presets[preset_name])
        self.save()
        from lyrune.logger import log_event
        log_event(f"🎨 [SettingsManager] Applied {domain} preset: {preset_name}")
        return True

    def reset_section(self, prefix: str) -> Dict[str, Any]:
        """
        Reset all settings whose key starts with `prefix` to their defaults.
        Returns dict of keys that were reset.
        """
        reset_keys = {}
        for key, default_val in DEFAULT_SETTINGS.items():
            if key.startswith(prefix):
                if self.settings.get(key) != default_val:
                    self.settings[key] = default_val
                    reset_keys[key] = default_val
        if reset_keys:
            self.save()
            from lyrune.logger import log_event
            log_event(f"🔄 [SettingsManager] Reset {len(reset_keys)} settings with prefix '{prefix}'")
        return reset_keys

    def get_section_keys(self, prefix: str) -> Dict[str, Any]:
        """Get all default settings whose key starts with the given prefix."""
        return {k: v for k, v in DEFAULT_SETTINGS.items() if k.startswith(prefix)}

    def load(self) -> Dict[str, Any]:
        """Load settings from disk, merging with defaults and running migrations."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    saved = json.load(f)

                migrated = self._migrate_schema(saved)

                # Merge over defaults
                self.settings = dict(DEFAULT_SETTINGS)
                self.settings.update(migrated)

                # Strip unknown obsolete keys
                orphaned = [k for k in list(self.settings.keys()) if k not in DEFAULT_SETTINGS]
                for k in orphaned:
                    del self.settings[k]

                if orphaned:
                    from lyrune.logger import log_event
                    log_event(f"[SettingsManager] Pruned {len(orphaned)} obsolete key(s): {orphaned}")
                    self._write_to_disk()

            except Exception as e:
                from lyrune.logger import log_event
                log_event(f"⚠️ [SettingsManager Warning] Corrupted settings file, backing up & recovering defaults: {e}")

                # Backup corrupt file
                corrupt_backup = os.path.join(
                    self.backup_dir,
                    f"settings_corrupt_{int(time.time())}.json"
                )
                try:
                    shutil.copy2(self.filepath, corrupt_backup)
                    log_event(f"💾 [SettingsManager] Saved corrupt settings copy to: {corrupt_backup}")
                except Exception:
                    pass

                self.settings = dict(DEFAULT_SETTINGS)
                self._write_to_disk()
        else:
            self.settings = dict(DEFAULT_SETTINGS)
            self._write_to_disk()

        return self.settings

    def _write_to_disk(self) -> None:
        """Immediate atomic write to disk via temp file."""
        tmp_path = f"{self.filepath}.tmp_{os.getpid()}_{int(time.time() * 1000)}"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
            os.replace(tmp_path, self.filepath)
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            from lyrune.logger import log_event
            log_event(f"❌ [SettingsManager Exception] Failed to write settings to disk: {e}")
        self._dirty = False

    def _schedule_save(self) -> None:
        """Debounced save: writes to disk after 400ms of inactivity."""
        self._dirty = True
        if self._save_timer is None:
            self._save_timer = QTimer()
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self._on_save_timer)
        self._save_timer.start(400)

    def _on_save_timer(self) -> None:
        if self._dirty:
            self._write_to_disk()

    def save(self) -> None:
        self._schedule_save()

    def save_immediate(self) -> None:
        if self._save_timer and self._save_timer.isActive():
            self._save_timer.stop()
        self._write_to_disk()

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self.save()

    def update(self, new_settings: Dict[str, Any]) -> None:
        self.settings.update(new_settings)
        self.save()

    def reset_to_defaults(self) -> Dict[str, Any]:
        self.settings = dict(DEFAULT_SETTINGS)
        self.save_immediate()
        return self.settings

    # === Backup & Restore ===

    def create_backup(self, label: str = "") -> str:
        """Creates a timestamped snapshot backup of current settings."""
        ts = time.strftime("%Y%m%d_%H%M%S")
        safe_label = f"_{label.strip().replace(' ', '_')}" if label else ""
        filename = f"backup_{ts}{safe_label}.json"
        target_path = os.path.join(self.backup_dir, filename)

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=4)

        from lyrune.logger import log_event
        log_event(f"💾 [SettingsManager] Backup created: {filename}")
        return target_path

    def restore_backup(self, backup_path: str) -> bool:
        """Restores settings from a backup JSON file."""
        if not os.path.exists(backup_path):
            return False
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            migrated = self._migrate_schema(data)
            self.settings.update(migrated)
            self.save_immediate()
            from lyrune.logger import log_event
            log_event(f"🔄 [SettingsManager] Restored settings from backup: {os.path.basename(backup_path)}")
            return True
        except Exception as e:
            from lyrune.logger import log_event
            log_event(f"❌ [SettingsManager] Failed to restore backup: {e}")
            return False

    def list_backups(self) -> List[Dict[str, Any]]:
        """Returns sorted list of available backup files."""
        if not os.path.exists(self.backup_dir):
            return []
        items = []
        for fn in sorted(os.listdir(self.backup_dir), reverse=True):
            if fn.endswith(".json"):
                full_p = os.path.join(self.backup_dir, fn)
                items.append({
                    "filename": fn,
                    "path": full_p,
                    "size": os.path.getsize(full_p),
                    "time": time.ctime(os.path.getmtime(full_p))
                })
        return items

    # === Import & Export ===

    def export_settings(self, export_path: str) -> bool:
        try:
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
            return True
        except Exception as e:
            from lyrune.logger import log_event
            log_event(f"❌ [SettingsManager] Export failed: {e}")
            return False

    def import_settings(self, import_path: str) -> bool:
        if not os.path.exists(import_path):
            return False
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            migrated = self._migrate_schema(data)
            self.settings.update(migrated)
            self.save_immediate()
            return True
        except Exception as e:
            from lyrune.logger import log_event
            log_event(f"❌ [SettingsManager] Import failed: {e}")
            return False

    # === Profiles ===

    def get_profiles(self) -> List[str]:
        builtin = list(DEFAULT_PROFILES.keys())
        custom = list(self.settings.get("profiles", {}).keys())
        return builtin + [c for c in custom if c not in builtin]

    def save_profile(self, name: str) -> bool:
        if not name:
            return False
        profiles = self.settings.setdefault("profiles", {})
        profiles[name] = dict(self.settings)
        self.settings["active_profile"] = name
        self.save()
        return True

    def load_profile(self, name: str) -> bool:
        if name in DEFAULT_PROFILES:
            preset = DEFAULT_PROFILES[name]
            self.settings.update(preset)
            self.settings["active_profile"] = name
            self.save_immediate()
            return True
        profiles = self.settings.get("profiles", {})
        if name in profiles:
            self.settings.update(profiles[name])
            self.settings["active_profile"] = name
            self.save_immediate()
            return True
        return False
