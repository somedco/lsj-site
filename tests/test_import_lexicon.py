import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
