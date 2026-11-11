from __future__ import annotations

from dataclasses import dataclass
import re


URL_RE = re.compile(r"https?://[^\s<>\]\[(){}]+", re.IGNORECASE)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    evidence: str = ""


def extract_urls(text: str, max_urls: int = 25) -> list[str]:
    """Return unique public HTTP(S) links while trimming common prose punctuation."""
    urls: list[str] = []
    for match in URL_RE.findall(text):
        url = match.rstrip(".,;:'\"")
        if url not in urls:
            urls.append(url)
        if len(urls) >= max_urls:
            break
    return urls


def search_web(query: str, max_results: int = 5) -> list[SearchResult]:
    from ddgs import DDGS

    raw = DDGS(timeout=12).text(query, max_results=max_results)
    return [
        SearchResult(
            title=str(item.get("title", "Untitled")),
            url=str(item.get("href") or item.get("url") or ""),
            snippet=str(item.get("body") or item.get("snippet") or ""),
        )
        for item in raw
        if item.get("href") or item.get("url")
    ]


def fetch_urls(urls: list[str], max_urls: int = 25) -> list[SearchResult]:
    """Retrieve bounded readable text from explicitly supplied URLs."""
    from ddgs import DDGS

    client = DDGS(timeout=20)
    results: list[SearchResult] = []
    for url in list(dict.fromkeys(urls))[:max_urls]:
        try:
            extracted = client.extract(url, fmt="text_plain")
            content = str(extracted.get("content", "")).strip()
            title = str(extracted.get("title") or url)
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=content[:500],
                    evidence=content[:12000],
                )
            )
        except Exception:
            results.append(SearchResult(title=url, url=url, snippet="", evidence=""))
    return results


def research_web(
    query: str,
    max_results: int = 5,
    extract_results: int = 3,
    source_text: str = "",
    deadline_seconds: float = 10.0,
) -> list[SearchResult]:
    """Open supplied links and search the public web for evidence-based comparison."""
    from ddgs import DDGS

    direct_urls = extract_urls(query + "\n" + source_text)
    results = fetch_urls(direct_urls, max_urls=max_results)
    search_query = URL_RE.sub(" ", query)
    search_query = " ".join(search_query.split())[:320]
    remaining = max(0, max_results - len(results))
    if search_query and remaining:
        try:
            searched = search_web(search_query, max_results=remaining)
        except Exception:
            if not any(item.evidence for item in results):
                raise
            searched = []  # A search outage must not discard a page already read.
        existing = {item.url for item in results}
        results.extend(item for item in searched if item.url not in existing)
    # Speed: read the chosen pages in parallel, with one overall deadline, instead of
    # one after another. A page that is too slow keeps its search snippet as evidence.
    pending = [item for item in results if not item.evidence][:extract_results]
    if pending:
        from concurrent.futures import ThreadPoolExecutor, wait

        def read(item):
            extracted = DDGS(timeout=8).extract(item.url, fmt="text_plain")
            return str(extracted.get("content", "")).strip()[:5000]

        pool = ThreadPoolExecutor(max_workers=len(pending))
        futures = {pool.submit(read, item): item for item in pending}
        done, _late = wait(futures, timeout=deadline_seconds)
        for future, item in futures.items():
            try:
                item.evidence = future.result() if future in done else item.snippet
            except Exception:
                item.evidence = item.snippet
            item.evidence = item.evidence or item.snippet
        pool.shutdown(wait=False, cancel_futures=True)
    return results
