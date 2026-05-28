from __future__ import annotations

import re
import urllib.parse
from typing import Any

import requests
from bs4 import BeautifulSoup

from .models import PostRecord


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    return session


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def _excerpt(title: str, text: str, limit: int = 800) -> str:
    body = f"{title}\n{text}".strip()
    return body[:limit]


def collect_reddit_user(username: str, limit: int = 8) -> tuple[list[PostRecord], list[str]]:
    posts: list[PostRecord] = []
    errors: list[str] = []
    session = _session()
    endpoints = [
        ("submitted", f"https://www.reddit.com/user/{username}/submitted.json?limit={limit}"),
        ("comments", f"https://www.reddit.com/user/{username}/comments.json?limit={limit}"),
    ]
    for kind, url in endpoints:
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            children = payload.get("data", {}).get("children", [])
            for child in children:
                data = child.get("data", {})
                title = data.get("title", "") if kind == "submitted" else f"Comment in r/{data.get('subreddit', '')}"
                text = data.get("selftext", "") if kind == "submitted" else data.get("body", "")
                permalink = data.get("permalink", "")
                post_url = f"https://www.reddit.com{permalink}" if permalink else url
                posts.append(
                    PostRecord(
                        post_id=f"reddit:{kind}:{data.get('id', '')}",
                        source=f"reddit_{kind}",
                        author=username,
                        url=post_url,
                        title=_clean_text(title),
                        text=_excerpt(title, _clean_text(text)),
                        published_at=str(data.get("created_utc", "")),
                        meta={"score": data.get("score"), "subreddit": data.get("subreddit", "")},
                    )
                )
        except Exception as exc:
            errors.append(f"Reddit {username} / {kind} 抓取失败: {exc}")
    return posts, errors


def collect_web_pages(urls: list[str]) -> tuple[list[PostRecord], list[str]]:
    posts: list[PostRecord] = []
    errors: list[str] = []
    session = _session()
    for url in urls:
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            title = _clean_text(soup.title.text if soup.title else url)
            text = _clean_text(" ".join(node.get_text(" ", strip=True) for node in soup.select("p, article, main, section")))
            if not text:
                text = _clean_text(soup.get_text(" ", strip=True))
            posts.append(
                PostRecord(
                    post_id=f"web:{url}",
                    source="web_page",
                    author=urllib.parse.urlparse(url).netloc,
                    url=url,
                    title=title,
                    text=_excerpt(title, text),
                )
            )
        except Exception as exc:
            errors.append(f"网页抓取失败 {url}: {exc}")
    return posts, errors


def collect_search_results(queries: list[str], limit_per_query: int = 5) -> tuple[list[PostRecord], list[str]]:
    posts: list[PostRecord] = []
    errors: list[str] = []
    session = _session()
    for query in queries:
        try:
            resp = session.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                timeout=20,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            results = soup.select(".result")[:limit_per_query]
            for idx, result in enumerate(results):
                link = result.select_one(".result__a")
                snippet = result.select_one(".result__snippet")
                href = link.get("href", "") if link else ""
                parsed = urllib.parse.urlparse(href)
                if parsed.netloc.endswith("duckduckgo.com"):
                    target = urllib.parse.parse_qs(parsed.query).get("uddg", [href])[0]
                else:
                    target = href
                title = _clean_text(link.get_text(" ", strip=True) if link else query)
                text = _clean_text(snippet.get_text(" ", strip=True) if snippet else "")
                posts.append(
                    PostRecord(
                        post_id=f"search:{query}:{idx}",
                        source="web_search",
                        author="duckduckgo",
                        url=target,
                        title=title,
                        text=_excerpt(title, text),
                        meta={"query": query},
                    )
                )
        except Exception as exc:
            errors.append(f"搜索抓取失败 {query}: {exc}")
    return posts, errors


def _fetch_jina_markdown(target_url: str, session: requests.Session) -> str:
    jina_url = f"https://r.jina.ai/http://{target_url.removeprefix('https://').removeprefix('http://')}"
    resp = session.get(jina_url, timeout=25)
    resp.raise_for_status()
    return resp.text


def collect_x_via_jina(
    usernames: list[str],
    status_urls: list[str] | None = None,
) -> tuple[list[PostRecord], list[str]]:
    posts: list[PostRecord] = []
    errors: list[str] = []
    session = _session()

    for username in usernames:
        if not username:
            continue
        profile_url = f"https://x.com/{username.lstrip('@')}"
        try:
            text = _fetch_jina_markdown(profile_url, session)
            posts.append(
                PostRecord(
                    post_id=f"x_profile:{username}",
                    source="x_profile_jina",
                    author=username.lstrip("@"),
                    url=profile_url,
                    title=f"X profile snapshot: {username}",
                    text=_excerpt(f"X profile snapshot: {username}", _clean_text(text), limit=2500),
                )
            )
        except Exception as exc:
            errors.append(f"X 主页抓取失败 {username}: {exc}")

    for status_url in status_urls or []:
        if not status_url:
            continue
        try:
            text = _fetch_jina_markdown(status_url, session)
            tail = status_url.rstrip("/").split("/")[-1]
            posts.append(
                PostRecord(
                    post_id=f"x_status:{tail}",
                    source="x_status_jina",
                    author="x",
                    url=status_url,
                    title=f"X status snapshot: {tail}",
                    text=_excerpt(f"X status snapshot: {tail}", _clean_text(text), limit=1800),
                )
            )
        except Exception as exc:
            errors.append(f"X 单帖抓取失败 {status_url}: {exc}")

    return posts, errors


def enrich_x_search_results(posts: list[PostRecord]) -> tuple[list[PostRecord], list[str]]:
    session = _session()
    enriched: list[PostRecord] = []
    errors: list[str] = []
    for post in posts:
        if "x.com/" not in post.url:
            enriched.append(post)
            continue
        try:
            text = _fetch_jina_markdown(post.url, session)
            enriched.append(
                PostRecord(
                    post_id=post.post_id,
                    source=f"{post.source}_jina",
                    author=post.author,
                    url=post.url,
                    title=post.title,
                    text=_excerpt(post.title, _clean_text(text), limit=2200),
                    published_at=post.published_at,
                    meta=post.meta,
                )
            )
        except Exception as exc:
            errors.append(f"X 搜索结果增强失败 {post.url}: {exc}")
            enriched.append(post)
    return enriched, errors


def collect_all(config: dict[str, Any]) -> tuple[list[PostRecord], list[str]]:
    posts: list[PostRecord] = []
    errors: list[str] = []
    limit = int(config.get("post_limit", 8))

    x_profiles = [name.strip() for name in config.get("x_profiles", []) if name.strip()]
    x_status_urls = [url.strip() for url in config.get("x_status_urls", []) if url.strip()]
    if x_profiles or x_status_urls:
        batch, batch_errors = collect_x_via_jina(x_profiles, x_status_urls)
        posts.extend(batch)
        errors.extend(batch_errors)

    for username in config.get("reddit_users", []):
        if not username:
            continue
        batch, batch_errors = collect_reddit_user(username.strip(), limit=limit)
        posts.extend(batch)
        errors.extend(batch_errors)

    web_urls = [url.strip() for url in config.get("web_urls", []) if url.strip()]
    if web_urls:
        batch, batch_errors = collect_web_pages(web_urls)
        posts.extend(batch)
        errors.extend(batch_errors)

    search_queries = [query.strip() for query in config.get("search_queries", []) if query.strip()]
    if search_queries:
        batch, batch_errors = collect_search_results(search_queries, limit_per_query=min(limit, 5))
        batch, enrich_errors = enrich_x_search_results(batch)
        posts.extend(batch)
        errors.extend(batch_errors)
        errors.extend(enrich_errors)

    deduped: dict[str, PostRecord] = {}
    for post in posts:
        deduped[post.post_id] = post
    return list(deduped.values()), errors
