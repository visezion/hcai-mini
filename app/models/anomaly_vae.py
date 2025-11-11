import numpy as np


class VAEAnomaly:
    def __init__(self, threshold: float = 0.97) -> None:
        self.threshold = threshold

    def score(self, window_vec: np.ndarray) -> tuple[float, bool]:
        if window_vec.size == 0:
            return 0.0, False
        err = float((window_vec[-1] - window_vec.mean()) ** 2)
        score = 1.0 / (1.0 + err)
        return score, score >= self.threshold
