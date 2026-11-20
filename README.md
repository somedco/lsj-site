# LSJ Lexicon site

Greek–English lexicon search over [gcelano/LSJ_GreekUnicode](https://github.com/gcelano/LSJ_GreekUnicode).

The data is **not** stored in this repo. A scheduled GitHub Action downloads the upstream XML, parses it, and upserts it into a hosted **Turso** (libSQL) database. The website is a static front-end served by nginx on your own Docker host; nginx proxies search requests to Turso and injects a read-only token, so the token never reaches the browser.

```
LSJ_GreekUnicode (XML) --[sync workflow]--> Turso <--[nginx /api/query]-- static site
```

## Setup

### 1. Turso

Create a free database at [turso.tech](https://turso.tech) and two tokens:

```bash
turso db tokens create lsj              # read/write — for the sync workflow
turso db tokens create lsj --read-only  # read-only  — for nginx
```

Get the HTTP host with `turso db show lsj --http-url`, or derive it from the database URL by replacing `libsql://` with `https://` and dropping any path (e.g. `https://lsj-yourname.turso.io`).

### 2. GitHub repository secrets

Settings → Secrets and variables → Actions → New repository secret:

| Name | Value |
| --- | --- |
| `TURSO_DATABASE_URL` | `libsql://…` database URL |
| `TURSO_AUTH_TOKEN` | the **read/write** token (created without `--read-only`) |

### 3. Your Docker host

Put the front-end, nginx config and compose file in one directory:

```
lsj-site/
├── sites/lsj/                  # extracted website archive for this site
├── nginx.conf                  # LSJ server block (one of several sites nginx serves)
├── docker-compose.yml
└── .env
```

`nginx.conf` uses the placeholder `lsj.example.com`. Replace it with the hostname that Cloudflare Tunnel sends for this site. Other sites keep their own server blocks; leave their configs alone.

`.env`:

```dotenv
TURSO_HOST=lsj-yourname.turso.io
TURSO_TOKEN=<the read-only token>
HTTP_PORT=80          # optional, defaults to 80
```

Then start it:

```bash
docker compose up -d
```

## Deploying a site update

1. In GitHub, run the **Build site** workflow (it also runs automatically when `frontend/` changes on `main`).
2. Download the `lsj-site` artifact and unpack it into `./sites/lsj` on your server (files must be directly in that folder, not in a nested `frontend/`).
3. The files are served immediately (nginx reads from the mounted directory). Run `docker compose restart nginx` only if you change `nginx.conf` or `.env`.

## Importing data

The **Sync LSJ data** workflow runs daily and can be triggered manually. To run the importer yourself:

```bash
git clone --depth 1 --branch master https://github.com/gcelano/LSJ_GreekUnicode.git /tmp/lsj
TURSO_DATABASE_URL=libsql://… TURSO_AUTH_TOKEN=… \
UPSTREAM_SHA=$(git -C /tmp/lsj rev-parse HEAD) \
python3 scripts/import_lexicon.py /tmp/lsj
```

The importer is idempotent and skips the work entirely when `UPSTREAM_SHA` matches the one stored in the database.

Run the local checks with:

```bash
python3 -m unittest discover -s tests
```

## How search works

Each XML entry is stored with its Greek headword, orthography and English glosses, plus accent-stripped, lowercased copies for matching. Search binds the (normalized) user input to a fixed SQL query: headword prefix matches rank first, then English definition matches. No user text is ever interpolated into SQL.

The nginx proxy uses Turso's `/v2/pipeline` HTTP protocol; the importer uses `/v3/pipeline` so each batch of upserts runs in one transaction. These are the parts coupled to an external wire format; if Turso changes them, update `nginx.conf` and the JSON payloads in `scripts/import_lexicon.py` / `frontend/app.js`.

Each entry keeps its glosses for search plus a JSON list of senses (label, gloss, Greek text and citations). The page shows the senses; entries imported before this change fall back to the old single gloss string until the next full import.

## License

Lexicon data: *A Greek–English Lexicon* by Henry George Liddell and Robert Scott, Perseus Project; Unicode conversion by Giuseppe G. A. Celano. Licensed [CC BY-NC-SA](https://creativecommons.org/licenses/by-nc-sa/4.0/) — attribution required, non-commercial use only.
