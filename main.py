import asyncio
import logging
import string
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import pymorphy3
from anyio import create_task_group, run as anyio_run
from async_timeout import timeout as async_timeout
from bs4 import BeautifulSoup

from adapters import SANITIZERS, ArticleNotFound
from text_tools import split_by_words, calculate_jaundice_rate


class ProcessingStatus(Enum):
    OK = "OK"
    FETCH_ERROR = "FETCH_ERROR"
    PARSING_ERROR = "PARSING_ERROR"
    TIMEOUT = "TIMEOUT"


REQUEST_TIMEOUT = 30.05

DICT_DIR = Path(__file__).resolve().parent / "charged_dict"
LARGE_TEXT = Path("samples/war_and_peace.txt").read_text(encoding="utf-8")

TEST_ARTICLES = [
    'https://inosmi.ru/20250920/svo-274757749.html',
    # 'https://inosmi.ru/20250920/oshibki-274752226.html',
    'https://inosmi/html',
    'https://anyio.readthedocs.io/en/latest/tasks.html',
    'https://lenta.ru/news/2025/09/20/v-germanii-predlozhili-sozdat-armiyu-bpla-posle-intsidenta-s-dronami-v-polshe/',
    'https://inosmi.ru/20250918/vss-274729939.html',
    'https://inosmi.ru/20250920/frantsiya-274764708.html',
    'https://inosmi.ru/20250920/iskusstvo-274760103.html'
]

ANALYSIS_TIMEOUT = 3.0

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("jaundice-rate")

logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pymorphy3").setLevel(logging.WARNING)
logging.getLogger("pymorphy3.opencorpora_dict").setLevel(logging.WARNING)
logging.getLogger("pymorphy3.opencorpora_dict.wrapper").setLevel(logging.WARNING)


# @contextmanager
# def elapsed_log(label: str):
#     start = time.monotonic()
#     try:
#         yield
#     finally:
#         dur = time.monotonic() - start
#         logger.info("%s за %.2f сек", label, dur)

def is_valid_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False
    

def pick_sanitizer(url: str):
    host = urlparse(url).netloc
    key = host.replace(".", "_").replace("-", "_")
    sanitizer = SANITIZERS.get(key)
    if not sanitizer:
        raise ValueError(f"No sanitizer for host: {host}")
    return sanitizer


async def fetch(session, url):
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with session.get(url, timeout=timeout) as response:
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
    """Добавляет в results словарь: url, status, title, score, words_count, elapsed."""
    record = {
        "idx": idx, "url": url, "status": None,
        "title": None, "score": None, "words_count": None,
        "elapsed": None,
    }

    if not is_valid_url(url):
        record["status"] = ProcessingStatus.FETCH_ERROR.value
        results.append(record)
        return

    try:
        async with async_timeout(REQUEST_TIMEOUT):
            html = await fetch(session, url)
    except asyncio.TimeoutError:
        record["status"] = ProcessingStatus.TIMEOUT.value
        results.append(record)
        return
    except (aiohttp.ClientError, asyncio.CancelledError):
        record["status"] = ProcessingStatus.FETCH_ERROR.value
        results.append(record)
        return

    # 2) санитизация
    try:
        title = extract_title(html)
        sanitize = pick_sanitizer(url)
        text = sanitize(html, plaintext=True)
    except (ValueError, ArticleNotFound):
        record["status"] = ProcessingStatus.PARSING_ERROR.value
        results.append(record)
        return
    except Exception:
        record["status"] = ProcessingStatus.PARSING_ERROR.value
        results.append(record)
        return

    # 3) анализ с таймаутом (split_by_words — async)
    start = time.monotonic()
    try:
        article_words = await asyncio.wait_for(
            split_by_words(morph, text),
            timeout=ANALYSIS_TIMEOUT,
        )
        score = calculate_jaundice_rate(article_words, charged_words)
        record.update({
            "status": ProcessingStatus.OK.value,
            "title": title,
            "score": score,
            "words_count": len(article_words),
        })
    except asyncio.TimeoutError:
        record["status"] = ProcessingStatus.TIMEOUT.value
    finally:
        record["elapsed"] = time.monotonic() - start

    results.append(record)



async def main():

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
        print(f"Слов в статье: {rec['words_count']}")
        if rec["status"] == ProcessingStatus.OK.value and rec.get("elapsed") is not None:
            logging.info("Анализ закончен за %.2f сек", rec["elapsed"])
        print()


asyncio.run(main())
