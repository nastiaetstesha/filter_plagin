import asyncio
import types
import pytest
import aiohttp

from main import (
    process_article,
    ProcessingStatus,
    ANALYSIS_TIMEOUT,
)
from server import create_app, MAX_URLS
from aiohttp.test_utils import TestServer, TestClient


class DummySession:
    """Фейковая aiohttp-сессия, чтобы не ходить в сеть."""
    def __init__(self, text: str = "<html></html>", raise_on_get: Exception | None = None):
        self._text = text
        self._raise = raise_on_get

    class _Resp:
        def __init__(self, text: str):
            self._text = text

        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc, tb): pass
        async def text(self): return self._text
        def raise_for_status(self): return None

    def get(self, url, timeout=None):
        if self._raise:
            raise self._raise
        return self._Resp(self._text)


def run_process_article_with_patches(monkeypatch, *, fetch_impl=None,
                                     sanitize_impl=None, split_impl=None,
                                     url="https://inosmi.ru/x.html"):
    if fetch_impl:
        monkeypatch.setattr("main.fetch", fetch_impl)
    if sanitize_impl:
        monkeypatch.setattr("main.pick_sanitizer", lambda _url: lambda html, plaintext=True: sanitize_impl(html))
    if split_impl:
        monkeypatch.setattr("main.split_by_words", split_impl)

    results: list[dict] = []

    import pymorphy3
    morph = pymorphy3.MorphAnalyzer()
    charged_words = ["скандал", "шок"]

    session = DummySession()

    asyncio.run(process_article(session, morph, charged_words, url, 0, results))
    assert len(results) == 1
    return results[0]


# тест 1: ошибка скачивания (FETCH_ERROR)
def test_process_article_fetch_error(monkeypatch):
    def fetch_raises(_session, _url):
        raise aiohttp.ClientError("boom")
    rec = run_process_article_with_patches(monkeypatch, fetch_impl=fetch_raises)
    assert rec["status"] == ProcessingStatus.FETCH_ERROR.value
    assert rec["score"] is None and rec["words_count"] is None


#  тест 2: ошибка парсинга (PARSING_ERROR) из-за отсутствия адаптера
def test_process_article_parsing_error_no_adapter(monkeypatch):
    monkeypatch.setattr("main.pick_sanitizer", lambda _url: (_ for _ in ()).throw(ValueError("no adapter")))
    rec = run_process_article_with_patches(monkeypatch)
    assert rec["status"] == ProcessingStatus.PARSING_ERROR.value


#  тест 3: ошибка парсинга (PARSING_ERROR) из-за ArticleNotFound 
def test_process_article_parsing_error_article_not_found(monkeypatch):
    from adapters import ArticleNotFound
    def sanitize_impl(_html): raise ArticleNotFound()
    rec = run_process_article_with_patches(monkeypatch, sanitize_impl=sanitize_impl)
    assert rec["status"] == ProcessingStatus.PARSING_ERROR.value


#  тест 4: таймаут анализа (TIMEOUT) 
def test_process_article_timeout(monkeypatch):
    async def slow_split(_morph, _text, yield_every: int = 500):
        await asyncio.sleep(ANALYSIS_TIMEOUT + 0.5)
        return []

    def fake_sanitize(_html):
        return "это тестовый текст " * 1_000_000

    rec = run_process_article_with_patches(
        monkeypatch,
        split_impl=slow_split,
        sanitize_impl=fake_sanitize,
    )

    assert rec["status"] == ProcessingStatus.TIMEOUT.value
    assert rec["score"] is None and rec["words_count"] is None


async def _request(app, path: str):
    server = TestServer(app)
    await server.start_server()
    try:
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.get(path)
            status = resp.status
            data = await resp.json()
            await resp.release()
            return status, data
        finally:
            await client.close()
    finally:
        await server.close()


def test_analyze_limit():
    app = create_app()
    many = ",".join(f"https://inosmi.ru/a{i}.html" for i in range(MAX_URLS + 1))
    status, data = asyncio.run(_request(app, f"/analyze?urls={many}"))
    assert status == 400
    assert "too many urls" in data["error"]


def test_analyze_missing_param():
    app = create_app()
    status, data = asyncio.run(_request(app, "/analyze"))
    assert status == 400
    assert "query parameter 'urls' is required" in data["error"]