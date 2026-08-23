# SPDX-License-Identifier: MIT
"""Trip computer B."""

from screens.trip_a import TripScreen


class TripBScreen(TripScreen):
    which = "b"
    title = "TRIP B"


def build(page, vehicle, group, w=0, h=0):
    return TripBScreen(page, vehicle, group, w, h)
