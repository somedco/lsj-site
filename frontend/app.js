"use strict";

// Fixed SQL: user input is only ever sent as a bound argument, never as SQL text.
const SEARCH_SQL = `SELECT id, headword, orth, substr(body, 1, 2000) AS body,
  COALESCE(senses, '') AS senses,
  CASE WHEN headword_norm LIKE ? || '%' THEN 0 ELSE 1 END AS rank
  FROM entries
  WHERE headword_norm LIKE ? || '%' OR body_norm LIKE '%' || ? || '%'
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

function addText(parent, className, text) {
  const element = document.createElement("div");
  element.className = className;
  element.textContent = text;
  parent.append(element);
}

function renderSenses(container, raw) {
  let senses;
  try {
    senses = raw ? JSON.parse(raw) : [];
  } catch (error) {
    senses = [];
  }
  if (!senses.length) return false;

  for (const sense of senses.slice(0, 30)) {
    const section = document.createElement("section");
    section.className = "sense-row";

    if (sense.label) {
      const label = document.createElement("span");
      label.className = "sense-label";
      label.textContent = sense.label;
      section.append(label);
    }
    if (sense.gloss && sense.gloss.length) {
      addText(section, "sense-gloss", sense.gloss.join("; "));
    }
    if (sense.greek && sense.greek.length) {
      const greek = document.createElement("div");
      greek.className = "sense-greek";
      greek.lang = "grc";
      greek.textContent = sense.greek.join(" · ");
      section.append(greek);
    }
    if (sense.citations && sense.citations.length) {
      addText(section, "sense-cites", sense.citations.join("; "));
    }
    container.append(section);
  }
  return true;
}

function render(rows) {
  resultsEl.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.textContent = "No matches found.";
    empty.style.textAlign = "center";
    resultsEl.append(empty);
    return;
  }

  for (const row of rows) {
    const entry = document.createElement("article");
    entry.className = "entry";

    const mark = document.createElement("div");
    mark.className = "letter";
    mark.textContent = "§";
    entry.append(mark);

    const body = document.createElement("div");

    const head = document.createElement("h2");
    head.className = "head";
    head.lang = "grc";
    head.textContent = row.headword || "—";
    body.append(head);

    const orth = document.createElement("div");
    orth.className = "orth";
    orth.lang = "grc";
    orth.textContent = row.orth || "";
    body.append(orth);

    if (!renderSenses(body, row.senses)) {
      addText(body, "gloss", row.body || "(no gloss available)");
    }

    entry.append(body);
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
    const rows = await query(SEARCH_SQL, [arg, arg, arg]);
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
