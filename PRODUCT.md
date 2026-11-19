# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

People working with Ancient Greek who need to look up a lexicon entry — by Greek headword or by English definition — while reading or translating a text. [inferred from the interface's stated purpose and search fields; no user interview was captured]

## Product Purpose

Provide a fast, free, self-hostable Greek–English lexicon search over the LSJ (Liddell & Scott) lexicon. Success means a user can find the relevant entry quickly from either a Greek or an English query. [inferred from README and frontend copy]

## Positioning

A static web front-end that stays data-free: lexicon data is downloaded from the upstream `gcelano/LSJ_GreekUnicode` XML by a scheduled GitHub Action, parsed and upserted into a hosted Turso (libSQL) database, and served to the browser through an nginx proxy that injects a read-only token so the token never reaches the client. [from README and infrastructure config]

## Operating Context

-Search happens in a web browser; nginx serves static files and proxies `/api/query` to Turso's `/v2/pipeline` HTTP protocol.
-Data refresh is automated by the daily "Sync LSJ data" GitHub Action (also manually triggerable); site updates ship by running the "Build site" workflow and unpacking the `lsj-site` artifact into `./site` on a self-hosted Docker host.
-Deployment is the operator's own Docker host via `docker compose`, configured with a `.env` (Turso host, read-only token, optional HTTP port). [from README, workflows, docker-compose.yml, default.conf.template]

## Capabilities and Constraints

-Search by Greek headword (prefix match, ranked first) or English definition (substring match); results ordered by rank, headword length, then headword; capped at 25. [from frontend SQL]
-User input is accent-stripped, final-sigma normalized, lowercased and punctuation-stripped before matching; it is bound as a SQL argument only, never interpolated. [from app.js]
-Live, debounced search (250 ms) with request cancellation on each new query. [from app.js]
-Results are collapsible entries: headword, optional orthography, a gloss preview, and expandable entry body. [from app.js]
-The read-only Turso token is injected server-side by nginx; nginx rate-limits `/api/query` to 2 r/s with burst 5 and a 16 KB body cap. [from default.conf.template]
-Lexicon data is not stored in this repository; the sync importer is idempotent and skips work when the upstream SHA is unchanged. [from README and import script]
-Undecided/open: no user accounts, analytics, saved history, or mobile app exist or are committed to; no visual design direction has been established. [inferred absence; future work must not fabricate these]

## Brand Commitments

-Name: "LSJ Greek–English Lexicon" / "LSJ Lexicon site". [from README and page title]
-Data attribution is binding: *A Greek–English Lexicon* by Liddell & Scott (Perseus Project); Unicode conversion by Giuseppe G. A. Celano; licensed CC BY-NC-SA — attribution required, non-commercial use only. [from README and footer copy]

## Evidence on Hand

-README.md documents setup, deployment, data import, search behavior and licensing.
-Working front-end (`frontend/index.html`, `frontend/app.js`, `frontend/style.css`), nginx template, docker-compose, GitHub Actions workflows, an idempotent Python importer (`scripts/import_lexicon.py`) and unit tests (`tests/test_import_lexicon.py`).
-No visual design document, brand assets, imagery, testimonials, user research or analytics data exist yet — these must not be invented in future work. [observed absence]

## Product Principles

-Let the data lead: the product is a lookup tool, so speed and accuracy of results outrank decoration. [inferred]
-Keep credentials and data off the client and out of the repo: token injection at the proxy, data synced from upstream. [from README and config]
-Preserve the source license and attribution in every surface that shows lexicon data. [from README and footer]
-Stay self-hostable and dependency-light: static files plus one database and one proxy. [inferred from architecture]

## Accessibility & Inclusion

-No formal accessibility standard was established in the brief, but the shipped interface already uses a screen-reader-only label, an `aria-live` status region, keyboard-operable `<details>/<summary>` entries, and a Greek-capable system font stack. [observed in frontend code, not a stated requirement]
