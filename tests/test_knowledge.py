import tempfile
import unittest
from pathlib import Path

from forgemind import knowledge
from forgemind.agent import DoxaTools, TOOL_SPECS

SAMPLE = """# Doxa Knowledge

## Core rules (the short version)

1. **Distribution beats product.**
2. Volume of good attempts wins.

---

## Lessons

### 2026-11-08 · `content` `ai-tools` · AI makes the video; the idea is still the job
Hooks decide views.

### 2026-11-08 · `security` · Rotate leaked keys
Rotate first.

---

## To research next
- music
"""


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "lessons.md"
        self.path.write_text(SAMPLE, "utf-8")

    def tearDown(self):
        self.dir.cleanup()

    def test_core_rules_and_search(self):
        self.assertIn("Distribution beats product", knowledge.core_rules(self.path))
        self.assertNotIn("Lessons", knowledge.core_rules(self.path))
        found = knowledge.search("hooks for my video", self.path)
        self.assertTrue(found.startswith("### 2026-11-08 · `content`"))
        self.assertNotIn("Rotate", found)
        self.assertIn("Core rules", knowledge.search("zzz", self.path))

    def test_add_goes_before_research_list_and_validates(self):
        out = knowledge.add("Comment keyword funnels work", "Use comment-keyword CTAs honestly.", ["marketing", "bogus"],
                            "reel X", False, self.path)
        self.assertIn("Saved", out)
        text = self.path.read_text("utf-8")
        self.assertLess(text.index("Comment keyword funnels work"), text.index("## To research next"))
        self.assertIn("`marketing` · Comment keyword", text)
        self.assertNotIn("bogus", text)
        self.assertIn("(unverified)", text)
        with self.assertRaises(ValueError):
            knowledge.add("", "x", path=self.path)

    def test_doxa_has_the_tools(self):
        names = {spec["name"] for spec in TOOL_SPECS}
        self.assertTrue({"knowledge_search", "knowledge_add"} <= names)
        self.assertTrue(hasattr(DoxaTools, "_knowledge_search") and hasattr(DoxaTools, "_knowledge_add"))


if __name__ == "__main__":
    unittest.main()
