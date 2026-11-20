#!/usr/bin/env python3
"""Import the LSJ TEI XML files into a Turso/libSQL database over its HTTP API."""

from __future__ import annotations

import argparse
import json
import os
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BATCH_SIZE = 300
BATCH_BYTES = 1_000_000
META_KEY = "upstream_sha"

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS entries (
        id TEXT PRIMARY KEY,
        headword TEXT NOT NULL,
        orth TEXT,
        body TEXT,
        headword_norm TEXT NOT NULL,
        body_norm TEXT NOT NULL,
        senses TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_entries_headword_norm ON entries(headword_norm)",
    "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)",
]

UPSERT = """INSERT INTO entries (id, headword, orth, body, headword_norm, body_norm, senses)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    headword=excluded.headword,
    orth=excluded.orth,
    body=excluded.body,
    headword_norm=excluded.headword_norm,
    body_norm=excluded.body_norm,
    senses=excluded.senses"""

SET_META = """INSERT INTO meta (k, v) VALUES (?, ?)
ON CONFLICT(k) DO UPDATE SET v=excluded.v"""


def normalize(text: str) -> str:
    """Lowercase, strip accents, unify final sigma, drop punctuation."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("ς", "σ").lower()
    words = []
    for word in text.split():
        word = "".join(c for c in word if c.isalnum() or c == "-")
        if word:
            words.append(word)
    return " ".join(words)


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _text(element: ET.Element) -> str:
    return "".join(element.itertext()).strip()


def _owner_sense(node: ET.Element, parents: dict) -> ET.Element | None:
    current = parents.get(node)
    while current is not None and _tag(current) != "sense":
        current = parents.get(current)
    return current


def parse_senses(element: ET.Element) -> list:
    """Build a small JSON-ready list: intro, then one item per sense."""
    parents = {child: parent for parent in element.iter() for child in parent}
    buckets: dict = {}
    intro = {"label": "", "level": "", "gloss": [], "greek": [], "citations": []}

    def bucket(node: ET.Element) -> dict:
        owner = _owner_sense(node, parents)
        if owner is None:
            return intro
        if owner not in buckets:
            buckets[owner] = {"label": "", "level": "", "gloss": [], "greek": [], "citations": []}
        return buckets[owner]

    for node in element.iter():
        tag = _tag(node)
        if tag in ("tr", "def"):
            value = _text(node)
            if value:
                bucket(node)["gloss"].append(value)
        elif tag in ("quote", "foreign"):
            value = _text(node)
            if value:
                bucket(node)["greek"].append(value)
        elif tag == "bibl":
            author = " ".join(_text(a) for a in node.iter() if _tag(a) == "author")
            title = " ".join(_text(t) for t in node.iter() if _tag(t) == "title")
            scope = " ".join(_text(s) for s in node.iter() if _tag(s) == "biblScope")
            citation = " ".join(x for x in (author or title, scope) if x).strip()
            if citation:
                bucket(node)["citations"].append(citation)

    result = []
    if any(intro[key] for key in ("gloss", "greek", "citations")):
        result.append(intro)

    for sense in element.iter():
        if _tag(sense) != "sense":
            continue
        item = buckets.get(sense)
        if item is None:
            continue
        item["label"] = sense.get("n") or ""
        item["level"] = sense.get("level") or ""
        result.append(item)

    return result


def parse_file(path: Path):
    """Yield (id, headword, orth, body, senses_json) for each lexicon entry."""
    counter = 0
    for _, element in ET.iterparse(path, events=("end",)):
        if _tag(element) not in ("entryFree", "entry"):
            continue
        counter += 1
        entry_id = element.get("id") or f"{path.stem}-{counter}"
        headword = element.get("key") or ""

        orth_node = element.find(".//orth")
        orth = _text(orth_node) if orth_node is not None else ""

        glosses = []
        for node in element.iter():
            if _tag(node) in ("tr", "def"):
                value = _text(node)
                if value:
                    glosses.append(value)

        senses = json.dumps(parse_senses(element), ensure_ascii=False, separators=(",", ":"))
        yield entry_id, headword, orth, " ".join(glosses), senses
        element.clear()


def _text_arg(value) -> dict:
    if value is None:
        return {"type": "null"}
    return {"type": "text", "value": str(value)}


def sql_stmt(sql: str, args=None, want_rows: bool = True) -> dict:
    stmt = {"sql": sql, "want_rows": want_rows}
    if args:
        stmt["args"] = [_text_arg(a) for a in args]
    return stmt


def statement(sql: str, args=None, want_rows: bool = True) -> dict:
    return {"type": "execute", "stmt": sql_stmt(sql, args, want_rows)}


def batch_request(statements: list) -> dict:
    """One BEGIN/COMMIT transaction. Later steps run only if earlier ones worked."""
    steps = [{"stmt": sql_stmt("BEGIN", want_rows=False)}]
    for index, stmt in enumerate(statements):
        steps.append({"condition": {"type": "ok", "step": index}, "stmt": stmt})
    last_write = len(steps) - 1
    steps.append({
        "condition": {"type": "ok", "step": last_write},
        "stmt": sql_stmt("COMMIT", want_rows=False),
    })
    commit = len(steps) - 1
    steps.append({
        "condition": {"type": "not", "cond": {"type": "ok", "step": commit}},
        "stmt": sql_stmt("ROLLBACK", want_rows=False),
    })
    return {"type": "batch", "batch": {"steps": steps}}


class Turso:
    def __init__(self, url: str, token: str):
        base = url.replace("libsql://", "https://").replace("turso://", "https://")
        self.endpoint = base.rstrip("/") + "/v3/pipeline"
        self.token = token

    def call(self, requests: list) -> list:
        payload = {"baton": None, "requests": list(requests) + [{"type": "close"}]}
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            data = json.load(response)
        results = data.get("results", [])[:-1]  # drop the close result
        for result in results:
            if result.get("type") == "error":
                raise RuntimeError(result["error"].get("message", "Turso query failed"))
        return results

    def rows(self, sql: str, args=None) -> list:
        result = self.call([statement(sql, args)])[0]
        return [[cell.get("value") for cell in row] for row in result["response"]["result"]["rows"]]

    def write_batch(self, statements: list) -> None:
        result = self.call([batch_request(statements)])[0]
        errors = result["response"]["result"]["step_errors"]
        if errors[-1]:
            raise RuntimeError(errors[-1].get("message", "ROLLBACK failed"))
        first_error = next((error for error in errors[:-1] if error), None)
        if first_error:
            raise RuntimeError(first_error.get("message", "Turso batch failed"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path, help="directory containing the LSJ XML files")
    options = parser.parse_args()

    db = Turso(os.environ["TURSO_DATABASE_URL"], os.environ["TURSO_AUTH_TOKEN"])
    sha = os.environ.get("UPSTREAM_SHA", "")

    db.call([statement(sql, want_rows=False) for sql in SCHEMA])
    try:
        db.call([statement("ALTER TABLE entries ADD COLUMN senses TEXT", want_rows=False)])
    except RuntimeError as error:
        if "duplicate column name" not in str(error).lower():
            raise  # a real error must stop the import

    previous = db.rows("SELECT v FROM meta WHERE k = ?", [META_KEY])
    if sha and previous and previous[0][0] == sha:
        print(f"Upstream unchanged ({sha}); nothing to import.")
        return

    batch = []
    batch_bytes = 0
    total = 0

    def flush() -> None:
        nonlocal batch, batch_bytes
        if batch:
            db.write_batch(batch)
            batch = []
            batch_bytes = 0

    files = sorted(options.source_dir.glob("grc.lsj.perseus-eng*.xml"))
    for path in files:
        for entry_id, headword, orth, body, senses in parse_file(path):
            batch.append(
                sql_stmt(
                    UPSERT,
                    [entry_id, headword, orth, body, normalize(headword), normalize(body), senses],
                    want_rows=False,
                )
            )
            batch_bytes += len(body) + len(senses)
            total += 1
            if len(batch) >= BATCH_SIZE or batch_bytes >= BATCH_BYTES:
                flush()
        print(f"Parsed {path.name}")
    flush()

    db.call([statement(SET_META, [META_KEY, sha], want_rows=False)])
    print(f"Imported {total} entries from {len(files)} files (upstream {sha or 'unknown'}).")


if __name__ == "__main__":
    main()
