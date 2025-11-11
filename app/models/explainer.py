from typing import Dict, List


class Explainer:
    def __init__(self) -> None:
        self.enabled = False

    def explain(self, features: Dict[str, List[float]]) -> Dict[str, float]:
        if not self.enabled:
            return {"note": "SHAP disabled in skeleton"}
        # placeholder for future SHAP integration
        return {}
