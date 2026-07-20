"""Persistence helpers for CSV output, schema, and checkpointing."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


def ensure_directories(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def list_raw_json_files(raw_dir: Path, entity: str) -> list[Path]:
    """Return sorted legacy raw JSON files for an entity."""
    if not raw_dir.exists():
        return []
    prefix = f"{slugify(entity)}_"
    return sorted(path for path in raw_dir.glob(f"{prefix}*_page_*.json") if path.is_file())


def slugify(value: str) -> str:
    import re

    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "unknown"


def load_csv_records(path: Path) -> list[dict[str, Any]]:
    """Load records from the single output CSV."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, Any]] = []
        for row in reader:
            cleaned = {
                key: (None if value in (None, "", "NULL") else value)
                for key, value in row.items()
            }
            rows.append(cleaned)
        return rows


def load_progress(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_progress(path: Path, progress: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(progress, handle, ensure_ascii=False, indent=2)


def write_csv(records: list[dict[str, Any]], output_file: Path, columns: list[str]) -> None:
    """Write deduplicated records to the single output CSV."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(records, columns=columns)
    frame.to_csv(output_file, index=False, na_rep="NULL")


def save_output_schema(path: Path, *, source_entity: str, columns: list[str]) -> None:
    """Write/update scrape metadata JSON alongside the schema definition."""
    payload: dict[str, Any]
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = {"description": "IndiaMART search API output column schema", "columns": []}

    payload["source_entity"] = source_entity
    payload["last_scrape_date"] = datetime.now().date().isoformat()
    payload["column_names"] = columns
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
