"""Simulated servo diverter.

No physical servo is driven. This class only tracks the angle a real
SG90/MG996R-style servo *would* be commanded to, so the dashboard can show
what the diverter flap is doing.
"""

from __future__ import annotations

import threading

from services.classifier import WET, DRY, METAL, NONE


class SimulatedServo:
    def __init__(self, wet_angle: int, dry_angle: int, metal_angle: int, idle_angle: int):
        for angle in (wet_angle, dry_angle, metal_angle, idle_angle):
            if not 0 <= angle <= 180:
                raise ValueError("servo angles must be between 0 and 180 degrees")
        self.angles = {WET: wet_angle, DRY: dry_angle, METAL: metal_angle}
        self.idle_angle = idle_angle
        self.current_angle = idle_angle
        self._lock = threading.Lock()

    def divert(self, category: str) -> dict:
        """Move the (simulated) flap for a category and describe the action."""
        with self._lock:
            previous = self.current_angle
            if category == NONE:
                return {
                    "action": "NO_ACTION",
                    "from_angle": previous,
                    "target_angle": previous,
                    "description": "No item detected - servo held in place",
                }
            target = self.angles[category]
            # A real diverter would move to the target, drop the item, then
            # return to idle. We record the target and settle back at idle.
            self.current_angle = self.idle_angle
            return {
                "action": f"ROTATE_TO_{category}",
                "from_angle": previous,
                "target_angle": target,
                "description": (
                    f"Rotated {previous} -> {target} deg for {category.lower()} bin, "
                    f"returned to {self.idle_angle} deg"
                ),
            }

    def to_dict(self) -> dict:
        return {
            "simulated": True,
            "current_angle": self.current_angle,
            "idle_angle": self.idle_angle,
            "angles": dict(self.angles),
        }
