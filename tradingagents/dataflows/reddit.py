"""Reddit search fetcher for ticker-specific discussion posts.

Uses Reddit's public RSS search endpoints (``old.reddit.com/r/{sub}/search.rss``)
which bypass Cloudflare's strict bot detection blocking the JSON endpoint.

Returns formatted plaintext blocks ready for prompt injection. Degrades
gracefully — returns a placeholder string rather than raising, so callers
never have to special-case missing data.
"""

from __future__ import annotations

import logging
import time
import re
import xml.etree.ElementTree as ET
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# Use old.reddit.com search.rss to avoid Cloudflare JS challenge / 403 Forbidden blocks
_API = "https://old.reddit.com/r/{sub}/search.rss?{qs}"
_UA = "python:cryptoagents.dataflow:v1.0.0 (by /u/cryptoagents_bot)"

# Default subreddits ordered roughly by signal density for ticker-specific
# discussion. wallstreetbets has the most volume but most noise; stocks /
# investing trend more measured. Caller can override.
DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")


def _fetch_subreddit(
    ticker: str,
    sub: str,
    limit: int,
    timeout: float,
) -> list[dict] | None:
    qs = urlencode({
        "q": ticker,
        "restrict_sr": "on",
        "sort": "new",
        "t": "week",  # last 7 days
    })
    url = _API.format(sub=sub, qs=qs)
    req = Request(url, headers={"User-Agent": _UA, "Accept": "application/rss+xml, application/atom+xml, xml"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            xml_data = resp.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.warning("Reddit RSS fetch failed for r/%s · %s: %s", sub, ticker, exc)
        if isinstance(exc, HTTPError) and exc.code == 403:
            return None
        return []

    # Parse XML Atom Feed
    try:
        root = ET.fromstring(xml_data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        
        posts = []
        for entry in entries[:limit]:
            title_el = entry.find("atom:title", ns)
            title = title_el.text if title_el is not None else ""
            
            author_el = entry.find("atom:author/atom:name", ns)
            author = author_el.text if author_el is not None else "unknown"
            if author.startswith("/u/"):
                author = author[3:]
                
            updated_el = entry.find("atom:updated", ns)
            updated_str = updated_el.text if updated_el is not None else ""
            
            created_date = "?"
            if updated_str:
                created_date = updated_str.split("T")[0]
                
            content_el = entry.find("atom:content", ns)
            content_html = content_el.text if content_el is not None else ""
            # Strip HTML tags to get raw body excerpt
            body = re.sub(r"<[^<]+?>", "", content_html)
            body = body.replace("\n", " ").strip()
            
            posts.append({
                "title": title,
                "author": author,
                "created_date": created_date,
                "body": body,
            })
        return posts
    except Exception as e:
        logger.warning("Reddit XML parsing failed for r/%s · %s: %s", sub, ticker, e)
        return []


def fetch_reddit_posts(
    ticker: str,
    subreddits: Iterable[str] = DEFAULT_SUBREDDITS,
    limit_per_sub: int = 5,
    timeout: float = 10.0,
    inter_request_delay: float = 0.4,
) -> str:
    """Fetch recent Reddit posts mentioning ``ticker`` across finance
    subreddits and return them as a formatted plaintext block.

    ``inter_request_delay`` keeps us under Reddit's public rate limit
    (~10 req/min per IP) even if the caller queries many subreddits.
    """
    blocks = []
    total_posts = 0
    blocked_count = 0
    
    for i, sub in enumerate(subreddits):
        if i > 0:
            time.sleep(inter_request_delay)
        posts = _fetch_subreddit(ticker, sub, limit_per_sub, timeout)
        
        if posts is None:
            blocked_count += 1
            blocks.append(f"r/{sub}: <Reddit search blocked by Cloudflare (HTTP 403 Forbidden)>")
            continue
            
        total_posts += len(posts)
        if not posts:
            blocks.append(f"r/{sub}: <no posts found mentioning {ticker.upper()} in the past 7 days>")
            continue

        lines = [f"r/{sub} — {len(posts)} recent posts mentioning {ticker.upper()}:"]
        for p in posts:
            title = p["title"].replace("\n", " ").strip()
            created_str = p["created_date"]
            selftext = p["body"]
            if len(selftext) > 240:
                selftext = selftext[:240] + "…"
            lines.append(
                f"  [{created_str} · @{p['author']}] {title}"
                + (f"\n    body excerpt: {selftext}" if selftext else "")
            )
        blocks.append("\n".join(lines))

    subreddits_list = list(subreddits)
    if blocked_count == len(subreddits_list):
        return f"<Reddit search is currently blocked by Cloudflare (HTTP 403 Forbidden) for {ticker.upper()}>"
    if total_posts == 0:
        return (
            f"<no Reddit posts found mentioning {ticker.upper()} across "
            f"{', '.join(f'r/{s}' for s in subreddits)} in the past 7 days>"
        )
    return "\n\n".join(blocks)
