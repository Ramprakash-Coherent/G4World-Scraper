"""Translate non-English (incl. Spanish) go4WorldBusiness fields to English."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Non-ASCII or common Spanish markers
_NON_LATIN_RE = re.compile(r"[^\x00-\x7F]")
_SPANISH_HINT_RE = re.compile(
    r"\b(el|la|los|las|de|del|para|con|empresa|proveedor|comprador|fabricante|"
    r"distribuidor|exportador|importador|productos|servicios)\b",
    re.I,
)


def needs_translation(value: str | None) -> bool:
    if not value:
        return False
    if _NON_LATIN_RE.search(value):
        return True
    # Heuristic for Spanish Latin text
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", value)
    if len(tokens) < 4:
        return False
    hits = len(_SPANISH_HINT_RE.findall(value))
    return hits >= 3 and hits / max(len(tokens), 1) > 0.15


class Go4WorldTranslator:
    def __init__(
        self,
        *,
        cache_file: Path,
        source: str = "auto",
        target: str = "en",
        enabled: bool = True,
    ) -> None:
        self.cache_file = cache_file
        self.source = source
        self.target = target
        self.enabled = enabled
        self._cache: dict[str, str] = {}
        self._dirty = False
        self._translator = None

    def load(self) -> None:
        if self.cache_file.exists():
            self._cache = json.loads(self.cache_file.read_text(encoding="utf-8"))

    def save(self) -> None:
        if not self._dirty:
            return
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")
        self._dirty = False

    def _get_translator(self):
        if self._translator is None:
            from deep_translator import GoogleTranslator

            self._translator = GoogleTranslator(source=self.source, target=self.target)
        return self._translator

    def translate_text(self, text: str | None) -> str | None:
        if not text or not self.enabled or not needs_translation(text):
            return text
        # Cap very long sections
        payload = text[:4500]
        cached = self._cache.get(payload)
        if cached is not None:
            return cached
        try:
            translated = self._get_translator().translate(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Translation failed: %s", exc)
            return text
        self._cache[payload] = translated
        self._dirty = True
        return translated

    def enrich_record(self, record: dict) -> dict:
        if not self.enabled:
            return record
        name = record.get("company_name")
        if name and needs_translation(name):
            record["company_name_en"] = self.translate_text(name)
        elif name and not record.get("company_name_en"):
            record["company_name_en"] = name

        for field, en_field in (
            ("description", "description_en"),
            ("about_text", "about_text_en"),
        ):
            value = record.get(field)
            if not value:
                continue
            translated = self.translate_text(value)
            if en_field:
                record[en_field] = translated

        for field in (
            "products_capabilities",
            "product_details",
            "deal_focus",
            "management_info",
            "facilities_info",
            "primary_business",
        ):
            value = record.get(field)
            if value and needs_translation(value):
                translated = self.translate_text(value)
                if translated and translated != value:
                    record[field] = translated
        return record
