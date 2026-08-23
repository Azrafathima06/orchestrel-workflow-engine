# Deploying Orchestrel

Free-tier portfolio deployment: Render (static site + one web service) and
Neon (PostgreSQL). No credentials appear in this repository — every
connection string is entered once in the Render dashboard.

## Architecture

```
Browser
   │
   ▼
Render Static Site  "orchestrel"          ← React build, SPA rewrite /* → /index.html
   │  HTTPS, exact-origin CORS
   ▼
Render Web Service  "orchestrel-api"      ← free plan, ONE instance
   entrypoint.sh:  alembic upgrade head → python -m app.seed → honcho start
     ├── web     uvicorn        binds $PORT
     ├── worker  celery worker  --concurrency=1
     └── beat    celery beat    (singleton)
   │                                   │
   ▼                                   ▼
Neon PostgreSQL                  Render Key Value
AUTHORITATIVE STATE              TRANSPORT ONLY (25 MB, no persistence)
```

**Why co-located processes:** Render's free tier does not offer Background
Workers. The API, one Celery worker, and one Celery Beat therefore share the
single free Web Service, supervised by `honcho` (see `backend/Procfile` and
`backend/entrypoint.sh`). honcho terminates the whole group when any child
exits, so a crashed API brings the container down and Render restarts it —
rather than leaving an instance that passes health checks with a dead API.

**Why exactly one Beat:** two Beats would double every recovery tick. The
free tier runs one instance, so this holds structurally today. If this
service is ever scaled beyond one instance, Beat must be split out first.

---

## Step-by-step

### 1. Public GitHub repository

Push `main` to a new public repository. Confirm before pushing:

```bash
git log --format='%h %an <%ae> %s'      # human author only, no AI trailers
git status --short                       # clean
git ls-files | grep -E '\.env$'          # must return nothing
```

### 2. Neon project

Create a project named `orchestrel`. Choose the region you will also use for
Render (lowest latency).

### 3. Pooled connection → `DATABASE_URL`

From the Neon dashboard, copy the **pooled** connection string — its host
carries a `-pooler` suffix. Used for all application queries.

Neon hands out a bare `postgresql://` scheme; the app normalizes it to
`postgresql+psycopg://` automatically, preserving credentials, port, and
query parameters including `sslmode=require`. Paste it verbatim.

### 4. Direct connection → `DATABASE_DIRECT_URL`

Copy the **direct / unpooled** connection string (no `-pooler`). Used only
by `alembic upgrade head` and the workflow seed. Neon runs PgBouncer in
transaction mode on the pooled endpoint and recommends a direct connection
for DDL.

> The application code uses no session-level features (no advisory locks, no
> `LISTEN/NOTIFY`, no `SET`, no temp tables), so ordinary queries are fully
> compatible with transaction-mode pooling. `SELECT ... FOR UPDATE` in the
> reconciler is transaction-scoped and supported.

### 5. Render Key Value

Create it **manually** in the Render dashboard — not via the blueprint. The
blueprint spec requires `ipAllowList` for `type: keyvalue` and does not
enumerate a free plan for it, so declaring it risks provisioning a paid
instance.

- Name: `orchestrel-broker`
- Plan: free (25 MB, **no persistence** — expected and safe)
- Region: same as the web service

### 6. Internal broker URL → `BROKER_URL`

Copy the **internal** connection URL. Both `redis://` and `rediss://` work.

> Losing broker contents is a tested scenario, not a risk: Redis holds no
> workflow state and no result backend is configured. On restart the
> recovery sweep re-dispatches stale `QUEUED` tasks, releases overdue
> retries, and reconciles stalled runs — all from PostgreSQL.

### 7. Render Blueprint

**New → Blueprint**, point at the repository. `render.yaml` creates:

- `orchestrel` — static site, root `frontend`, build `npm ci && npm run build`,
  publish `dist`, rewrite `/*` → `/index.html`
- `orchestrel-api` — Docker web service, free plan, `healthCheckPath: /health`

> **`/health`, never `/ready`.** Render probes the health path continuously,
> every few seconds. `/ready` performs real PostgreSQL and Redis round-trips,
> so using it would keep Neon's compute permanently awake — Neon free
> autosuspends after 5 minutes idle and bills from a 100 CU-hour monthly
> budget. `/health` touches nothing, which lets Neon sleep whenever the demo
> is idle. `/ready` remains available on demand for the dashboard.

### 8. Backend environment variables

On `orchestrel-api` set the four `sync: false` secrets:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Neon **pooled** string (step 3) |
| `DATABASE_DIRECT_URL` | Neon **direct** string (step 4) |
| `BROKER_URL` | Key Value **internal** URL (step 6) |
| `CORS_ORIGINS` | leave unset for now — set in step 14 |

`APP_ENV=production` and the public-safety limits are already declarative in
`render.yaml`.

> The app **refuses to start** in production if `DATABASE_URL` or
> `BROKER_URL` is still a Docker default, or if `CORS_ORIGINS` is empty or
> `*`. A misconfiguration fails loudly at boot instead of surfacing as a DNS
> error inside a request minutes later.

### 9. Backend first deploy

Deploy. The logs should show, in order:

```
[entrypoint] applying database migrations
[entrypoint] seeding workflow definitions
[entrypoint] starting web + worker + beat
```

then three honcho-prefixed process streams (`web.1`, `worker.1`, `beat.1`).
Confirm exactly one `beat`. Check memory headroom — three Python processes
share one free instance.

### 10. Verify `/health`

```bash
curl -i https://orchestrel-api.onrender.com/health
# 200  {"status":"ok","version":"0.1.0"}
```

### 11. Verify `/ready`

```bash
curl -s https://orchestrel-api.onrender.com/ready
# {"database":{"ok":true,...},"broker":{"ok":true,...},"workers_observed_5m":0}
```

Both components must report `ok: true`.

### 12. Frontend `VITE_API_BASE_URL`

On the `orchestrel` static site, set:

```
VITE_API_BASE_URL = https://orchestrel-api.onrender.com
```

Public configuration, not a secret — it is compiled into the browser bundle.
**Never** put a database or broker URL in a `VITE_*` variable.

> A production build with this unset **fails** rather than silently baking in
> `http://localhost:8000`. That failure is deliberate: the silent version
> looks like a backend outage to every visitor.

### 13. Frontend deploy

Deploy the static site. Note its origin, e.g.
`https://orchestrel.onrender.com`.

### 14. Exact `CORS_ORIGINS`

Set `CORS_ORIGINS` on `orchestrel-api` to that exact origin — no trailing
slash, no wildcard, no path:

```
CORS_ORIGINS = https://orchestrel.onrender.com
```

Redeploy the backend.

### 15. Full smoke test

Run every step. Do not skip the abuse probes.

| # | Check | Expected |
|---|---|---|
| A | Open the static site root | Overview renders with real data |
| B | Hard-refresh directly on `/runs/<id>` | Renders (proves the SPA rewrite) |
| C | First load after ≥15 min idle | Calm "Starting workflow engine…" screen, resolves within ~180 s; never a raw 502/CORS/network error |
| D | `curl -i $API/health` | `200 {"status":"ok"}` |
| E | `curl -s $API/ready` | database + broker both `ok: true` |
| F | `GET /api/v1/workflows` | 5 definitions |
| G | Trigger `sequential_etl` | `SUCCEEDED`, 4/4 tasks |
| H | Trigger `fanout_join` | `SUCCEEDED`, 6/6, shards show real durations |
| I | Trigger `retry_backoff` (`fail_until: 4`) | Visible `RETRYING` + countdown, then `SUCCEEDED`, 3 retries |
| J | Trigger `failure_isolation` | Branch A `FAILED`, descendants `UPSTREAM_FAILED` (0 attempts), branch B `SUCCEEDED` |
| K | Open a failed task in the inspector | Real worker id, duration, error type, attempt timeline |
| L | Reload `/runs` | History persists |
| M | Manual Deploy (or wait for spin-down), reload | All prior runs still present — PostgreSQL durability |
| N | `curl -H "Origin: https://evil.example" $API/api/v1/workflows -i` | No permissive `Access-Control-Allow-Origin` |
| O | `grep -oE "localhost\|neon.tech\|redis://" dist/assets/*.js` | No matches — no secrets in the bundle |
| P | Render logs | One `web`, one `worker`, one `beat`; no restart loop |
| Q | Neon dashboard | ≤ ~30 connections; compute **suspends** when idle |
| R | Abuse probes | see below |

**R — abuse probes, all must be refused:**

```bash
API=https://orchestrel-api.onrender.com

# fault-injection workflow is not publicly triggerable
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  $API/api/v1/workflows/crash_recovery/runs \
  -H 'Content-Type: application/json' -d '{"params":{}}'          # 403

# parameter above its declared maximum
curl -s -X POST $API/api/v1/workflows/retry_backoff/runs \
  -H 'Content-Type: application/json' \
  -d '{"params":{"fail_until":999999}}'                            # 422

# wrong parameter type
curl -s -X POST $API/api/v1/workflows/retry_backoff/runs \
  -H 'Content-Type: application/json' \
  -d '{"params":{"fail_until":"many"}}'                            # 422

# undeclared parameter
curl -s -X POST $API/api/v1/workflows/sequential_etl/runs \
  -H 'Content-Type: application/json' -d '{"params":{"evil":1}}'   # 422

# rate limit (>10/min per client)
for i in $(seq 1 15); do curl -s -o /dev/null -w '%{http_code} ' -X POST \
  $API/api/v1/workflows/sequential_etl/runs \
  -H 'Content-Type: application/json' -d '{"params":{}}'; done      # ends in 429

# oversized body
python3 -c "print('{\"params\":{\"x\":\"'+'a'*50000+'\"}}')" > /tmp/big.json
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  $API/api/v1/workflows/sequential_etl/runs \
  -H 'Content-Type: application/json' --data @/tmp/big.json         # 413

# unbounded pagination
curl -s -o /dev/null -w '%{http_code}\n' "$API/api/v1/runs?limit=100000"  # 422

# invalid UUID — clean error, no traceback
curl -s $API/api/v1/runs/not-a-uuid | head -c 200                   # no "Traceback", no "/app/"
```

---

## Free-tier limits worth knowing

| Resource | Limit | Consequence |
|---|---|---|
| Render web service | Spins down after 15 min idle; ~1 min restart | Cold start; API + worker + Beat sleep together |
| Render instance hours | 750/month per workspace | One always-on service ≈ 730 h — fits only if it is the workspace's only free web service |
| Render Key Value | 25 MB, **no persistence**, one free per workspace | Broker loss is expected and recoverable |
| Neon compute | 100 CU-hours/month/project | ≈ 400 h at 0.25 CU — safe **only** because `/health` lets Neon autosuspend |
| Neon storage | 0.5 GB | Outputs are capped at 128 KB and are typically a few hundred bytes |

The two free tiers cooperate: Render's spin-down stops Beat, which stops the
30-second sweep, which lets Neon autosuspend. Compute is consumed only while
the demo is actually being used.

**Nothing here requires a paid service.** Realistic upgrade triggers are
sustained traffic beyond ~400 Neon compute-hours, or wanting no cold start
(Render Starter).

## Rollback

Render keeps previous deploys. **Manual Deploy → pick an earlier commit.**
Migrations are additive; no destructive migration exists in this project's
history.
