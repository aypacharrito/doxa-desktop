from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from forgemind.database import MemoryDB
from forgemind.indexer import chunk_text, index_files, index_folder, read_document


class DatabaseTests(unittest.TestCase):
    def test_starter_knowledge_is_searchable(self) -> None:
        starter = Path(__file__).parents[1] / "starter_knowledge"
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            db = MemoryDB(Path(folder) / "starter.sqlite3")
            indexed, _ = index_folder(db, starter)
            self.assertGreaterEqual(indexed, 8)
            found = db.retrieve("How should I debug and reproduce a failure?")
            self.assertTrue(any("Reproduce before changing code" in item["content"] for item in found))

    def test_memory_and_document_retrieval(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            db = MemoryDB(root / "test.sqlite3")
            db.add_memory("Pacifica uses FastAPI with PostgreSQL")
            db.add_learning(
                "The CRM deployment uses Windows Server",
                kind="observation",
                confidence=0.9,
            )
            db.add_message("user", "Our authentication system uses short-lived access tokens")
            db.add_message("user", "x" * 12000)
            self.assertEqual(len(db.long_messages()), 1)
            long_id = db.long_messages()[0]["id"]
            db.replace_message_content(long_id, "[imported]")
            self.assertEqual(len(db.long_messages()), 0)
            source = root / "billing.py"
            source.write_text("def calculate_premium(age):\n    return age * 1.5\n", encoding="utf-8")
            indexed, skipped = index_folder(db, root)
            self.assertEqual(indexed, 1)
            self.assertEqual(skipped, 0)
            found = db.retrieve("How does calculate_premium work?")
            self.assertTrue(any("calculate_premium" in item["content"] for item in found))
            memories = db.retrieve("Which database does Pacifica use?")
            self.assertTrue(any("PostgreSQL" in item["content"] for item in memories))
            chats = db.retrieve("How does our authentication use access tokens?")
            self.assertTrue(any("short-lived" in item["content"] for item in chats))
            learned = db.retrieve("Which operating system does the CRM deployment use?")
            self.assertTrue(any("Windows Server" in item["content"] for item in learned))
            self.assertEqual(db.counts()["learnings"], 1)
            source.unlink()
            index_folder(db, root)
            self.assertEqual(db.counts()["documents"], 0)
            db.clear_messages()
            self.assertEqual(db.counts()["messages"], 0)

    def test_backup_is_valid_database(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            db = MemoryDB(root / "live.sqlite3")
            db.add_message("user", "hello")
            backup = db.backup_to(root / "backups")
            copy = MemoryDB(backup)
            self.assertEqual(copy.counts()["messages"], 1)


class ChunkTests(unittest.TestCase):
    def test_office_document_text_is_read_without_modifying_file(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            document = Path(folder) / "notes.docx"
            with zipfile.ZipFile(document, "w") as bundle:
                bundle.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="urn:test"><w:body><w:p><w:r><w:t>Quarterly premium report</w:t></w:r></w:p></w:body></w:document>',
                )
            size = document.stat().st_size
            self.assertIn("Quarterly premium report", read_document(document))
            self.assertEqual(document.stat().st_size, size)

    def test_explicit_file_connection_is_indexed_read_only(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            source = root / "notes.md"
            original = "The deployment region is us-west-2."
            source.write_text(original, encoding="utf-8")
            db = MemoryDB(root / "memory.sqlite3")
            indexed, skipped = index_files(db, [source])
            self.assertEqual((indexed, skipped), (1, 0))
            self.assertEqual(source.read_text(encoding="utf-8"), original)
            self.assertTrue(any("us-west-2" in item["content"] for item in db.retrieve("deployment region")))

    def test_chunks_overlap_and_cover_tail(self) -> None:
        text = "\n".join(f"line {i} useful code" for i in range(500))
        chunks = chunk_text(text, size=300, overlap=40)
        self.assertGreater(len(chunks), 2)
        self.assertIn("line 499", chunks[-1])


if __name__ == "__main__":
    unittest.main()
