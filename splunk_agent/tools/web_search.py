"""Web search: Tavily if TAVILY_API_KEY is set, otherwise DuckDuckGo (no key needed).

User messages often contain raw logs, so IPs, emails, DOMAIN\\user names and hashes
are removed from the query before it is sent.
"""

import re

import httpx
from ddgs import DDGS

SPLUNK_SITES = [
    "help.splunk.com",
    "docs.splunk.com",
    "lantern.splunk.com",
    "community.splunk.com",
    "research.splunk.com",
]

SENSITIVE_PATTERNS = [
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",  # IPv4 address
    r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",  # email
    r"\b[\w-]+\\[\w.$-]+\b",  # DOMAIN\user
    r"\b[0-9a-fA-F]{32,}\b",  # hashes / tokens
]


def scrub_query(query: str) -> str:
    for pattern in SENSITIVE_PATTERNS:
        query = re.sub(pattern, "", query)
    return " ".join(query.split())[:300]


def search_tavily(query: str, api_key: str) -> list[dict]:
    response = httpx.post(
        "https://api.tavily.com/search",
        json={"query": query, "max_results": 5, "include_domains": SPLUNK_SITES},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20,
    )
    response.raise_for_status()
    return [
        {"title": r["title"], "url": r["url"], "snippet": r.get("content", "")[:800]}
        for r in response.json().get("results", [])
    ]


def search_duckduckgo(query: str) -> list[dict]:
    if "splunk" not in query.lower():
        query = "splunk " + query
    rows = DDGS().text(query, max_results=10) or []
    results = [{"title": r["title"], "url": r["href"], "snippet": r.get("body", "")[:800]} for r in rows]
    # Put official Splunk sites first.
    results.sort(key=lambda r: not any(site in r["url"] for site in SPLUNK_SITES))
    return results[:5]


def web_search(query: str, tavily_api_key: str = "") -> dict:
    query = scrub_query(query)
    if not query:
        return {"query": query, "error": "Query is empty after removing sensitive values."}
    try:
        if tavily_api_key:
            return {"query": query, "provider": "tavily", "results": search_tavily(query, tavily_api_key)}
        return {"query": query, "provider": "duckduckgo", "results": search_duckduckgo(query)}
    except Exception as e:
        return {"query": query, "error": f"Search failed: {e}"}
