"""ISOLATED demographics store (specs/04 §6, HR-6, FR-HMD-3).

Import contract enforced by T-ISO-1: nothing under app/agent, app/agents,
app/policy_engine, app/aus, app/domain, or app/audit may import this
module or read its table. Writers: the intake API (strips the package's
hmda_demographics block). Readers: the monitoring extract only
(GET /hmda/monitoring-extract, FR-HMD-4).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS hmda_demographics (
  application_id TEXT NOT NULL,
  borrower_id TEXT NOT NULL,
  ethnicity TEXT, race TEXT, sex TEXT, age_band TEXT,
  collection_method TEXT NOT NULL DEFAULT 'applicant_provided',
  PRIMARY KEY (application_id, borrower_id)
);
"""


class DemographicsStore:
    def __init__(self, db_path: Path | str):
        self._path = str(db_path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as conn:
            conn.executescript(_DDL)
            conn.commit()

    def store(self, application_id: str, demographics: dict[str, dict]) -> None:
        with closing(sqlite3.connect(self._path)) as conn:
            for borrower_id, entry in demographics.items():
                conn.execute(
                    "INSERT OR REPLACE INTO hmda_demographics"
                    " (application_id, borrower_id, ethnicity, race, sex, age_band)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (application_id, borrower_id, entry.get("ethnicity"),
                     entry.get("race"), entry.get("sex"), entry.get("age_band")))
            conn.commit()

    def monitoring_extract(self) -> list[dict]:
        """Fair-lending monitoring ONLY (X-Purpose header set by the API)."""
        with closing(sqlite3.connect(self._path)) as conn:
            rows = conn.execute(
                "SELECT application_id, borrower_id, ethnicity, race, sex,"
                " age_band FROM hmda_demographics ORDER BY application_id",
            ).fetchall()
        return [
            {"application_id": r[0], "borrower_id": r[1], "ethnicity": r[2],
             "race": r[3], "sex": r[4], "age_band": r[5]}
            for r in rows
        ]


def strip_demographics(package: dict) -> dict[str, dict]:
    """Remove the demographics block from a package at intake; the pipeline
    never sees it (HR-6). Returns what was stripped."""
    return package.pop("hmda_demographics", {}) or {}


__all__ = ["DemographicsStore", "strip_demographics"]
