from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import uuid


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_SOURCE = ROOT / "hermes-patches/hermes_ddgs_provider.py"


def load_provider(monkeypatch):
    agent_package = types.ModuleType("agent")
    agent_package.__path__ = []
    web_search_provider = types.ModuleType("agent.web_search_provider")

    class WebSearchProvider:
        pass

    web_search_provider.WebSearchProvider = WebSearchProvider
    monkeypatch.setitem(sys.modules, "agent", agent_package)
    monkeypatch.setitem(
        sys.modules,
        "agent.web_search_provider",
        web_search_provider,
    )
    module_name = f"hermes_ddgs_provider_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, PROVIDER_SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_html_parser_extracts_direct_and_redirected_results(monkeypatch) -> None:
    module = load_provider(monkeypatch)
    parser = module._DuckDuckGoHTMLParser(3)
    parser.feed(
        """
        <a class="result__a" href="https://example.com/one">
          First <b>result</b>
        </a>
        <a class="result__snippet" href="https://example.com/one">
          First <b>description</b>
        </a>
        <a class="result__a"
           href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Ftwo">
          Second result
        </a>
        """
    )
    assert parser.results == [
        {
            "title": "First result",
            "url": "https://example.com/one",
            "description": "First description",
            "position": 1,
        },
        {
            "title": "Second result",
            "url": "https://example.org/two",
            "description": "",
            "position": 2,
        },
    ]


def test_ddgs_http_client_is_forced_to_system_dns(monkeypatch) -> None:
    module = load_provider(monkeypatch)
    captured: list[dict] = []

    class FakePrimpClient:
        def __init__(self, **kwargs) -> None:
            captured.append(kwargs)

    class FakeHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("unpatched DDGS initializer was called")

    ddgs_package = types.ModuleType("ddgs")
    ddgs_package.__path__ = []
    ddgs_http_client = types.ModuleType("ddgs.http_client")
    ddgs_http_client.HttpClient = FakeHttpClient
    primp = types.ModuleType("primp")
    primp.Client = FakePrimpClient
    monkeypatch.setitem(sys.modules, "ddgs", ddgs_package)
    monkeypatch.setitem(sys.modules, "ddgs.http_client", ddgs_http_client)
    monkeypatch.setitem(sys.modules, "primp", primp)

    module._force_system_dns_for_ddgs()
    FakeHttpClient(proxy="http://proxy.invalid", timeout=7, verify="/tmp/ca.pem")

    assert captured == [
        {
            "proxy": "http://proxy.invalid",
            "timeout": 7,
            "impersonate": "random",
            "impersonate_os": "random",
            "verify": True,
            "ca_cert_file": "/tmp/ca.pem",
            "dns_resolver": "system",
        }
    ]


def test_search_uses_http_fallback_when_ddgs_fails(monkeypatch) -> None:
    module = load_provider(monkeypatch)
    monkeypatch.setitem(sys.modules, "ddgs", types.ModuleType("ddgs"))

    def fail_primary(query: str, limit: int):
        raise RuntimeError("native resolver failed")

    fallback_result = [
        {
            "title": "Recovered",
            "url": "https://example.com/recovered",
            "description": "System HTTP fallback",
            "position": 1,
        }
    ]
    monkeypatch.setattr(module, "_run_ddgs_search", fail_primary)
    monkeypatch.setattr(
        module,
        "_run_html_fallback",
        lambda query, limit: fallback_result,
    )

    result = module.DDGSWebSearchProvider().search("test", limit=1)

    assert result == {"success": True, "data": {"web": fallback_result}}


def test_html_fallback_uses_httpx_and_returns_normalized_results(monkeypatch) -> None:
    module = load_provider(monkeypatch)

    class FakeResponse:
        text = """
        <a class="result__a" href="https://example.com/">Example</a>
        <a class="result__snippet" href="https://example.com/">
          A useful result
        </a>
        """

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            assert kwargs["follow_redirects"] is True

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def post(self, url: str, *, data: dict):
            assert url == module._DUCKDUCKGO_HTML_URL
            assert data == {"q": "hello"}
            return FakeResponse()

    httpx = types.ModuleType("httpx")
    httpx.Client = FakeClient
    monkeypatch.setitem(sys.modules, "httpx", httpx)

    assert module._run_html_fallback("hello", 3) == [
        {
            "title": "Example",
            "url": "https://example.com/",
            "description": "A useful result",
            "position": 1,
        }
    ]
