from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row


DDL = """
CREATE TABLE IF NOT EXISTS context_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  retrieved_at TIMESTAMPTZ NOT NULL,
  issued_at TIMESTAMPTZ NULL,
  valid_at TIMESTAMPTZ NULL,
  stale_after TIMESTAMPTZ NOT NULL,
  bbox JSONB NOT NULL,
  layers JSONB NOT NULL,
  payload_hash TEXT NOT NULL UNIQUE,
  worker_status TEXT NOT NULL
);
ALTER TABLE context_snapshots ADD COLUMN IF NOT EXISTS domain_id TEXT NULL;
ALTER TABLE context_snapshots ADD COLUMN IF NOT EXISTS geometry_hash TEXT NULL;
CREATE INDEX IF NOT EXISTS context_snapshots_retrieved_at_idx ON context_snapshots (retrieved_at DESC);
CREATE TABLE IF NOT EXISTS sensor_observations (
  observation_id TEXT PRIMARY KEY,
  station_serial TEXT NOT NULL,
  metric TEXT NOT NULL,
  value DOUBLE PRECISION NOT NULL,
  unit TEXT NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL,
  source_type TEXT NOT NULL,
  qc_status TEXT NOT NULL,
  qc_reason TEXT NULL,
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (station_serial, metric, observed_at, source_type)
);
CREATE INDEX IF NOT EXISTS sensor_observations_station_time_idx
  ON sensor_observations (station_serial, observed_at DESC);
"""


class SnapshotRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def initialize(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(DDL)

    def insert_immutable(self, snapshot: dict[str, Any]) -> bool:
        query = """
        INSERT INTO context_snapshots
          (snapshot_id, retrieved_at, issued_at, valid_at, stale_after, bbox, layers, payload_hash, worker_status, domain_id, geometry_hash)
        VALUES
          (%(snapshot_id)s, %(retrieved_at)s, %(issued_at)s, %(valid_at)s, %(stale_after)s,
           %(bbox)s::jsonb, %(layers)s::jsonb, %(payload_hash)s, %(worker_status)s, %(domain_id)s, %(geometry_hash)s)
        ON CONFLICT (payload_hash) DO NOTHING
        """
        values = {**snapshot, "bbox": json.dumps(snapshot["bbox"]), "layers": json.dumps(snapshot["layers"])}
        with psycopg.connect(self.database_url) as connection:
            return connection.execute(query, values).rowcount == 1

    def latest(self) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            return connection.execute("SELECT * FROM context_snapshots ORDER BY retrieved_at DESC LIMIT 1").fetchone()

    def by_id(self, snapshot_id: str) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            return connection.execute("SELECT * FROM context_snapshots WHERE snapshot_id = %s", (snapshot_id,)).fetchone()

    def by_payload_hash(self, payload_hash: str) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            return connection.execute("SELECT * FROM context_snapshots WHERE payload_hash = %s", (payload_hash,)).fetchone()

    def insert_sensor_observations(self, observations: list[dict[str, Any]]) -> int:
        if not observations:
            return 0
        query = """
        INSERT INTO sensor_observations
          (observation_id, station_serial, metric, value, unit, observed_at,
           ingested_at, source_type, qc_status, qc_reason, provenance)
        VALUES
          (%(observation_id)s, %(station_serial)s, %(metric)s, %(value)s,
           %(unit)s, %(observed_at)s, %(ingested_at)s, %(source_type)s,
           %(qc_status)s, %(qc_reason)s, %(provenance)s::jsonb)
        ON CONFLICT DO NOTHING
        """
        inserted = 0
        with psycopg.connect(self.database_url) as connection:
            for observation in observations:
                values = {**observation, "provenance": json.dumps(observation.get("provenance", {}))}
                inserted += int(connection.execute(query, values).rowcount == 1)
        return inserted

    def latest_observed_at(self, station_serial: str) -> datetime | None:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute("SELECT max(observed_at) FROM sensor_observations WHERE station_serial = %s", (station_serial,)).fetchone()
        return row[0] if row else None

    def latest_sensor(self, station_serial: str, limit: int = 100) -> list[dict[str, Any]]:
        query = """
        SELECT DISTINCT ON (metric) observation_id, station_serial, metric, value, unit,
               observed_at, ingested_at, source_type, qc_status, qc_reason,
               provenance
        FROM sensor_observations
        WHERE station_serial = %s
        ORDER BY metric, observed_at DESC
        LIMIT %s
        """
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(query, (station_serial, int(limit))).fetchall()
        return list(rows)

    def status_summary(self, station_serial: str, connect_timeout: int = 3) -> dict[str, Any]:
        """Latest snapshot header + newest sensor time for the light status endpoint (no layer payloads)."""
        with psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=connect_timeout) as connection:
            snapshot = connection.execute(
                "SELECT snapshot_id, retrieved_at, stale_after FROM context_snapshots ORDER BY retrieved_at DESC LIMIT 1").fetchone()
            sensor = connection.execute(
                "SELECT max(observed_at) AS latest_observed_at FROM sensor_observations WHERE station_serial = %s",
                (station_serial,)).fetchone()
        return {"snapshot": snapshot, "latest_observed_at": (sensor or {}).get("latest_observed_at")}


def snapshot_status(snapshot: dict[str, Any] | None, now: datetime | None = None) -> str:
    if snapshot is None:
        return "unavailable"
    now = now or datetime.now(timezone.utc)
    stale_after = snapshot["stale_after"]
    if stale_after.tzinfo is None:
        stale_after = stale_after.replace(tzinfo=timezone.utc)
    return "fresh" if now <= stale_after else "stale"
