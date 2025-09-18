import aiohttp
import asyncio
import os
# import ssl
# import certifi
from urllib.parse import urlparse

from adapters import SANITIZERS, ArticleNotFound


def pick_sanitizer(url: str):
    host = urlparse(url).netloc
    key = host.replace(".", "_").replace("-", "_")
    sanitizer = SANITIZERS.get(key)
    if not sanitizer:
        raise ValueError(f"No sanitizer for host: {host}")
    return sanitizer


async def fetch(session, url):
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.text()


async def main():
    async with aiohttp.ClientSession() as session:
        # html = await fetch(session, 'https://inosmi.ru/20250917/tramp_sanktsii-274720044.html')
        # print(html)
        url = "https://inosmi.ru/20250917/tramp_sanktsii-274720044.html"
        html = await fetch(session, url)
        sanitize = pick_sanitizer(url)
        try:
            text = sanitize(html, plaintext=True)
        except ArticleNotFound:
            raise SystemExit("Не удалось найти контейнер статьи на странице.")
        print(text)


asyncio.run(main())
