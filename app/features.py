from collections import defaultdict, deque
from typing import Deque, Dict, List

import numpy as np


class RollingWindow:
    def __init__(self, size: int = 120) -> None:
        self.size = size
        self.buf: Deque[float] = deque(maxlen=size)

    def add(self, value: float) -> None:
        self.buf.append(value)

    def as_array(self) -> np.ndarray:
        if not self.buf:
            return np.zeros((self.size,), dtype=float)
        arr = np.array(self.buf, dtype=float)
        if arr.shape[0] < self.size:
            pad = np.full((self.size - arr.shape[0],), arr[-1])
            arr = np.concatenate([pad, arr])
        return arr


class FeatureStore:
    def __init__(self, window: int = 120) -> None:
        self.window = window
        self.buffers: Dict[str, Dict[str, RollingWindow]] = defaultdict(lambda: defaultdict(lambda: RollingWindow(window)))

    def push(self, rack: str, metric: str, value: float) -> None:
        self.buffers[rack][metric].add(value)

    def get_window(self, rack: str, metric: str) -> np.ndarray:
        return self.buffers[rack][metric].as_array()

    def snapshot(self, rack: str) -> Dict[str, List[float]]:
        return {metric: buf.as_array().tolist() for metric, buf in self.buffers[rack].items()}
