"""Load entity/listing tasks from Excel or CSV files."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class ListingTask:
    entity: str
    listing: str
    search_query: str | None = None

    @property
    def query(self) -> str:
        """Search slug or category URL (New Listing when set, else Listing)."""
        return (self.search_query or self.listing).strip()


def _append_task(
    tasks: list[ListingTask],
    seen: set[tuple[str, str]],
    *,
    entity: str,
    listing: str,
    search_query: str | None,
) -> None:
    entity = entity.strip()
    listing = listing.strip()
    if not entity or not listing or entity.lower() == "nan" or listing.lower() == "nan":
        return
    dedupe_key = (entity, search_query or listing)
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)
    tasks.append(ListingTask(entity=entity, listing=listing, search_query=search_query))


def _load_xlsx(path: Path, tasks: list[ListingTask], seen: set[tuple[str, str]]) -> None:
    frame = pd.read_excel(path)
    columns = {col.strip().lower(): col for col in frame.columns}
    entity_col = columns.get("entity")
    listing_col = columns.get("listing")
    new_listing_col = columns.get("new listing")
    if not entity_col or not listing_col:
        raise ValueError(f"{path.name} must contain 'Entity' and 'Listing' columns")

    for _, row in frame.iterrows():
        search_query: str | None = None
        if new_listing_col:
            raw_new = str(row[new_listing_col]).strip()
            if raw_new and raw_new.lower() != "nan":
                search_query = raw_new
        _append_task(
            tasks,
            seen,
            entity=str(row[entity_col]),
            listing=str(row[listing_col]),
            search_query=search_query,
        )


def _load_csv(path: Path, tasks: list[ListingTask], seen: set[tuple[str, str]]) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return
        columns = {name.strip().lower(): name for name in reader.fieldnames}
        entity_col = columns.get("entity")
        listing_col = columns.get("listing")
        new_listing_col = columns.get("new listing")
        if not entity_col or not listing_col:
            raise ValueError(f"{path.name} must contain Entity and Listing columns")

        for row in reader:
            search_query: str | None = None
            if new_listing_col:
                raw_new = (row.get(new_listing_col) or "").strip()
                if raw_new:
                    search_query = raw_new
            _append_task(
                tasks,
                seen,
                entity=row.get(entity_col) or "",
                listing=row.get(listing_col) or "",
                search_query=search_query,
            )


def load_listings(listings_path: Path) -> list[ListingTask]:
    """Load tasks from a CSV/XLSX file or every CSV/XLSX in a directory."""
    if listings_path.is_file():
        paths = [listings_path]
    elif listings_path.is_dir():
        paths = sorted(
            path
            for path in listings_path.iterdir()
            if path.suffix.lower() in {".csv", ".xlsx"} and not path.name.startswith("~$")
        )
    else:
        raise FileNotFoundError(f"Listings path not found: {listings_path}")

    if not paths:
        raise FileNotFoundError(f"No .csv or .xlsx listings in {listings_path}")

    tasks: list[ListingTask] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        if path.suffix.lower() == ".xlsx":
            _load_xlsx(path, tasks, seen)
        else:
            _load_csv(path, tasks, seen)
    return tasks


def group_by_entity(tasks: list[ListingTask]) -> dict[str, list[ListingTask]]:
    grouped: dict[str, list[ListingTask]] = {}
    for task in tasks:
        grouped.setdefault(task.entity, []).append(task)
    return grouped
