# SPDX-License-Identifier: MIT
"""Believable vehicle state for the instrument cluster demo.

Drive state is automatic: a looping profile varies gear, speed, RPM, and oil
pressure over time. Digit keys are not used. Speed tracks roughly 10× gear.
"""

import math

_IDLE_RPM = 1000
_MAX_ACCEL_RPM = 7000
_REDLINE = 6500
_CYCLE_S = 72.0

# Piecewise drive profile: (end_time_s, gear, throttle).
# Speed target is ~gear × 10 mph. Throttle drives RPM and accel feel.
_PROFILE = (
    (4.0, 0, 0.0),  # park / idle
    (8.0, 1, 0.05),  # creep
    (16.0, 3, 0.75),  # pull away
    (24.0, 5, 0.55),  # build to ~50
    (34.0, 6, 0.35),  # cruise ~60
    (42.0, 8, 1.0),  # hard accel → ~7k RPM
    (50.0, 7, 0.40),  # settle ~70
    (60.0, 3, 0.0),  # coast / brake
    (66.0, 1, 0.0),  # idle in gear
    (72.0, 0, 0.0),  # park
)


def _clamp(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _lerp(a, b, t):
    return a + (b - a) * t


def _profile_at(t):
    """Return (gear, throttle) for absolute time ``t`` (seconds)."""
    u = t % _CYCLE_S
    prev_t, prev_g, prev_thr = 0.0, 0, 0.0
    for end_t, gear, thr in _PROFILE:
        if u <= end_t:
            span = end_t - prev_t
            if span <= 1e-6:
                return gear, thr
            f = (u - prev_t) / span
            # Hold gear as integer steps; blend throttle smoothly.
            g = gear if f >= 0.35 else prev_g
            if prev_g == 0 and gear > 0 and f < 0.15:
                g = 0
            return int(g), _lerp(prev_thr, thr, f)
        prev_t, prev_g, prev_thr = end_t, gear, thr
    return 0, 0.0


class Vehicle:
    def __init__(self):
        self.gear = 0  # 0 = Park, 1..10
        self.throttle = 0.0
        self.speed_mph = 0.0
        self.rpm = float(_IDLE_RPM)
        self.fuel_frac = 0.625  # fixed ~5/8 tank
        self.coolant_f = 210.6  # fixed
        self.oil_psi = 22.0
        self.oil_temp_f = 205.0
        self.battery_v = 14.2
        self.iat_f = 95.0
        self.engine_hours = 128.4
        self.odo_miles = 48217.6
        self.speedo_mode = "digital"  # or "analog"
        self.trip_a = self._new_trip()
        self.trip_b = self._new_trip()
        self.lights = {
            "autodim": True,
            "delayed_off": True,
            "drl": True,
            "fog": False,
            "cabin": False,
            "brightness": 0.85,
            "high_beam": False,
            "turn_left": False,
            "turn_right": False,
        }
        self.tires = [
            {"name": "FL", "psi": 34.0, "temp_f": 86.0},
            {"name": "FR", "psi": 34.5, "temp_f": 87.0},
            {"name": "RL", "psi": 33.0, "temp_f": 90.0},
            {"name": "RR", "psi": 33.5, "temp_f": 89.0},
            {"name": "Spare", "psi": 40.0, "temp_f": 72.0},
        ]
        self.assist = {
            "acc": True,
            "acc_set": 65,
            "lane_keep": True,
            "blind_spot": True,
            "park_fl": 0.15,
            "park_fr": 0.18,
            "park_rl": 0.55,
            "park_rr": 0.52,
        }
        self.redline = False
        self._t = 0.0
        self._accel = 0.0  # mph/s, for oil response

    def _new_trip(self):
        return {
            "distance": 0.0,
            "time_s": 0.0,
            "fuel_used": 0.0,
            "max_speed": 0.0,
        }

    def gear_label(self):
        if self.gear <= 0:
            return "P"
        return str(int(self.gear))

    def set_gear(self, g):
        self.gear = int(_clamp(g, 0, 10))

    def set_throttle(self, t):
        self.throttle = _clamp(float(t), 0.0, 1.0)

    def toggle_speedo_mode(self):
        self.speedo_mode = "analog" if self.speedo_mode == "digital" else "digital"

    def reset_trip(self, which):
        if which == "a":
            self.trip_a = self._new_trip()
        elif which == "b":
            self.trip_b = self._new_trip()

    def trip_avg_speed(self, which):
        trip = self.trip_a if which == "a" else self.trip_b
        if trip["time_s"] < 1.0:
            return 0.0
        return trip["distance"] / (trip["time_s"] / 3600.0)

    def trip_mpg(self, which):
        trip = self.trip_a if which == "a" else self.trip_b
        if trip["fuel_used"] < 0.01:
            return 0.0
        return trip["distance"] / trip["fuel_used"]

    def tick(self, dt_s):
        if dt_s <= 0:
            return
        if dt_s > 0.2:
            dt_s = 0.2

        self._t += dt_s
        gear_tgt, thr_tgt = _profile_at(self._t)
        self.gear = int(gear_tgt)
        self.throttle = _lerp(self.throttle, thr_tgt, min(1.0, dt_s * 3.0))

        # Speed tracks roughly 10 × gear.
        if self.gear <= 0:
            target_speed = 0.0
        else:
            target_speed = float(self.gear * 10)

        prev_speed = self.speed_mph
        # Accelerate a bit faster than we decelerate so pulls feel eager.
        speed_rate = 2.8 if target_speed > self.speed_mph else 1.8
        self.speed_mph = _lerp(self.speed_mph, target_speed, min(1.0, dt_s * speed_rate))
        if self.speed_mph < 0.2:
            self.speed_mph = 0.0
        self._accel = (self.speed_mph - prev_speed) / dt_s

        # RPM: 1k idle → 7k at strongest acceleration.
        idle = self.gear <= 0 or (self.speed_mph < 1.5 and self.throttle < 0.08)
        if idle:
            target_rpm = float(_IDLE_RPM)
        else:
            accel_n = _clamp(self._accel / 10.0, 0.0, 1.0)
            # Hard throttle and rising speed push toward redline; cruise is calmer.
            demand = _clamp(max(self.throttle, accel_n * 0.9), 0.0, 1.0)
            if self.throttle < 0.12 and self._accel <= 0.5:
                demand = _clamp(0.12 + self.speed_mph / 120.0, 0.12, 0.35)
            target_rpm = _IDLE_RPM + (_MAX_ACCEL_RPM - _IDLE_RPM) * demand

        self.rpm = _lerp(self.rpm, target_rpm, min(1.0, dt_s * 4.5))
        self.redline = self.rpm >= _REDLINE

        # Oil pressure: 15–30 idle, 35–65 driving; rises on accel, falls on decel.
        if idle:
            # Mild idle wander with a quiet sine so the needle isn't frozen.
            wobble = 0.5 + 0.5 * math.sin(self._t * 0.7)
            target_oil = 18.0 + 10.0 * wobble  # ~18..28 within 15–30
        else:
            drive = _clamp(self.speed_mph / 80.0, 0.0, 1.0)
            target_oil = 40.0 + 15.0 * drive  # ~40..55 baseline while moving
            accel_n = _clamp(self._accel / 10.0, -1.0, 1.0)
            target_oil += accel_n * 12.0
            target_oil = _clamp(target_oil, 35.0, 65.0)
        oil_rate = 3.5 if abs(self._accel) > 1.0 else 2.0
        self.oil_psi = _lerp(self.oil_psi, target_oil, min(1.0, dt_s * oil_rate))
        if idle:
            self.oil_psi = _clamp(self.oil_psi, 15.0, 30.0)
        else:
            self.oil_psi = _clamp(self.oil_psi, 35.0, 65.0)

        # Fuel + coolant stay fixed. Ancillary temps still breathe a little.
        load = _clamp(self.throttle * 0.7 + (self.rpm / 10000.0) * 0.3, 0.0, 1.0)
        self.oil_temp_f = _lerp(self.oil_temp_f, 190.0 + load * 30.0, min(1.0, dt_s * 0.1))
        self.iat_f = _lerp(self.iat_f, 85.0 + load * 25.0, min(1.0, dt_s * 0.08))
        self.battery_v = _lerp(
            self.battery_v, 13.8 + (0.6 if self.rpm > 500 else 0.0), min(1.0, dt_s)
        )

        dist = self.speed_mph * (dt_s / 3600.0)
        self.odo_miles += dist
        if self.rpm > 100:
            self.engine_hours += dt_s / 3600.0

        # Trip fuel_used for MPG only — does not drain the fuel gauge.
        burn = (0.000005 + self.throttle * 0.00004 + self.speed_mph * 0.00000015) * dt_s
        for trip in (self.trip_a, self.trip_b):
            if self.speed_mph > 0.5:
                trip["distance"] += dist
                trip["time_s"] += dt_s
                trip["fuel_used"] += burn * 12.0
                if self.speed_mph > trip["max_speed"]:
                    trip["max_speed"] = self.speed_mph

        for tire in self.tires:
            if tire["name"] == "Spare":
                continue
            target_t = 75.0 + self.speed_mph * 0.25
            tire["temp_f"] = _lerp(tire["temp_f"], target_t, min(1.0, dt_s * 0.05))
