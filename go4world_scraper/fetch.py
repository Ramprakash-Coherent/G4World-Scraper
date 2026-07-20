"""Fetch go4worldbusiness HTML with cache, polite delays, and Playwright WAF bypass."""

from __future__ import annotations

import hashlib
import logging
import random
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx

import go4world_config as config
from go4world_scraper.proxies import httpx_proxy_url, pick_proxy, playwright_proxy_dict

logger = logging.getLogger(__name__)


def cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{digest}.html"


def is_waf_challenge(html: str) -> bool:
    lower = html.lower()
    # Real interstitial pages are short and lack app content.
    if "javascript is disabled" in lower and "not a robot" in lower:
        return True
    if "just a moment" in lower and "cloudflare" in lower:
        return True
    if "cf-turnstile" in lower and len(html) < 20000:
        return True
    if "verifying you are human" in lower or "performing security verification" in lower:
        return True
    # AWS WAF challenge.js is embedded on normal pages too — only treat as block
    # when the document is tiny / empty of marketplace markup.
    if "awswaf" in lower and len(html) < 8000 and "entity-row-title" not in lower and "business profile" not in lower:
        return True
    return False


def is_g4w_page_ready(html: str, *, url: str | None = None) -> bool:
    if not html or len(html) < 4000:
        return False
    if is_waf_challenge(html):
        return False
    lower = html.lower()
    if url and "/find" in url:
        return (
            "entity-row-title" in lower
            or "search-results" in lower
            or "no results" in lower
            or "buyersorsuppliers" in lower
            or "wanted :" in lower
        )
    markers = (
        "business profile",
        "member/view",
        "pn-contact",
        "mn-business-summary",
        "verification status",
        "about the supplier",
        "about the buyer",
        "pref_product/view",
        "buylead/view",
    )
    return any(marker in lower for marker in markers)


def sleep_polite(min_delay: float, max_delay: float) -> None:
    time.sleep(random.uniform(min_delay, max_delay))


class G4WFetchError(RuntimeError):
    pass


class G4WHTTPClient:
    def __init__(
        self,
        *,
        cache_dir: Path,
        timeout: float,
        min_delay: float,
        max_delay: float,
        user_agent: str,
        use_playwright: bool = True,
        headless: bool = True,
        playwright_timeout_ms: int = config.PLAYWRIGHT_TIMEOUT_MS,
        challenge_wait_ms: int = config.CHALLENGE_WAIT_MS,
        browser_profile_dir: Path = config.BROWSER_PROFILE_DIR,
        proxy_url: str | None = None,
        proxy_index: int = 0,
        use_proxy_pool: bool = True,
        playwright_first: bool | None = None,
        cdp_url: str | None = None,
        use_cache: bool = True,
    ) -> None:
        self.cache_dir = cache_dir
        self.use_cache_default = use_cache and not bool(cdp_url)
        self.timeout = timeout
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.user_agent = user_agent
        self.use_playwright = use_playwright
        self.headless = headless
        self.playwright_timeout_ms = playwright_timeout_ms
        self.challenge_wait_ms = challenge_wait_ms
        self.browser_profile_dir = browser_profile_dir
        self.cdp_url = cdp_url
        self._cdp_connected = False
        self.proxy_url = (
            proxy_url if proxy_url is not None else (pick_proxy(proxy_index) if use_proxy_pool else None)
        )
        self.playwright_first = (
            playwright_first
            if playwright_first is not None
            else (bool(cdp_url) or not headless or config.PLAYWRIGHT_FIRST)
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def close(self) -> None:
        try:
            if self._cdp_connected:
                if self._playwright:
                    self._playwright.stop()
            else:
                if self._context:
                    self._context.close()
                if self._browser:
                    self._browser.close()
                if self._playwright:
                    self._playwright.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Browser cleanup: %s", exc)
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
            self._cdp_connected = False

    def fetch(
        self,
        url: str,
        *,
        use_cache: bool | None = None,
        force: bool = False,
        save_raw: Path | None = None,
    ) -> str:
        use_cache = self.use_cache_default if use_cache is None else use_cache
        path = cache_path(self.cache_dir, url)
        if use_cache and path.exists() and not force:
            cached = path.read_text(encoding="utf-8", errors="replace")
            if is_g4w_page_ready(cached, url=url):
                return cached

        sleep_polite(self.min_delay, self.max_delay)
        html: str | None = None

        if self.use_playwright and self.playwright_first:
            html = self._fetch_with_playwright(url)
        else:
            html = self._fetch_live(url)
            if (is_waf_challenge(html) or not is_g4w_page_ready(html, url=url)) and self.use_playwright:
                logger.info("Challenge / empty page for %s — retrying with Playwright", url)
                html = self._fetch_with_playwright(url)

        if not is_g4w_page_ready(html, url=url):
            raise G4WFetchError(
                f"Blocked or empty response for {url}. "
                "Start Chrome with remote debugging and use --cdp after verification, "
                "or run with --headed, or set G4W_PROXY_URL to a residential proxy."
            )

        path.write_text(html, encoding="utf-8")
        if save_raw:
            save_raw.parent.mkdir(parents=True, exist_ok=True)
            save_raw.write_text(html, encoding="utf-8")
        return html

    def _fetch_live(self, url: str) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
            "Referer": config.BASE_URL + "/",
        }
        proxy = httpx_proxy_url(self.proxy_url)
        with httpx.Client(timeout=self.timeout, follow_redirects=True, proxy=proxy) as client:
            response = client.get(url, headers=headers)
            return response.text or ""

    def _ensure_browser(self):
        if self._page is not None:
            return self._page

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise G4WFetchError(
                "Playwright required for WAF bypass. "
                "pip install playwright && python -m playwright install chromium"
            ) from exc

        self._playwright = sync_playwright().start()
        if self.cdp_url:
            return self._connect_cdp_browser()

        proxy = playwright_proxy_dict(self.proxy_url)
        launch_kwargs: dict = {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        }
        try:
            self._browser = self._playwright.chromium.launch(channel="chrome", **launch_kwargs)
            logger.info("Using installed Google Chrome for Playwright")
        except Exception:
            self._browser = self._playwright.chromium.launch(**launch_kwargs)
            logger.info("Using Playwright Chromium")

        self._context = self._browser.new_context(
            user_agent=self.user_agent,
            locale="en-US",
            viewport={"width": 1366, "height": 900},
            proxy=proxy,
            storage_state=self._storage_state_path() if self._storage_state_path().exists() else None,
        )
        self._page = self._context.new_page()
        # Warm homepage once to collect cookies / pass soft challenges.
        try:
            self._page.goto(config.BASE_URL + "/", wait_until="domcontentloaded", timeout=self.playwright_timeout_ms)
            self._page.wait_for_timeout(3000)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Homepage warm-up: %s", exc)
        return self._page

    def _connect_cdp_browser(self):
        assert self.cdp_url
        logger.info("Attaching to Chrome via CDP: %s", self.cdp_url)
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(self.cdp_url)
        except Exception as exc:  # noqa: BLE001
            raise G4WFetchError(
                f"Could not connect to Chrome at {self.cdp_url}. "
                "Close all Chrome windows, then start Chrome with:\n"
                '  chrome.exe --remote-debugging-port=9222 '
                f'--user-data-dir="{self.browser_profile_dir / "chrome_cdp"}"\n'
                "Open https://www.go4worldbusiness.com and complete verification, then re-run with --cdp."
            ) from exc

        self._cdp_connected = True
        if not self._browser.contexts:
            raise G4WFetchError("Connected to Chrome but no browser context found.")
        self._context = self._browser.contexts[0]
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        logger.info("CDP attached (%s existing tab(s)).", len(self._context.pages))
        return self._page

    def _storage_state_path(self) -> Path:
        return self.browser_profile_dir / "storage_state.json"

    def _persist_session(self) -> None:
        if self._cdp_connected or not self._context:
            return
        try:
            self._context.storage_state(path=str(self._storage_state_path()))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not persist browser session: %s", exc)

    def _safe_page_content(self, page, *, attempts: int = 8) -> str:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            try:
                return page.content()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                page.wait_for_timeout(1500)
                if attempt == 2:
                    logger.debug("Page still navigating, waiting... (%s)", exc)
        if last_error:
            raise last_error
        return page.content()

    def _wait_for_ready(self, page, url: str) -> str:
        if self.cdp_url:
            logger.info("CDP mode: if a challenge appears in Chrome, complete it manually.")
        elif not self.headless:
            logger.info("If a verification challenge appears, complete it once — cookies are saved.")

        max_wait_ms = self.challenge_wait_ms if (self.cdp_url or not self.headless) else min(
            self.challenge_wait_ms, 90000
        )
        poll_ms = 2000
        elapsed = 0
        html = self._safe_page_content(page)
        while elapsed < max_wait_ms:
            if is_g4w_page_ready(html, url=url):
                self._persist_session()
                return html
            page.wait_for_timeout(poll_ms)
            elapsed += poll_ms
            try:
                html = self._safe_page_content(page)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Content read retry while waiting: %s", exc)
                continue
            if elapsed % 10000 == 0:
                logger.info("Still waiting for %s (%ss)...", url, elapsed // 1000)
        return html

    def _fetch_with_playwright(self, url: str) -> str:
        page = self._ensure_browser()
        mode = "cdp" if self.cdp_url else "playwright"
        logger.info("%s fetch: %s (proxy=%s)", mode, url, bool(self.proxy_url))
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.playwright_timeout_ms)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Initial navigation issue for %s: %s", url, exc)
        html = self._wait_for_ready(page, url)
        if is_g4w_page_ready(html, url=url):
            return html
        try:
            page.reload(wait_until="domcontentloaded", timeout=self.playwright_timeout_ms)
            html = self._wait_for_ready(page, url)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Reload after challenge failed: %s", exc)
        return html


def absolute_url(base_url: str, href: str) -> str:
    return urljoin(base_url, href)
