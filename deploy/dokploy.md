# Deploying on Dokploy

Target host: `interviewer.evertontomalok.com.br`. This doc covers what
Dokploy is, what "the swarm" means here, and the exact steps to get this
repo's `docker-compose.yml` running behind that domain.

## 1. What Dokploy is

Dokploy is a self-hosted PaaS (open source, Heroku/Vercel-shaped) that runs
on a VPS you own. You point it at a git repo or a Docker Compose file; it
builds the image, runs it, terminates TLS, and reverse-proxies your domain to
the container. No vendor lock-in, no per-request billing — you pay for the
VPS, Dokploy is free.

Three pieces do the work:

- **Docker Swarm** — orchestrates containers (see §2).
- **Traefik** — reverse proxy + automatic Let's Encrypt certificates. Every
  app Dokploy deploys gets Traefik labels attached automatically; you never
  hand-write proxy config.
- **Dokploy's own API/UI** — project and env management, deploy triggers,
  logs, one-off command execution against a running container.

## 2. What "the swarm" is

Docker Swarm is Docker's built-in orchestrator (`docker swarm init`) —
Dokploy runs one under the hood, even on a single VPS. A single-node swarm
still buys you three things that matter for this deploy:

- **Rolling restarts.** Redeploying replaces the container without a hard
  stop-then-start gap — Swarm waits for the new one to pass its healthcheck
  before killing the old one.
- **Declarative services.** Each `docker-compose.yml` service becomes a
  Swarm *service*; Dokploy diffs and reconciles instead of `docker compose
  up`-ing by hand.
- **Room to grow.** Add a second VPS as a swarm worker node later and
  Dokploy can schedule services onto it — nothing about this deploy changes
  to get there, it's a Swarm property, not a Dokploy one.

You don't run any `docker swarm` command yourself — Dokploy's installer does
`docker swarm init` on the VPS during setup. Everything after that is UI.

## 3. What gets deployed

One image (`Dockerfile` at repo root), two processes, sharing all code and
dependencies:

| Service | Command | Exposes | Notes |
|---|---|---|---|
| `api` | `uvicorn interviewer_api.main:app --host 0.0.0.0 --port 8000` | 8000 | Also serves `apps/web/*.html` (mounted at `/`) — one origin, no CORS. |
| `worker` | `python -m interviewer_worker` | — | Consumes the Redis stream; a running interview needs this alive, `POST /session/turns` returns `202` and does nothing without it. |
| `postgres` | — | internal | `docker-compose.yml`'s own `postgres:16-alpine`, not a managed DB. |
| `redis` | — | internal | Workflow queue + `appendonly` persistence. |

Only `api` gets a public domain. `worker`, `postgres`, `redis` stay on the
compose network, unreachable from outside.

## 4. Prerequisites

- A VPS (2 GB RAM is enough for this workload) with a public IP, reachable
  on 80/443/443-udp and whatever port Dokploy's UI uses (default `3000`).
- Root/sudo SSH access to it.
- Ownership of `evertontomalok.com.br` at your registrar.

## 5. Install Dokploy

SSH into the VPS and run Dokploy's installer (single command, does the
`docker swarm init` + Traefik + Dokploy-UI bootstrap):

```bash
curl -sSL https://dokploy.com/install.sh | sh
```

Open `http://<vps-ip>:3000`, create the admin account. This first account is
Dokploy's own login, unrelated to this app's `SEED_ADMIN_EMAIL`.

## 6. Create the project + application

1. Dokploy UI → **Projects** → **Create Project** → name it `interviewer`.
2. Inside it, **Create Service** → **Compose**.
3. Point it at this repo (Git provider + branch `master`, or paste the repo
   URL if it's public) and set **Compose Path** to `docker-compose.yml`.
4. Set **Compose Profile** to `app` — the `api`/`worker` services in this
   repo are gated behind `profiles: ["app"]` on purpose (`make up` alone
   only brings up `postgres`/`redis` for local dev); Dokploy needs the
   profile enabled to bring the full stack up.

## 7. Environment variables

Dokploy's **Environment** tab for the compose service takes `KEY=value`
lines and injects them into every service in the compose file — this is
where secrets live, never in the repo. Copy `.env.example` as the starting
point and fill in at minimum:

```bash
APP_ENV=prod
LOG_JSON=true

# generate with: openssl rand -hex 32
AUTH_SECRET_KEY=<random 32+ byte secret>

PUBLIC_BASE_URL=https://interviewer.evertontomalok.com.br
REGISTRATION_OPEN=false

# `make seed`'s admin login -- change before running seed, see §9
SEED_ADMIN_EMAIL=admin@admin.com
SEED_ADMIN_PASSWORD=<pick your own, don't ship this file's placeholder>

# real providers -- set at least one, or leave LLM_PROVIDER=fake/STT_PROVIDER=fake
# to run scripted, keyless (see README §2)
LLM_PROVIDER=openrouter
LLM__OPENROUTER__API_KEY=<key>
STT_PROVIDER=openai_compat
STT__OPENAI_COMPAT__API_KEY=<key>
```

Leave `DATABASE_URL` / `REDIS_URL` unset here — `docker-compose.yml` already
hardcodes the in-swarm service hostnames (`postgres`, `redis`) for `api` and
`worker`, overriding whatever `.env.example`'s localhost defaults say.

`STORAGE__LOCAL_FS__ROOT=/var/blobs` is already set by the compose file and
backed by the `blobs` named volume — recordings and artifacts survive a
redeploy. `local_fs` is the only storage adapter actually registered today;
`Settings` has `STORAGE__S3__*`/`STORAGE__GCS__*` fields reserved for future
adapters (see README §5/§10), but setting `STORAGE_PROVIDER=s3` right now is
a `ConfigError` at boot — no adapter to build. Make sure the VPS disk under
the `blobs` volume has room for interview audio, or back it up.

## 8. Deploy

Click **Deploy**. Dokploy builds the image from `Dockerfile`, brings up
`postgres`/`redis`/`api`/`worker` as Swarm services, and — once you've set a
domain (§10) — Traefik starts routing to `api`. Watch the build+deploy log in
the UI; `api`'s container logs should settle on:

```
Uvicorn running on http://0.0.0.0:8000
```

## 9. Run the migration and seed

The schema migration and the seed script (3 sample jobs — Python backend,
React frontend, DevOps/SRE — plus the admin user) are one-shot commands, not
services, so they don't belong in `docker-compose.yml`. Run them against the
live `api` container from Dokploy's **Terminal** tab (or `docker exec` over
SSH if you prefer):

```bash
alembic upgrade head
python scripts/seed.py
```

`scripts/seed.py` is idempotent — re-running it after a redeploy skips
anything that already exists (admin by email, each area/persona by slug) and
prints what it skipped vs. created. It reads `SEED_ADMIN_EMAIL` /
`SEED_ADMIN_PASSWORD` from the environment you set in §7 — nothing about the
admin credential is hardcoded in the repo, so `admin@admin.com` /
`password123` (or whatever you choose) only ever exists in Dokploy's env
store and in whoever you hand it to.

## 10. Domain + TLS

In the compose service's **Domains** tab:

1. **Add Domain** → host `interviewer.evertontomalok.com.br` → service
   `api` → container port `8000`.
2. Enable **HTTPS** — Dokploy requests a Let's Encrypt cert via Traefik the
   first time the domain resolves to this VPS and answers the HTTP-01
   challenge. It won't succeed until the DNS record in §11 is live and
   propagated.

## 11. DNS — set this on the registrar

`evertontomalok.com.br` is a `.com.br`, so this is set at whoever you
registered it through (Registro.br, or a reseller). Add one record:

| Type | Host | Value | TTL |
|---|---|---|---|
| `A` | `interviewer` | `<vps-public-ip>` | 3600 (or provider default) |

That's `interviewer.evertontomalok.com.br` → the VPS's IPv4. If the
registrar's zone editor wants a full name instead of just the subdomain,
that's `interviewer.evertontomalok.com.br.` (trailing dot). No `CNAME`, no
`www` — one `A` record is the whole ask. Propagation is usually minutes,
occasionally up to a few hours; re-check the Domains tab in Dokploy once
`dig interviewer.evertontomalok.com.br` returns the VPS IP, and it'll issue
the cert on its own.

## 12. Verify

```bash
curl https://interviewer.evertontomalok.com.br/healthz
curl https://interviewer.evertontomalok.com.br/readyz   # checks Postgres + the workflow queue
```

Then open `https://interviewer.evertontomalok.com.br/jobs.html` in a
browser — the 3 seeded jobs should list, and clicking one should start an
interview with no login step.

## 13. Redeploying

Push to `master`, click **Deploy** in Dokploy (or wire up its Git-push
webhook so it deploys on push automatically). Swarm's rolling update means
`api` stays reachable through the swap; `worker` has a short gap while its
one replica restarts, which only delays in-flight turns, since `POST
/session/turns` is a `202`-and-queue, not synchronous. Migrations don't
auto-run on deploy — re-run §9's `alembic upgrade head` by hand whenever a
new migration lands.
