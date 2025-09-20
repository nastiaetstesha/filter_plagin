import aiohttp
import asyncio
import os
# import ssl
# import certifi
from urllib.parse import urlparse
from pathlib import Path
from adapters import SANITIZERS, ArticleNotFound
from text_tools import split_by_words, calculate_jaundice_rate
from collections import Counter
import pymorphy3
import string


CHARGED_WORDS = ["скандал", "шок", "сенсация", "катастрофа", "позор", "триумф", "отстаивать", "санкции"]
DICT_DIR = Path(__file__).resolve().parent / "charged_dict"


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


def load_charged_words(dict_dir: Path, morph) -> list[str]:
    """
    Читает все *.txt в папке, убирает шум, нормализует леммы
    и возвращает уникальный список «заряженных» слов.
    """
    words: set[str] = set()
    if not dict_dir.exists():
        return []

    def clean_token(tok: str) -> str:
        tok = tok.replace("«", "").replace("»", "").replace("…", "")
        tok = tok.strip(string.punctuation + "—–- «»\t ")
        return tok

    for path in sorted(dict_dir.glob("*.txt")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                for raw in line.replace(",", " ").split():
                    tok = clean_token(raw.lower())
                    if not tok:
                        continue
                    norm = morph.parse(tok)[0].normal_form
                    if len(norm) > 2 or norm == "не":
                        words.add(norm)
    return sorted(words)


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

    charged = load_charged_words(DICT_DIR, morph)
    if not charged:
        raise SystemExit(f"Словарь пуст. Положи .txt файлы в {DICT_DIR}")

    rating = calculate_jaundice_rate(article_words, charged)

    print(f"Рейтинг: {rating:.2f}")
    print(f"Слов в статье: {len(article_words)}")
    print("Словарь:", ", ".join(charged))


asyncio.run(main())
