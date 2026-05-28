from __future__ import annotations

from datetime import datetime
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


def _event_message(status: str, platform: str, target: str, detail: str) -> str:
    timestamp = datetime.now().isoformat(timespec="seconds")
    return f"{status} | timestamp={timestamp} | platform={platform} | target={target} | {detail}"


def _normalize_search_query_item(item: Any) -> dict[str, str]:
    if isinstance(item, dict):
        query = str(item.get("query", "")).strip()
        platform = str(item.get("platform", "search")).strip() or "search"
        return {"query": query, "platform": platform}
    query = str(item or "").strip()
    return {"query": query, "platform": "search"}


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
                        meta={
                            "score": data.get("score"),
                            "subreddit": data.get("subreddit", ""),
                            "discovery_source": "direct",
                            "platform": "reddit",
                        },
                    )
                )
        except Exception as exc:
            errors.append(_event_message("failed", "reddit", f"{username}/{kind}", f"error={exc}"))
    return posts, errors


def collect_web_pages(urls: list[Any]) -> tuple[list[PostRecord], list[str]]:
    posts: list[PostRecord] = []
    errors: list[str] = []
    session = _session()
    for item in urls:
        if isinstance(item, dict):
            url = str(item.get("url", "")).strip()
            platform = str(item.get("platform", "web")).strip() or "web"
            discovery_source = str(item.get("discovery_source", "manual")).strip() or "manual"
        else:
            url = str(item or "").strip()
            platform = "web"
            discovery_source = "manual"
        if not url:
            continue
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
                        meta={"discovery_source": discovery_source, "platform": platform},
                    )
                )
        except Exception as exc:
            errors.append(_event_message("failed", platform, url, f"error={exc}"))
    return posts, errors


def collect_search_results(
    queries: list[Any],
    limit_per_query: int = 5,
    platform_caps: dict[str, int] | None = None,
) -> tuple[list[PostRecord], list[str]]:
    posts: list[PostRecord] = []
    errors: list[str] = []
    session = _session()
    platform_counts: dict[str, int] = {}
    for item in queries:
        query_item = _normalize_search_query_item(item)
        query = query_item["query"]
        platform = query_item["platform"]
        if not query:
            continue
        cap = (platform_caps or {}).get(platform, limit_per_query)
        current_count = platform_counts.get(platform, 0)
        if current_count >= cap:
            errors.append(_event_message("skipped", platform, query, f"warning=platform cap reached ({cap})"))
            continue
        remaining = max(cap - current_count, 0)
        effective_limit = min(limit_per_query, remaining)
        if effective_limit <= 0:
            continue
        try:
            resp = session.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                timeout=20,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            results = soup.select(".result")[:effective_limit]
            if not results:
                errors.append(_event_message("warning", platform, query, "warning=no public results"))
                continue
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
                        author="",
                        url=target,
                        title=title,
                        text=_excerpt(title, text),
                        meta={"query": query, "discovery_source": "duckduckgo", "platform": platform},
                    )
                )
                platform_counts[platform] = platform_counts.get(platform, 0) + 1
        except Exception as exc:
            errors.append(_event_message("failed", platform, query, f"error={exc}"))
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
                    meta={"discovery_source": "direct", "platform": "x"},
                )
            )
        except Exception as exc:
            errors.append(_event_message("failed", "x", profile_url, f"error={exc}"))

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
                    meta={"discovery_source": "direct", "platform": "x"},
                )
            )
        except Exception as exc:
            errors.append(_event_message("failed", "x", status_url, f"error={exc}"))

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
            platform = str(post.meta.get("platform", "x")).strip() or "x"
            errors.append(_event_message("failed", platform, post.url, f"error={exc}"))
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

    web_urls = config.get("web_urls", [])
    if web_urls:
        batch, batch_errors = collect_web_pages(web_urls)
        posts.extend(batch)
        errors.extend(batch_errors)

    search_queries = config.get("search_queries", [])
    search_platform_caps = config.get("search_platform_caps", {})
    if search_queries:
        batch, batch_errors = collect_search_results(
            search_queries,
            limit_per_query=min(limit, 5),
            platform_caps=search_platform_caps,
        )
        batch, enrich_errors = enrich_x_search_results(batch)
        posts.extend(batch)
        errors.extend(batch_errors)
        errors.extend(enrich_errors)

    deduped: dict[str, PostRecord] = {}
    for post in posts:
        deduped[post.post_id] = post
    return list(deduped.values()), errors
