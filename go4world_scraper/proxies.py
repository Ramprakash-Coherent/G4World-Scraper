"""Proxy helpers for go4worldbusiness scraping."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import go4world_config as config


def _normalize_proxy(line: str) -> str:
    line = line.strip()
    if not line or line.startswith("#"):
        return ""
    if "://" not in line:
        return f"http://{line}"
    return line


def load_proxy_list() -> list[str]:
    if os.environ.get("G4W_NO_PROXY", "1").lower() in ("1", "true", "yes"):
        return []

    proxies: list[str] = []
    env_urls = os.environ.get("G4W_PROXY_URLS", "")
    if env_urls:
        proxies.extend(_normalize_proxy(url) for url in env_urls.split(",") if _normalize_proxy(url))

    single = os.environ.get("G4W_PROXY_URL") or config.PROXY_URL
    if single:
        normalized = _normalize_proxy(single)
        if normalized and normalized not in proxies:
            proxies.append(normalized)

    if proxies:
        return proxies

    if os.environ.get("G4W_USE_PROXY_LIST", "").lower() not in ("1", "true", "yes"):
        return []

    list_file = os.environ.get("G4W_PROXY_LIST_FILE")
    paths: list[Path] = []
    if list_file:
        paths.append(Path(list_file))
    for candidate in (
        config.PROXY_LIST_FILE,
        config.BASE_DIR / "proxyscrape_premium_http_proxies_aviral.txt",
        config.BASE_DIR / "proxyscrape_premium_http_proxies.txt",
    ):
        if candidate not in paths:
            paths.append(candidate)

    for path in paths:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                normalized = _normalize_proxy(line)
                if normalized:
                    proxies.append(normalized)
            if proxies:
                break
    return proxies


def pick_proxy(index: int = 0) -> str | None:
    proxies = load_proxy_list()
    if not proxies:
        return None
    return proxies[index % len(proxies)]


def playwright_proxy_dict(proxy_url: str | None) -> dict[str, str] | None:
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    if not parsed.hostname:
        return None
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    payload: dict[str, str] = {"server": server}
    if parsed.username:
        payload["username"] = parsed.username
    if parsed.password:
        payload["password"] = parsed.password
    return payload


def httpx_proxy_url(proxy_url: str | None) -> str | None:
    return proxy_url
