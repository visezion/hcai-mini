from __future__ import annotations

import numpy as np


class Forecaster:
    def __init__(self, horizon: int = 30) -> None:
        self.horizon = horizon

    def predict(self, series: np.ndarray) -> tuple[list[float], list[float], list[float]]:
        if series.size == 0:
            series = np.zeros(10)
        trend_window = min(10, series.size - 1) if series.size > 1 else 1
        trend = 0.0
        if trend_window > 0:
            trend = (series[-1] - series[-trend_window - 1]) / trend_window if series.size > trend_window + 1 else 0.0
        preds = [float(series[-1] + (i + 1) * trend * 0.5) for i in range(self.horizon)]
        lo = [p - 0.8 for p in preds]
        hi = [p + 0.8 for p in preds]
        return preds, lo, hi
