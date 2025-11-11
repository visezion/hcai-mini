from typing import Dict


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class MPCController:
    def __init__(self, limits: Dict[str, Dict[str, float]], weights: Dict[str, float]) -> None:
        self.limits = limits
        self.weights = weights

    def propose(self, forecast_temp: list[float], current_set: Dict[str, float]) -> Dict[str, float]:
        target = 23.0
        lookahead = min(5, len(forecast_temp) - 1) if forecast_temp else 0
        error = forecast_temp[lookahead] - target if forecast_temp else 0.0
        fan = current_set.get("fan_rpm", 1200)
        supply = current_set.get("supply_temp_c", 18.0)
        delta_fan = 150 if error > 0 else -100
        delta_temp = -0.3 if error > 0 else 0.2
        new_fan = clamp(fan + delta_fan, self.limits["fan_rpm"]["min"], self.limits["fan_rpm"]["max"])
        new_supply = clamp(supply + delta_temp, self.limits["temp_c"]["min"], self.limits["temp_c"]["max"])
        return {"supply_temp_c": round(new_supply, 1), "fan_rpm": int(new_fan)}
