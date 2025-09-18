from bs4 import BeautifulSoup
import requests
import pytest

from .exceptions import ArticleNotFound
from .html_tools import remove_buzz_attrs, remove_buzz_tags, remove_all_tags


def _find_article_container(soup: BeautifulSoup):
    candidates = [
        "div.layout-article",
        "article.article",
        "article",
        "div.article__text",
        "div.article__content",
        "div.article__body",
        'div[itemprop="articleBody"]',
    ]
    for css in candidates:
        node = soup.select_one(css)
        if node and len(node.get_text(strip=True)) > 200:
            inner = node.select_one(".article__text, .article__content, .article__body")
            return inner or node
    return None


def _pick_article_container(soup: BeautifulSoup):
    for css in [
        "div.layout-article",
        "article.article",
        "article",
    ]:
        node = soup.select_one(css)
        if node:
            return node
    return None


def sanitize(html, plaintext=False):
    soup = BeautifulSoup(html, "html.parser")

    article = _pick_article_container(soup)
    if not article:
        raise ArticleNotFound()

    article.attrs = {}

    buzz_blocks = [
        *article.select(".article__notice"),
        *article.select(".article__aggr"),
        *article.select("aside"),
        *article.select(".media__copyright"),
        *article.select(".article__meta"),
        *article.select(".article__info"),
        *article.select(".article__tags"),
        *article.select(".share, .social, .banner, .ads, .subscribe"),
    ]
    for el in buzz_blocks:
        el.decompose()

    remove_buzz_attrs(article)
    remove_buzz_tags(article)

    if not plaintext:
        return article.prettify().strip()
    else:
        remove_all_tags(article)
        return article.get_text(" ", strip=True)
# def sanitize(html, plaintext=False):
#     soup = BeautifulSoup(html, 'html.parser')
#     article = soup.select_one("div.layout-article")

#     if not article:
#         raise ArticleNotFound()

#     article.attrs = {}

#     buzz_blocks = [
#         *article.select('.article__notice'),
#         *article.select('.article__aggr'),
#         *article.select('aside'),
#         *article.select('.media__copyright'),
#         *article.select('.article__meta'),
#         *article.select('.article__info'),
#         *article.select('.article__tags'),
#     ]
#     for el in buzz_blocks:
#         el.decompose()

#     remove_buzz_attrs(article)
#     remove_buzz_tags(article)

#     if not plaintext:
#         text = article.prettify()
#     else:
#         remove_all_tags(article)
#         text = article.get_text()
#     return text.strip()


def test_sanitize():
    resp = requests.get('https://inosmi.ru/economic/20190629/245384784.html')
    resp.raise_for_status()
    clean_text = sanitize(resp.text)

    assert 'В субботу, 29 июня, президент США Дональд Трамп' in clean_text
    assert 'За несколько часов до встречи с Си' in clean_text

    assert '<img src="' in clean_text
    assert '<h1>' in clean_text

    clean_plaintext = sanitize(resp.text, plaintext=True)

    assert 'В субботу, 29 июня, президент США Дональд Трамп' in clean_plaintext
    assert 'За несколько часов до встречи с Си' in clean_plaintext

    assert '<img src="' not in clean_plaintext
    assert '<a href="' not in clean_plaintext
    assert '<h1>' not in clean_plaintext
    assert '</article>' not in clean_plaintext
    assert '<h1>' not in clean_plaintext


def test_sanitize_wrong_url():
    resp = requests.get('http://example.com')
    resp.raise_for_status()
    with pytest.raises(ArticleNotFound):
        sanitize(resp.text)
