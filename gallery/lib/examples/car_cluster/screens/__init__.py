# SPDX-License-Identifier: MIT
"""Center tab pages for the instrument cluster."""

from .assist import build as build_assist
from .engine import build as build_engine
from .lights import build as build_lights
from .speed import build as build_speed
from .theme_screen import build as build_theme
from .tires import build as build_tires
from .trip_a import build as build_trip_a
from .trip_b import build as build_trip_b

BUILDERS = (
    build_speed,
    build_trip_a,
    build_trip_b,
    build_engine,
    build_lights,
    build_tires,
    build_assist,
    build_theme,
)

TAB_NAMES = (
    "Speed",
    "Trip A",
    "Trip B",
    "Engine",
    "Lights",
    "Tires",
    "Assist",
    "Theme",
)
