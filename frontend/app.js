"use strict";

// Fixed SQL: user input is only ever sent as a bound argument, never as SQL text.
const SEARCH_SQL = `SELECT id, headword, orth, substr(body, 1, 2000) AS body,
  COALESCE(senses, '') AS senses,
  CASE WHEN headword_norm LIKE ? || '%' OR headword_norm GLOB ? THEN 0 ELSE 1 END AS rank
  FROM entries
  WHERE headword_norm LIKE ? || '%' OR body_norm LIKE '%' || ? || '%'
    OR headword_norm GLOB ? OR body_norm GLOB ?
  ORDER BY rank, length(headword_norm), headword_norm
  LIMIT 25`;

// Landing entry: a random letter narrows the scan, then one entry is picked.
const RANDOM_SQL = `SELECT id, headword, orth, substr(body, 1, 2000) AS body,
  COALESCE(senses, '') AS senses
  FROM entries
  WHERE headword_norm LIKE ? || '%'
  ORDER BY RANDOM()
  LIMIT 1`;

const GREEK_LETTERS = "αβγδεζηθικλμνξοπρστυφχψω".split("");

const GREEK_LETTERS_MAP = {
  a:"α", b:"β", c:"κ", d:"δ", e:"[εη]", f:"φ", g:"γ", h:"", i:"ι",
  k:"κ", l:"λ", m:"μ", n:"ν", o:"[οω]", p:"π", r:"ρ", s:"σ",
  t:"τ", u:"υ", x:"ξ", y:"υ", z:"ζ",
};
const GREEK_DIGRAPHS = { th:"θ", ph:"φ", ch:"χ", kh:"χ", ps:"ψ" };

const form = document.getElementById("search-form");
const input = document.getElementById("q");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");

let debounceTimer = null;
let controller = null;

function normalize(value) {
  return value
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/ς/g, "σ")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

// Latin input becomes a GLOB pattern; vowel classes cover ε/η and ο/ω in one shot.
function greekPattern(value) {
  let out = "";
  for (let i = 0; i < value.length; i++) {
    const pair = value.slice(i, i + 2);
    if (GREEK_DIGRAPHS[pair]) {
      out += GREEK_DIGRAPHS[pair];
      i++;
      continue;
    }
    out += GREEK_LETTERS_MAP[value[i]] ?? value[i];
  }
  return out;
}

function parseSenses(raw) {
  try {
    return raw ? JSON.parse(raw) : [];
  } catch (error) {
    return [];
  }
}

function previewFor(row, senses) {
  const first = senses[0];
  const gloss = first && Array.isArray(first.gloss) ? first.gloss.join(", ") : "";
  return gloss || (row.body || "").replace(/\s+/g, " ").slice(0, 120) || "—";
}

function senseNode(sense) {
  const section = document.createElement("div");
  section.className = "sense";

  const label = document.createElement("div");
  label.className = "label";
  label.textContent = sense.label || "—";

  const body = document.createElement("div");

  const gloss = document.createElement("p");
  gloss.className = "gloss";
  gloss.textContent = Array.isArray(sense.gloss)
    ? sense.gloss.join("; ")
    : sense.gloss || "";
  body.append(gloss);

  if (Array.isArray(sense.greek) && sense.greek.length) {
    const greek = document.createElement("p");
    greek.className = "greek";
    greek.lang = "grc";
    greek.textContent = sense.greek.join(" · ");
    body.append(greek);
  }

  const citations = sense.citations || [];
  if (Array.isArray(citations) && citations.length) {
    const cites = document.createElement("p");
    cites.className = "cites";
    cites.textContent = citations.join("  ·  ");
    body.append(cites);
  }

  section.append(label, body);
  return section;
}

function render(rows) {
  resultsEl.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No matches found.";
    resultsEl.append(empty);
    return;
  }

  for (const [i, row] of rows.entries()) {
    const senses = parseSenses(row.senses);
    const entry = document.createElement("details");
    entry.className = "entry";
    if (i === 0) entry.open = true;

    const summary = document.createElement("summary");
    const no = document.createElement("span");
    no.className = "no";
    no.textContent = String(row.id || "").padStart(2, "0");
    const head = document.createElement("h2");
    head.className = "head";
    head.lang = "grc";
    head.textContent = row.headword || "—";
    const orth = document.createElement("span");
    orth.className = "orth";
    orth.lang = "grc";
    orth.textContent = row.orth || "";
    const chev = document.createElement("span");
    chev.className = "chev";
    chev.textContent = "senses +";
    summary.append(no, head, orth, chev);

    const preview = document.createElement("p");
    preview.className = "preview";
    preview.textContent = previewFor(row, senses);

    entry.append(summary, preview);
    if (senses.length) {
      for (const sense of senses.slice(0, 30)) entry.append(senseNode(sense));
    } else {
      const gloss = document.createElement("p");
      gloss.className = "gloss";
      gloss.textContent = row.body || "(no gloss available)";
      entry.append(gloss);
    }
    entry.addEventListener("toggle", () => {
      chev.textContent = entry.open ? "senses −" : "senses +";
    });
    resultsEl.append(entry);
  }
}

async function query(sql, args) {
  if (controller) controller.abort();
  controller = new AbortController();

  const payload = {
    requests: [
      { type: "execute", stmt: { sql, args } },
      { type: "close" },
    ],
  };

  const response = await fetch("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: controller.signal,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);

  const data = await response.json();
  const first = data.results && data.results[0];
  if (first && first.type === "error") {
    throw new Error((first.error && first.error.message) || "Database query failed");
  }
  const result = first && first.response && first.response.result;
  if (!result) throw new Error("Unexpected response from server");

  const columns = result.cols.map((col) => col.name);
  return result.rows.map((row) =>
    Object.fromEntries(columns.map((name, i) => [name, (row[i] && row[i].value) || ""]))
  );
}

async function showRandom() {
  const start = Math.floor(Math.random() * GREEK_LETTERS.length);
  const letters = [...GREEK_LETTERS.slice(start), ...GREEK_LETTERS.slice(0, start)];
  for (const letter of letters.slice(0, 3)) {
    try {
      const rows = await query(RANDOM_SQL, [{ type: "text", value: letter }]);
      if (rows.length) {
        render(rows);
        statusEl.textContent = "";
        return;
      }
    } catch (error) {
      if (error.name === "AbortError") return;
      statusEl.textContent = `Error: ${error.message}`;
      return;
    }
  }
  resultsEl.replaceChildren();
  statusEl.textContent = "";
}

async function run(term) {
  const text = normalize(term);
  if (!text) {
    await showRandom();
    return;
  }

  try {
    const arg = { type: "text", value: text };
    const pattern = greekPattern(text);
    const headGlob = { type: "text", value: pattern + "*" };
    const bodyGlob = { type: "text", value: "*" + pattern + "*" };
    const rows = await query(SEARCH_SQL, [arg, headGlob, arg, arg, headGlob, bodyGlob]);
    render(rows);
    statusEl.textContent = `${rows.length} result${rows.length === 1 ? "" : "s"}`;
  } catch (error) {
    if (error.name === "AbortError") return;
    resultsEl.replaceChildren();
    statusEl.textContent = `Error: ${error.message}`;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(debounceTimer);
  run(input.value);
});

input.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => run(input.value), 250);
});

showRandom();
