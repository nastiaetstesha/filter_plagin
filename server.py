# server.py
import asyncio
from functools import partial
from pathlib import Path
from typing import List

import aiohttp
from aiohttp import web
import pymorphy3

from main import (
    process_article,
    load_charged_words,
    # HEADERS,
)


def parse_urls_param(request: web.Request) -> List[str]:
    raw = request.query.get("urls", "")
    return [u.strip() for u in raw.split(",") if u.strip()]


async def call_process(url: str, session: aiohttp.ClientSession, morph, charged_words):

    results: list[dict] = []
    await process_article(session, morph, charged_words, url, 0, results)

    if not results:
        return {"status": "PARSING_ERROR", "url": url, "score": None, "words_count": None}

    rec = results[0]
    return {
        "status": rec.get("status"),
        "url": url,
        "score": rec.get("score"),
        "words_count": rec.get("words_count"),
    }


async def analyze_handler(request: web.Request, morph, charged_words):

    urls = parse_urls_param(request)
    if not urls:
        return web.json_response({"error": "query parameter 'urls' is required"}, status=400)

    async with aiohttp.ClientSession() as session:
        tasks = [call_process(url, session, morph, charged_words) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    return web.json_response(results)


async def root_handler(_request: web.Request):

    return web.json_response({
        "ok": True,
        "usage": "/analyze?urls=https://inosmi.ru/...,https://inosmi.ru/..."
    })


async def healthz(_request: web.Request):
    return web.json_response({"ok": True})


def create_app() -> web.Application:
    app = web.Application()

    morph = pymorphy3.MorphAnalyzer()
    dict_dir = Path(__file__).resolve().parent / "charged_dict"
    charged_words = load_charged_words(dict_dir, morph)

    handler = partial(analyze_handler, morph=morph, charged_words=charged_words)

    app.add_routes([
        web.get("/", root_handler),
        web.get("/analyze", handler),
        web.get("/healthz", healthz),
    ])
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="127.0.0.1", port=8080)
