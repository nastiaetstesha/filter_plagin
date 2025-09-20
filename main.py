import asyncio
import aiohttp
from urllib.parse import urlparse
from pathlib import Path
from collections import Counter
import string
from anyio import create_task_group, run as anyio_run
from bs4 import BeautifulSoup

import pymorphy3
from adapters import SANITIZERS, ArticleNotFound
from text_tools import split_by_words, calculate_jaundice_rate
from enum import Enum


# CHARGED_WORDS = ["скандал", "шок", "сенсация", "катастрофа", "позор", "триумф", "отстаивать", "санкции"]
class ProcessingStatus(Enum):
    OK = "OK"
    FETCH_ERROR = "FETCH_ERROR"
    PARSE_ERROR = "PARSE_ERROR"


DICT_DIR = Path(__file__).resolve().parent / "charged_dict"

TEST_ARTICLES = [
    'https://inosmi.ru/20250920/svo-274757749.html',
    # 'https://inosmi.ru/20250920/oshibki-274752226.html',
    'https://inosmi/html'
    'https://inosmi.ru/20250918/vss-274729939.html',
    'https://inosmi.ru/20250920/frantsiya-274764708.html',
    'https://inosmi.ru/20250920/iskusstvo-274760103.html'
]


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


def extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    title = soup.title.string if soup.title else None
    return (title or "").strip() or "Без заголовка"


async def process_article(session, morph, charged_words, url: str, idx: int, results: list):
    """Добавляет в results словарь с полями: url, status, title, score, words_count."""
    record = {
        "idx": idx, "url": url, "status": None,
        "title": None, "score": None, "words_count": None
    }
    try:
        html = await fetch(session, url)
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        record["status"] = ProcessingStatus.FETCH_ERROR.value
        results.append(record)
        return

    try:
        title = extract_title(html)
        sanitize = pick_sanitizer(url)
        text = sanitize(html, plaintext=True)
        article_words = split_by_words(morph, text)
        score = calculate_jaundice_rate(article_words, charged_words)

        record.update({
            "status": ProcessingStatus.OK.value,
            "title": title,
            "score": score,
            "words_count": len(article_words),
        })
    except ArticleNotFound:
        record["status"] = ProcessingStatus.PARSE_ERROR.value
    except Exception:
        record["status"] = ProcessingStatus.PARSE_ERROR.value

    results.append(record)
# async def process_article(session, morph, charged_words, url: str):
#     try:
#         html = await fetch(session, url)
#         title = extract_title(html)

#         sanitize = pick_sanitizer(url)
#         text = sanitize(html, plaintext=True)

#         article_words = split_by_words(morph, text)
#         score = calculate_jaundice_rate(article_words, charged_words)

#         print(f"URL: {url}")
#         print(f"Заголовок: {title}")
#         print(f"Рейтинг: {score:.2f}")
#         print(f"Слов в статье: {len(article_words)}")
#         print()
#     except ArticleNotFound:
#         print(f"URL: {url}\nОшибка: контейнер статьи не найден\n")
#     except Exception as e:
#         print(f"URL: {url}\nОшибка: {e}\n")


async def main():
    # url = "https://inosmi.ru/20250917/tramp_sanktsii-274720044.html"
    # async with aiohttp.ClientSession() as session:
    #     # html = await fetch(session, 'https://inosmi.ru/20250917/tramp_sanktsii-274720044.html')
    #     # print(html)
        
    #     html = await fetch(session, url)
    # sanitize = pick_sanitizer(url)
    # try:
    #     text = sanitize(html, plaintext=True)
    # except ArticleNotFound:
    #     raise SystemExit("Не удалось найти контейнер статьи на странице.")

    morph = pymorphy3.MorphAnalyzer()
    charged_words = load_charged_words(DICT_DIR, morph)
    if not charged_words:
        raise SystemExit(f"Словарь пуст. Положи .txt файлы в {DICT_DIR}")

    results: list[dict] = []

    async with aiohttp.ClientSession() as session:
        async with create_task_group() as tg:
            for idx, url in enumerate(TEST_ARTICLES):
                tg.start_soon(process_article, session, morph, charged_words, url, idx, results)

    for rec in sorted(results, key=lambda r: r["idx"]):
        print(f"URL: {rec['url']}")
        print(f"Статус: {rec['status']}")
        print(f"Рейтинг: {rec['score']}")
        print(f"Слов в статье: {rec['words_count']}\n")


asyncio.run(main())
