"""
fact_searcher.py

Searches Bing News RSS for supporting facts related to commentary topics.
Free, no API key required.

Adapted from sports-clip-tool/article_searcher.py
"""

import xml.etree.ElementTree as ET
from html import unescape
from typing import Optional
from urllib.parse import quote_plus

import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def search_facts(query: str, max_results: int = 5) -> list:
    """
    Search Bing News RSS for articles related to a query.

    Returns list of dicts: [{"title": str, "url": str, "snippet": str}, ...]
    """
    encoded = quote_plus(query)
    rss_url = f"https://www.bing.com/news/search?q={encoded}&format=rss&mkt=en-US"

    print(f"  [FactSearch] Searching: {query[:60]}")
    try:
        r = requests.get(rss_url, headers=_HEADERS, timeout=12)
        if r.status_code != 200:
            print(f"  [FactSearch] RSS fetch failed: HTTP {r.status_code}")
            return []

        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        results = []

        for item in items[:max_results]:
            title = item.findtext("title", "")
            link = item.findtext("link") or item.findtext("guid") or ""
            description = item.findtext("description", "")
            description = unescape(description)
            # Strip HTML tags from description
            import re
            description = re.sub(r"<[^>]+>", "", description)

            if link and link.startswith("http") and "bing.com" not in link:
                results.append({
                    "title": title,
                    "url": link,
                    "snippet": description[:300],
                })

        print(f"  [FactSearch] Found {len(results)} articles")
        return results

    except ET.ParseError as e:
        print(f"  [FactSearch] XML parse error: {e}")
        return []
    except Exception as e:
        print(f"  [FactSearch] Error: {e}")
        return []


def search_facts_for_topics(
    speakers: list,
    topics: list,
    stance_label: str,
) -> list:
    """
    Search for facts across all topics to support commentary.

    Args:
        speakers: List of speaker dicts from analysis
        topics: List of topic dicts from analysis
        stance_label: The stance the user chose (e.g. "Side with Tucker Carlson")

    Returns:
        List of fact dicts with topic_id association
    """
    all_facts = []
    speaker_names = [s["name"] for s in speakers]

    for topic in topics:
        # Build query from topic + speaker names
        query_parts = [topic.get("title", "")]
        for name in speaker_names:
            if name.lower() not in query_parts[0].lower():
                query_parts.append(name)

        query = " ".join(query_parts).strip()
        if not query:
            continue

        facts = search_facts(query, max_results=3)
        for fact in facts:
            fact["topic_id"] = topic.get("topic_id", 0)
        all_facts.extend(facts)

    print(f"[FactSearch] Total facts found: {len(all_facts)}")
    return all_facts
