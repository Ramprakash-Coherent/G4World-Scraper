#!/usr/bin/env python3
"""Convert the 4 catalog CSVs into G4World Entity/Listing worker folders."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

WORKERS: tuple[tuple[str, str, str, str], ...] = (
    # worker_id, source_csv, entity_col, listing_col
    ("rm", "subgroups_absolute_final.csv", "business_cluster", "subgroup"),
    ("fg", "nutraceutical_finished_goods_deduped_v1.csv", "business_cluster", "search_term"),
    ("pk", "packaging_deduped_v1.csv", "business_cluster", "search_term"),
    ("mc", "machinery_deduped_v1.csv", "business_cluster", "search_term"),
)


def prepare_worker(
    worker_id: str,
    source_name: str,
    entity_col: str,
    listing_col: str,
    *,
    root: Path = ROOT,
) -> int:
    source = root / source_name
    if not source.exists():
        raise FileNotFoundError(f"Missing catalog CSV: {source}")

    frame = pd.read_csv(source)
    if entity_col not in frame.columns or listing_col not in frame.columns:
        raise ValueError(
            f"{source.name} must contain columns {entity_col!r} and {listing_col!r}; "
            f"found {list(frame.columns)}"
        )

    out_dir = root / f"listings_{worker_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(
        {
            "Entity": frame[entity_col].astype(str).str.strip(),
            "Listing": frame[listing_col].astype(str).str.strip(),
        }
    )
    out = out[(out["Entity"] != "") & (out["Listing"] != "")]
    out = out[out["Entity"].str.lower() != "nan"]
    out = out[out["Listing"].str.lower() != "nan"]
    out_path = out_dir / "terms.csv"
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"{worker_id.upper():>2}  {len(out):5d} terms  ->  {out_path.relative_to(root)}")
    return len(out)


def main() -> int:
    total = 0
    try:
        for worker_id, source_name, entity_col, listing_col in WORKERS:
            total += prepare_worker(worker_id, source_name, entity_col, listing_col)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Prepared {total} total listing terms across {len(WORKERS)} workers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
