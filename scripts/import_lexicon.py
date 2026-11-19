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

BATCH_SIZE = 100
BATCH_BYTES = 1_000_000
META_KEY = "upstream_sha"

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS entries (
        id TEXT PRIMARY KEY,
        headword TEXT NOT NULL,
        orth TEXT,
        body TEXT,
        headword_norm TEXT NOT NULL,
        body_norm TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_entries_headword_norm ON entries(headword_norm)",
    "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)",
]

UPSERT = """INSERT INTO entries (id, headword, orth, body, headword_norm, body_norm)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    headword=excluded.headword,
    orth=excluded.orth,
    body=excluded.body,
    headword_norm=excluded.headword_norm,
    body_norm=excluded.body_norm"""

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


def parse_file(path: Path):
    """Yield (id, headword, orth, body) for each lexicon entry in one XML file."""
    counter = 0
    for _, element in ET.iterparse(path, events=("end",)):
        if _tag(element) not in ("entryFree", "entry"):
            continue
        counter += 1
        entry_id = element.get("id") or f"{path.stem}-{counter}"
        headword = element.get("key") or ""

        orth_node = element.find(".//orth")
        orth = "".join(orth_node.itertext()).strip() if orth_node is not None else ""

        glosses = []
        for node in element.iter():
            if _tag(node) in ("tr", "def"):
                value = "".join(node.itertext()).strip()
                if value:
                    glosses.append(value)

        yield entry_id, headword, orth, " ".join(glosses)
        element.clear()


def _text_arg(value) -> dict:
    if value is None:
        return {"type": "null"}
    return {"type": "text", "value": str(value)}


def statement(sql: str, args=None, want_rows: bool = True) -> dict:
    stmt = {"sql": sql, "want_rows": want_rows}
    if args:
        stmt["args"] = [_text_arg(a) for a in args]
    return {"type": "execute", "stmt": stmt}


class Turso:
    def __init__(self, url: str, token: str):
        base = url.replace("libsql://", "https://").replace("turso://", "https://")
        self.endpoint = base.rstrip("/") + "/v2/pipeline"
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path, help="directory containing the LSJ XML files")
    options = parser.parse_args()

    db = Turso(os.environ["TURSO_DATABASE_URL"], os.environ["TURSO_AUTH_TOKEN"])
    sha = os.environ.get("UPSTREAM_SHA", "")

    db.call([statement(sql, want_rows=False) for sql in SCHEMA])

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
            db.call(batch)
            batch = []
            batch_bytes = 0

    files = sorted(options.source_dir.glob("grc.lsj.perseus-eng*.xml"))
    for path in files:
        for entry_id, headword, orth, body in parse_file(path):
            batch.append(
                statement(
                    UPSERT,
                    [entry_id, headword, orth, body, normalize(headword), normalize(body)],
                    want_rows=False,
                )
            )
            batch_bytes += len(body)
            total += 1
            if len(batch) >= BATCH_SIZE or batch_bytes >= BATCH_BYTES:
                flush()
        print(f"Parsed {path.name}")
    flush()

    db.call([statement(SET_META, [META_KEY, sha], want_rows=False)])
    print(f"Imported {total} entries from {len(files)} files (upstream {sha or 'unknown'}).")


if __name__ == "__main__":
    main()
