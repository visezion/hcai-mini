from typing import Dict


class Safety:
    def __init__(self, limits: Dict[str, Dict[str, float]]) -> None:
        self.limits = limits

    @staticmethod
    def _rate_limit(prev: float | None, new: float, max_delta: float) -> float:
        if prev is None:
            return new
        delta = new - prev
        if abs(delta) > max_delta:
            return prev + (max_delta if delta > 0 else -max_delta)
        return new

    def enforce(self, current: Dict[str, float], proposed: Dict[str, float]) -> Dict[str, float]:
        out = {}
        temp_limits = self.limits["temp_c"]
        fan_limits = self.limits["fan_rpm"]
        temp = max(temp_limits["min"], min(temp_limits["max"], proposed["supply_temp_c"]))
        fan = max(fan_limits["min"], min(fan_limits["max"], proposed["fan_rpm"]))
        temp = self._rate_limit(current.get("supply_temp_c"), temp, temp_limits["max_delta_per_min"])
        fan = self._rate_limit(current.get("fan_rpm"), fan, fan_limits["max_delta_per_min"])
        out["supply_temp_c"] = round(temp, 1)
        out["fan_rpm"] = int(fan)
        out["safety_summary"] = "limits, rate limits applied"
        return out
