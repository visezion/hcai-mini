from datetime import datetime, timezone
from typing import Dict

from .db import DB


def record_audit(db: DB, actor: str, action: str, payload: Dict) -> None:
    db.insert(
        "audits",
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "action": action,
            "payload": str(payload),
        },
    )
