"""Tests for the eng1neer_notes module."""
import json
import sys
import os
import unittest
import tempfile
from pathlib import Path

# Ensure the repo root is importable regardless of how pytest is invoked.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import eng1neer_notes as notes


def _make_notes_file(tmp_dir: Path, docs=None) -> Path:
    """Write a minimal code_notes.json to *tmp_dir* and return its path."""
    if docs is None:
        docs = [
            {
                "id": "doc-one",
                "path": "eng1neer_patch.py",
                "range": {"start": 1, "end": 3},
                "title": "First document",
                "tags": ["patch", "engine"],
                "notes": ["A note about patching."],
                "text": "",
            },
            {
                "id": "doc-two",
                "path": "eng1neer.py",
                "range": {"start": 14, "end": 16},
                "title": "Second document",
                "tags": ["engine", "context"],
                "notes": ["Context state init."],
                "text": "existing text",
            },
        ]
    data = {
        "schema_version": 1,
        "repo": "dotpipe/anemone",
        "generated_at": "2026-01-01T00:00:00Z",
        "documents": docs,
    }
    p = tmp_dir / "code_notes.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


class TestLoadNotes(unittest.TestCase):
    def test_load_valid(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_notes_file(Path(td))
            data = notes.load_notes(p)
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(len(data["documents"]), 2)

    def test_load_missing_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            notes.load_notes(Path("/nonexistent/code_notes.json"))
        self.assertIn("not found", str(ctx.exception))

    def test_load_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "code_notes.json"
            p.write_text("{bad json", encoding="utf-8")
            with self.assertRaises(RuntimeError) as ctx:
                notes.load_notes(p)
            self.assertIn("not valid JSON", str(ctx.exception))


class TestListDocuments(unittest.TestCase):
    def test_list_returns_compact(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_notes_file(Path(td))
            listing = notes.list_documents(p)
            self.assertEqual(len(listing), 2)
            ids = [d["id"] for d in listing]
            self.assertIn("doc-one", ids)
            self.assertIn("doc-two", ids)
            # compact: no 'text' key
            for d in listing:
                self.assertNotIn("text", d)
                self.assertIn("location", d)

    def test_list_location_format(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_notes_file(Path(td))
            listing = notes.list_documents(p)
            loc = {d["id"]: d["location"] for d in listing}
            self.assertEqual(loc["doc-one"], "eng1neer_patch.py:1-3")
            self.assertEqual(loc["doc-two"], "eng1neer.py:14-16")


class TestGetDocument(unittest.TestCase):
    def test_get_existing(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_notes_file(Path(td))
            doc = notes.get_document("doc-one", p)
            self.assertEqual(doc["title"], "First document")

    def test_get_missing_raises_key_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_notes_file(Path(td))
            with self.assertRaises(KeyError):
                notes.get_document("nonexistent-id", p)


class TestSearchDocuments(unittest.TestCase):
    def test_search_by_title(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_notes_file(Path(td))
            results = notes.search_documents("second", p)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], "doc-two")

    def test_search_by_tag(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_notes_file(Path(td))
            results = notes.search_documents("patch", p)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], "doc-one")

    def test_search_no_match(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_notes_file(Path(td))
            results = notes.search_documents("zzznomatch", p)
            self.assertEqual(results, [])

    def test_search_by_notes_text(self):
        with tempfile.TemporaryDirectory() as td:
            p = _make_notes_file(Path(td))
            results = notes.search_documents("patching", p)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], "doc-one")


class TestRefreshNotes(unittest.TestCase):
    def test_refresh_updates_text_and_timestamp(self):
        """Refresh should read actual file content for existing files."""
        repo_root = Path(__file__).parent.parent
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            # use a doc pointing at eng1neer_patch.py lines 1-3 (exists in repo)
            p = _make_notes_file(tdp)
            before = notes.load_notes(p)["generated_at"]

            data = notes.refresh_notes(p, base_dir=repo_root)
            after = data["generated_at"]
            self.assertNotEqual(before, after)

            # doc-one should have real text now
            doc_one = next(d for d in data["documents"] if d["id"] == "doc-one")
            self.assertTrue(len(doc_one["text"]) > 0)

    def test_refresh_missing_file_records_error(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            docs = [
                {
                    "id": "bad-doc",
                    "path": "no_such_file.py",
                    "range": {"start": 1, "end": 5},
                    "title": "Bad",
                    "tags": [],
                    "notes": [],
                    "text": "",
                }
            ]
            p = _make_notes_file(tdp, docs=docs)
            data = notes.refresh_notes(p)
            self.assertTrue(len(data.get("_refresh_errors", [])) > 0)


class TestHandleNotesCommand(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._p = _make_notes_file(Path(self._td.name))

    def tearDown(self):
        self._td.cleanup()

    def _cmd(self, s):
        return notes.handle_notes_command(s, notes_path=self._p)

    def test_returns_none_for_non_notes_input(self):
        self.assertIsNone(self._cmd("what is the speed of light"))
        self.assertIsNone(self._cmd("help"))
        self.assertIsNone(self._cmd("list"))

    def test_help_notes(self):
        out = self._cmd("help notes")
        self.assertIn("list notes", out)
        self.assertIn("refresh notes", out)

    def test_notes_help(self):
        out = self._cmd("notes help")
        self.assertIn("search notes", out)

    def test_list_notes(self):
        out = self._cmd("list notes")
        self.assertIn("doc-one", out)
        self.assertIn("doc-two", out)

    def test_notes_list(self):
        out = self._cmd("notes list")
        self.assertIn("doc-one", out)

    def test_notes_id(self):
        out = self._cmd("notes doc-one")
        self.assertIn("First document", out)
        self.assertIn("patch", out)

    def test_notes_id_not_found(self):
        out = self._cmd("notes nonexistent-id")
        self.assertIn("nonexistent-id", out)

    def test_notes_info(self):
        out = self._cmd("notes info doc-two")
        self.assertIn("Second document", out)
        # info: no code block
        self.assertNotIn("```", out)

    def test_search_notes(self):
        out = self._cmd("search notes patching")
        self.assertIn("doc-one", out)

    def test_search_notes_no_match(self):
        out = self._cmd("search notes zzznomatch")
        self.assertIn("No code notes matching", out)

    def test_notes_tags(self):
        out = self._cmd("notes tags")
        self.assertIn("patch", out)
        self.assertIn("engine", out)

    def test_refresh_notes(self):
        repo_root = Path(__file__).parent.parent
        # pass base_dir via a notes_path-only call is not possible through
        # handle_notes_command, but we can at least confirm it runs without crash
        # and returns a sensible string (errors are collected, not raised)
        out = self._cmd("refresh notes")
        self.assertIn("Refreshed", out)


class TestHandleNotesCommandMissingFile(unittest.TestCase):
    def test_list_notes_missing_file(self):
        out = notes.handle_notes_command("list notes", notes_path=Path("/no/such/notes.json"))
        self.assertIn("not found", out)

    def test_search_notes_missing_file(self):
        out = notes.handle_notes_command("search notes foo", notes_path=Path("/no/such/notes.json"))
        self.assertIn("not found", out)

    def test_notes_id_missing_file(self):
        out = notes.handle_notes_command("notes doc-one", notes_path=Path("/no/such/notes.json"))
        self.assertIn("not found", out)


if __name__ == "__main__":
    unittest.main()
