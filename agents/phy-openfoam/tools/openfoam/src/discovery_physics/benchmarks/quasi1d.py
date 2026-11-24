"""Isentropic quasi-one-dimensional nozzle relations (independent implementation)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Nozzle1D:
    throat_radius: float
    total_pressure: float
    total_temperature: float
    gamma: float = 1.4
    gas_constant: float = 287.0

    def area_ratio(self, mach: float) -> float:
        g = self.gamma
        return (1 / mach) * ((2 / (g + 1)) * (1 + (g - 1) / 2 * mach * mach)) ** ((g + 1) / (2 * (g - 1)))

    def mach(self, radius: float, supersonic: bool) -> float:
        target = (radius / self.throat_radius) ** 2
        if target < 1:
            raise ValueError("radius below throat radius")
        lo, hi = (1.0, 50.0) if supersonic else (1e-9, 1.0)
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if (self.area_ratio(mid) < target) == supersonic:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def state(self, radius: float, supersonic: bool) -> tuple[float, float, float, float]:
        """Return static pressure, temperature, speed, and Mach number."""
        g, R = self.gamma, self.gas_constant
        m = self.mach(radius, supersonic)
        t = self.total_temperature / (1 + (g - 1) / 2 * m * m)
        p = self.total_pressure * (t / self.total_temperature) ** (g / (g - 1))
        return p, t, m * math.sqrt(g * R * t), m

    def choked_mass_flow(self) -> float:
        g, R = self.gamma, self.gas_constant
        area = math.pi * self.throat_radius ** 2
        return (area * self.total_pressure / math.sqrt(self.total_temperature) * math.sqrt(g / R)
                * (2 / (g + 1)) ** ((g + 1) / (2 * (g - 1))))
