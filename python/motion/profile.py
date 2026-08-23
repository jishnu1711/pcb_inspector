"""Deterministic scalar trapezoidal/triangular motion profiles."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt


@dataclass(frozen=True)
class ScalarProfile:
    distance_mm: float
    max_speed_mm_s: float
    max_acceleration_mm_s2: float
    duration_s: float
    acceleration_time_s: float
    cruise_time_s: float
    peak_speed_mm_s: float

    def distance_at(self, time_s: float) -> float:
        time_s = min(max(time_s, 0.0), self.duration_s)
        acceleration = self.max_acceleration_mm_s2
        accel_time = self.acceleration_time_s
        if time_s <= accel_time:
            return 0.5 * acceleration * time_s * time_s
        accel_distance = 0.5 * acceleration * accel_time * accel_time
        if time_s <= accel_time + self.cruise_time_s:
            return accel_distance + self.peak_speed_mm_s * (time_s - accel_time)
        remaining = self.duration_s - time_s
        return self.distance_mm - 0.5 * acceleration * remaining * remaining

    def samples(self, dt_s: float) -> tuple[float, ...]:
        if dt_s <= 0:
            raise ValueError("dt_s must be positive")
        if self.distance_mm == 0:
            return (0.0,)
        count = ceil(self.duration_s / dt_s)
        return tuple(min(self.distance_at(index * dt_s), self.distance_mm) for index in range(count)) + (self.distance_mm,)


def make_profile(distance_mm: float, max_speed_mm_s: float, max_acceleration_mm_s2: float) -> ScalarProfile:
    if distance_mm < 0 or max_speed_mm_s <= 0 or max_acceleration_mm_s2 <= 0:
        raise ValueError("distance must be non-negative and limits must be positive")
    if distance_mm == 0:
        return ScalarProfile(0.0, max_speed_mm_s, max_acceleration_mm_s2, 0.0, 0.0, 0.0, 0.0)
    accel_time = max_speed_mm_s / max_acceleration_mm_s2
    accel_distance = 0.5 * max_acceleration_mm_s2 * accel_time * accel_time
    if 2.0 * accel_distance >= distance_mm:
        accel_time = sqrt(distance_mm / max_acceleration_mm_s2)
        peak_speed = max_acceleration_mm_s2 * accel_time
        cruise_time = 0.0
    else:
        peak_speed = max_speed_mm_s
        cruise_time = (distance_mm - 2.0 * accel_distance) / peak_speed
    return ScalarProfile(
        distance_mm, max_speed_mm_s, max_acceleration_mm_s2,
        2.0 * accel_time + cruise_time, accel_time, cruise_time, peak_speed,
    )
