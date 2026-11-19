import io
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_lexicon  # noqa: E402


SAMPLE = """<TEI.2><text><body>
<div0 type="alphabetic letter">
<entryFree id="n1" key="λόγος" type="main">
  <orth extent="full" lang="greek">λόγος</orth>
  <sense n="A"><tr>word, speech</tr></sense>
  <sense n="B"><tr>reason, account</tr></sense>
</entryFree>
<entryFree key="Ϝ"><orth>Ϝ ϝ</orth><tr>w,</tr></entryFree>
</div0></body></text></TEI.2>"""


class ImportLexiconTests(unittest.TestCase):
    def test_normalize_strips_greek_accents_and_final_sigma(self):
        self.assertEqual(import_lexicon.normalize("Λόγος"), "λογοσ")
        self.assertEqual(import_lexicon.normalize("λόγος"), "λογοσ")
        self.assertEqual(import_lexicon.normalize("κόσμος"), "κοσμοσ")
        self.assertEqual(import_lexicon.normalize("ὁ δὲ λόγος"), "ο δε λογοσ")

    def test_parse_file_extracts_entries(self):
        path = Path(__file__).with_name("sample.xml")
        path.write_text(SAMPLE, encoding="utf-8")
        try:
            entries = list(import_lexicon.parse_file(path))
        finally:
            path.unlink()

        self.assertEqual(len(entries), 2)
        entry_id, headword, orth, body = entries[0]
        self.assertEqual(entry_id, "n1")
        self.assertEqual(headword, "λόγος")
        self.assertEqual(orth, "λόγος")
        self.assertEqual(body, "word, speech reason, account")
        self.assertEqual(entries[1][0], "sample-2")  # fallback id when absent
        self.assertEqual(entries[1][3], "w,")

    def test_statement_binds_text_arguments(self):
        stmt = import_lexicon.statement("SELECT ?", ["λόγος"], want_rows=False)
        self.assertEqual(stmt["stmt"]["args"], [{"type": "text", "value": "λόγος"}])
        self.assertFalse(stmt["stmt"]["want_rows"])

    def test_failed_batch_does_not_store_upstream_sha(self):
        def ok_result(rows=None, cols=None):
            return {"type": "ok", "response": {"type": "execute", "result": {
                "cols": cols or [], "rows": rows or [], "affected_row_count": 0,
                "last_insert_rowid": None}}}

        def response(*results):
            payload = {"results": list(results) + [{"type": "ok", "response": {"type": "close"}}]}
            return io.BytesIO(json.dumps(payload).encode("utf-8"))

        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(json.loads(req.data.decode("utf-8")))
            if len(calls) == 1:  # schema
                return response(*[ok_result() for _ in range(3)])
            if len(calls) == 2:  # meta lookup
                return response(ok_result(rows=[], cols=[{"name": "v"}]))
            return response({"type": "error", "error": {"message": "write failed"}})

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            (source / "grc.lsj.perseus-engtest.xml").write_text(SAMPLE, encoding="utf-8")
            env = {"TURSO_DATABASE_URL": "libsql://example.turso.io",
                   "TURSO_AUTH_TOKEN": "token", "UPSTREAM_SHA": "new-sha"}
            with patch.dict(os.environ, env), \
                 patch.object(import_lexicon.urllib.request, "urlopen", fake_urlopen), \
                 patch.object(sys, "argv", ["import_lexicon.py", str(source)]):
                with self.assertRaises(RuntimeError):
                    import_lexicon.main()

        self.assertFalse(any("INSERT INTO meta" in json.dumps(call) for call in calls))


if __name__ == "__main__":
    unittest.main()
