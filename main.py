import aiohttp
import asyncio
import os
# import ssl
# import certifi
from urllib.parse import urlparse

from adapters import SANITIZERS, ArticleNotFound
from text_tools import split_by_words, calculate_jaundice_rate
from collections import Counter
import pymorphy3


CHARGED_WORDS = ["скандал", "шок", "сенсация", "катастрофа", "позор", "триумф", "отстаивать", "санкции"]


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
    url = "https://inosmi.ru/20250917/tramp_sanktsii-274720044.html"
    async with aiohttp.ClientSession() as session:
        # html = await fetch(session, 'https://inosmi.ru/20250917/tramp_sanktsii-274720044.html')
        # print(html)
        
        html = await fetch(session, url)
    sanitize = pick_sanitizer(url)
    try:
        text = sanitize(html, plaintext=True)
    except ArticleNotFound:
        raise SystemExit("Не удалось найти контейнер статьи на странице.")

    morph = pymorphy3.MorphAnalyzer()
    article_words = split_by_words(morph, text)

    charged = CHARGED_WORDS
    if not charged:
        freq = Counter(w for w in article_words if len(w) >= 6)
        charged = [w for w, _ in freq.most_common(15)]

    rating = calculate_jaundice_rate(article_words, charged)

    print(f"Рейтинг: {rating:.2f}")
    print(f"Слов в статье: {len(article_words)}")
    print("Словарь:", ", ".join(charged))


asyncio.run(main())
