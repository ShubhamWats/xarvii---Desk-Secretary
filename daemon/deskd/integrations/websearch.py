import logging
import os

import httpx

log = logging.getLogger("deskd.websearch")


async def web_search(query: str, cfg) -> list[dict]:
    provider = cfg.websearch.provider.lower()
    max_results = cfg.websearch.max_results
    try:
        if provider == "tavily":
            return await _tavily(query, max_results)
        if provider == "brave":
            return await _brave(query, max_results)
    except Exception:
        log.exception("web search failed (%s)", provider)
        return []
    if provider not in ("none", ""):
        log.warning("unknown search provider %r", provider)
    return []


async def _tavily(query: str, max_results: int) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        log.warning("TAVILY_API_KEY not set")
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": query, "max_results": max_results},
        )
        r.raise_for_status()
        data = r.json()
    return [
        {"title": it.get("title", ""), "url": it.get("url", ""), "snippet": it.get("content", "")[:300]}
        for it in data.get("results", [])
    ]


async def _brave(query: str, max_results: int) -> list[dict]:
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if not key:
        log.warning("BRAVE_SEARCH_API_KEY not set")
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
    results = data.get("web", {}).get("results", [])
    return [
        {"title": it.get("title", ""), "url": it.get("url", ""), "snippet": it.get("description", "")[:300]}
        for it in results
    ]
