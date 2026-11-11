from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from forgemind.web import extract_urls, research_web


class FakeDDGS:
    def __init__(self, **_kwargs) -> None:
        pass

    def extract(self, url: str, **_kwargs) -> dict[str, str]:
        return {"title": "Direct page", "content": f"Retrieved evidence from {url}"}

    def text(self, query: str, **_kwargs) -> list[dict[str, str]]:
        return [{"title": "Search page", "href": "https://example.com/search", "body": query}]


class WebResearchTests(unittest.TestCase):
    def test_urls_are_extracted_and_deduplicated(self) -> None:
        text = "Read https://example.com/a, then https://example.com/a and https://example.org/b."
        self.assertEqual(
            extract_urls(text),
            ["https://example.com/a", "https://example.org/b"],
        )

    def test_supplied_url_is_opened_directly(self) -> None:
        fake_module = types.SimpleNamespace(DDGS=FakeDDGS)
        with patch.dict(sys.modules, {"ddgs": fake_module}):
            results = research_web("Open https://example.com/guide", max_results=1)
        self.assertEqual(results[0].url, "https://example.com/guide")
        self.assertIn("Retrieved evidence", results[0].evidence)


if __name__ == "__main__":
    unittest.main()
