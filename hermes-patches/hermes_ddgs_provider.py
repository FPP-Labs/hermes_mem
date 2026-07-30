"""Reliable keyless web search for Hermes Mem.

The upstream ``ddgs`` package uses ``primp`` with its own DNS resolver by
default. That resolver can stop resolving every hostname after a macOS
sleep/network transition while the operating system resolver continues to
work. Hermes Mem forces ``primp`` to use the system resolver and retains a
plain-httpx DuckDuckGo HTML fallback so one client implementation cannot take
web search down.
"""

from __future__ import annotations

import concurrent.futures as _cf
from html.parser import HTMLParser
import logging
import re
import threading
from typing import Any, Callable, Dict
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from agent.web_search_provider import WebSearchProvider


logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT_SECS = 30
_FALLBACK_TIMEOUT_SECS = 15
_DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
_DNS_PATCH_LOCK = threading.Lock()
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _normalize_result_url(value: str) -> str:
    """Return a direct HTTP(S) result URL and unwrap DDG redirect links."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    absolute = urljoin(_DUCKDUCKGO_HTML_URL, raw)
    try:
        parsed = urlparse(absolute)
    except ValueError:
        return ""
    if parsed.hostname and parsed.hostname.lower().endswith("duckduckgo.com"):
        redirected = (parse_qs(parsed.query).get("uddg") or [""])[0]
        if redirected:
            absolute = unquote(redirected)
            try:
                parsed = urlparse(absolute)
            except ValueError:
                return ""
    return absolute if parsed.scheme in {"http", "https"} and parsed.netloc else ""


class _DuckDuckGoHTMLParser(HTMLParser):
    """Extract titles, URLs, and snippets from DuckDuckGo's HTML endpoint."""

    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.results: list[dict[str, Any]] = []
        self._mode = ""
        self._href = ""
        self._parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "a" or self._mode:
            return
        attributes = {name: value or "" for name, value in attrs}
        classes = set(attributes.get("class", "").split())
        if "result__a" in classes:
            self._mode = "title"
        elif "result__snippet" in classes:
            self._mode = "snippet"
        else:
            return
        self._href = _normalize_result_url(attributes.get("href", ""))
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._mode:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._mode:
            return
        text = _clean_text("".join(self._parts))
        if self._mode == "title":
            if self._href and text and len(self.results) < self.limit:
                self.results.append(
                    {
                        "title": text,
                        "url": self._href,
                        "description": "",
                        "position": len(self.results) + 1,
                    }
                )
        elif text:
            for result in reversed(self.results):
                if not result["description"] and (
                    not self._href or result["url"] == self._href
                ):
                    result["description"] = text
                    break
        self._mode = ""
        self._href = ""
        self._parts = []


def _force_system_dns_for_ddgs() -> None:
    """Make all DDGS HTTP clients use the operating system DNS resolver."""
    from ddgs.http_client import HttpClient  # type: ignore

    if getattr(HttpClient.__init__, "_hermes_mem_system_dns", False):
        return
    with _DNS_PATCH_LOCK:
        if getattr(HttpClient.__init__, "_hermes_mem_system_dns", False):
            return
        import primp  # type: ignore

        def system_dns_init(
            self: Any,
            proxy: str | None = None,
            timeout: int | None = 10,
            *,
            verify: bool | str = True,
        ) -> None:
            self.client = primp.Client(
                proxy=proxy,
                timeout=timeout,
                impersonate="random",
                impersonate_os="random",
                verify=verify if isinstance(verify, bool) else True,
                ca_cert_file=verify if isinstance(verify, str) else None,
                dns_resolver="system",
            )

        setattr(system_dns_init, "_hermes_mem_system_dns", True)
        HttpClient.__init__ = system_dns_init


def _run_ddgs_search(query: str, safe_limit: int) -> list[dict[str, Any]]:
    """Search through DDGS after replacing its unreliable private resolver."""
    _force_system_dns_for_ddgs()
    from ddgs import DDGS  # type: ignore

    results: list[dict[str, Any]] = []
    with DDGS(timeout=10) as client:
        for hit in client.text(query, max_results=safe_limit):
            url = _normalize_result_url(str(hit.get("href") or hit.get("url") or ""))
            title = _clean_text(str(hit.get("title", "")))
            if not url or not title or any(item["url"] == url for item in results):
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "description": _clean_text(str(hit.get("body", ""))),
                    "position": len(results) + 1,
                }
            )
            if len(results) >= safe_limit:
                break
    return results


def _run_html_fallback(query: str, safe_limit: int) -> list[dict[str, Any]]:
    """Search DuckDuckGo HTML with httpx and the normal system resolver."""
    import httpx

    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
    }
    with httpx.Client(
        follow_redirects=True,
        headers=headers,
        timeout=_FALLBACK_TIMEOUT_SECS,
    ) as client:
        response = client.post(_DUCKDUCKGO_HTML_URL, data={"q": query})
        response.raise_for_status()
    parser = _DuckDuckGoHTMLParser(safe_limit)
    parser.feed(response.text)
    if not parser.results:
        raise RuntimeError("DuckDuckGo HTML returned no searchable results")
    return parser.results


def _run_bounded(
    operation: Callable[[], list[dict[str, Any]]],
    timeout: int,
) -> list[dict[str, Any]]:
    """Run blocking network work without allowing a hung client to block Hermes."""
    pool = _cf.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(operation).result(timeout=timeout)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


class DDGSWebSearchProvider(WebSearchProvider):
    """Keyless DDGS search with system-DNS repair and an httpx fallback."""

    @property
    def name(self) -> str:
        return "ddgs"

    @property
    def display_name(self) -> str:
        return "DuckDuckGo (ddgs)"

    def is_available(self) -> bool:
        try:
            import ddgs  # noqa: F401

            return True
        except ImportError:
            return False

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        try:
            import ddgs  # noqa: F401
        except ImportError:
            return {
                "success": False,
                "error": "ddgs package is not installed — run `pip install ddgs`",
            }

        safe_limit = max(1, int(limit))
        primary_error = ""
        try:
            results = _run_bounded(
                lambda: _run_ddgs_search(query, safe_limit),
                _SEARCH_TIMEOUT_SECS,
            )
            if results:
                logger.info(
                    "DDGS system-DNS search %r: %d results",
                    query,
                    len(results),
                )
                return {"success": True, "data": {"web": results}}
            primary_error = "DDGS returned no results"
        except _cf.TimeoutError:
            primary_error = f"DDGS timed out after {_SEARCH_TIMEOUT_SECS}s"
        except Exception as exc:  # noqa: BLE001
            primary_error = f"{type(exc).__name__}: {exc}"

        logger.warning(
            "DDGS primary search failed (%s); using system-http fallback",
            primary_error,
        )
        try:
            results = _run_bounded(
                lambda: _run_html_fallback(query, safe_limit),
                _FALLBACK_TIMEOUT_SECS + 2,
            )
            logger.info(
                "DuckDuckGo HTML fallback %r: %d results",
                query,
                len(results),
            )
            return {"success": True, "data": {"web": results}}
        except Exception as exc:  # noqa: BLE001
            fallback_error = f"{type(exc).__name__}: {exc}"
            logger.warning("DuckDuckGo HTML fallback failed: %s", fallback_error)
            return {
                "success": False,
                "error": (
                    "DuckDuckGo search failed through both system-DNS paths. "
                    f"DDGS: {primary_error}. HTML fallback: {fallback_error}"
                ),
            }

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "DuckDuckGo (ddgs)",
            "badge": "free · no key · search only",
            "tag": (
                "Search via DDGS with a system-DNS and DuckDuckGo HTML fallback"
            ),
            "env_vars": [],
            "post_setup": "ddgs",
        }
