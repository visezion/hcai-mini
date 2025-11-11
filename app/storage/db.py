import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  site TEXT NOT NULL,
  rack TEXT,
  temp_c REAL,
  hum_pct REAL,
  power_kw REAL,
  airflow_cfm REAL,
  raw_json TEXT
);
CREATE TABLE IF NOT EXISTS forecasts (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  horizon_s INTEGER NOT NULL,
  rack TEXT,
  temp_pred REAL,
  temp_lo REAL,
  temp_hi REAL,
  power_pred REAL
);
CREATE TABLE IF NOT EXISTS anomalies (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  rack TEXT,
  score REAL,
  threshold REAL,
  is_alarm INTEGER
);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  device_id TEXT NOT NULL,
  cmd_json TEXT NOT NULL,
  mode TEXT NOT NULL,
  status TEXT DEFAULT 'queued',
  reason TEXT,
  model_version TEXT,
  safety_summary TEXT
);
CREATE TABLE IF NOT EXISTS receipts (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  device_id TEXT NOT NULL,
  status TEXT NOT NULL,
  applied_json TEXT,
  latency_ms INTEGER,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS audits (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  payload TEXT
);
"""


class DB:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        with self.lock, self.conn:
            self.conn.executescript(SCHEMA)

    def insert(self, table: str, payload: Dict[str, Any]) -> None:
        cols = ",".join(payload.keys())
        placeholders = ":" + ",:".join(payload.keys())
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        with self.lock, self.conn:
            self.conn.execute(sql, payload)

    def latest(self, table: str, limit: int = 50) -> list[Dict[str, Any]]:
        with self.lock:
            cur = self.conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def get(self, table: str, row_id: int) -> Dict[str, Any] | None:
        with self.lock:
            cur = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def update_action_status(self, action_id: int, status: str) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE actions SET status = :status WHERE id = :id",
                {"status": status, "id": action_id},
            )

    def update_action_cmd(self, action_id: int, new_cmd: Dict[str, Any]) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE actions SET cmd_json = :cmd WHERE id = :id",
                {"cmd": json.dumps(new_cmd), "id": action_id},
            )

    def telemetry_history(self, rack: str, limit: int = 120) -> list[Dict[str, Any]]:
        with self.lock:
            cur = self.conn.execute(
                "SELECT ts, temp_c, hum_pct, power_kw, airflow_cfm FROM telemetry WHERE rack = ? ORDER BY ts DESC LIMIT ?",
                (rack, limit),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def latest_point(self, rack: str) -> Dict[str, Any] | None:
        with self.lock:
            cur = self.conn.execute(
                "SELECT ts, temp_c, hum_pct, power_kw, airflow_cfm FROM telemetry WHERE rack = ? ORDER BY ts DESC LIMIT 1",
                (rack,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def record_action(self, action: Dict[str, Any]) -> int:
        payload = action.copy()
        if isinstance(payload.get("cmd_json"), dict):
            payload["cmd_json"] = json.dumps(payload["cmd_json"])
        if isinstance(payload.get("safety_summary"), dict):
            payload["safety_summary"] = json.dumps(payload["safety_summary"])
        with self.lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO actions (ts, device_id, cmd_json, mode, status, reason, model_version, safety_summary) "
                "VALUES (:ts, :device_id, :cmd_json, :mode, :status, :reason, :model_version, :safety_summary)",
                payload,
            )
            return cur.lastrowid

    def record_receipt(self, receipt: Dict[str, Any]) -> None:
        payload = receipt.copy()
        if isinstance(payload.get("applied_json"), dict):
            payload["applied_json"] = json.dumps(payload["applied_json"])
        self.insert("receipts", payload)
