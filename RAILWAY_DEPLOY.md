# Deploying Recon.AI on Railway

Project **recon-ai** (id `4ee2cbc3-aec6-442e-ba30-de1849a05ec6`), three services,
deployed **via the Railway CLI from this repo** (`railway up`) — no GitHub
integration (the Railway GitHub App isn't authorized for this private repo).

| Service       | URL                                              | Image source                              |
| ------------- | ------------------------------------------------ | ----------------------------------------- |
| `api`         | https://api-production-e6f0.up.railway.app       | `Dockerfile` (FastAPI/uvicorn)            |
| `admin-ui`    | https://admin-ui-production-bf2e.up.railway.app  | `Dockerfile.admin` (Node build → Caddy)   |
| `customer-ui` | https://customer-ui-production-c15b.up.railway.app | `customer-ui.Dockerfile` (prebuilt → Caddy) |

Each service selects its Dockerfile via the `RAILWAY_DOCKERFILE_PATH` service
variable (all builds use the repo root as context). The root `railway.json`
intentionally does **not** set `dockerfilePath` — a value there overrides the
per-service variable for every service.

## Deploying

```bash
cd ~/projects/recon.ai          # the CLI resolves project link from the cwd
railway up -s api -d
railway up -s admin-ui -d
railway up -s customer-ui -d
```

Never pass a path argument to `railway up` (broken in CLI 5.26, "prefix not
found") and always run from the repo root — from anywhere else the CLI will
link/create a different project.

## customer-ui: prebuilt bundle

Railway's builder dies with no logs (likely OOM) on `frontend-customer`'s
`tsc && vite build`. The bundle is therefore built locally and only static
files ship (`customer-ui.Dockerfile` copies `frontend-customer/prebuilt/`).
To rebuild after frontend changes or an API URL change:

```bash
docker build -f Dockerfile.customer \
  --build-arg VITE_API_BASE_URL=https://api-production-e6f0.up.railway.app \
  -t recon-cust .
rm -rf frontend-customer/prebuilt
docker create --name x recon-cust && docker cp x:/srv/. frontend-customer/prebuilt && docker rm x
railway up -s customer-ui -d
```

`frontend-customer/prebuilt/` stays untracked in git but **must not** be
gitignored — `railway up` honors .gitignore when uploading.

## Environment variables (already set)

- `api`: `ALLOWED_ORIGINS` = both frontend URLs (comma-separated).
  `OPENAI_API_KEY` = **must be set manually** (dashboard → api → Variables).
- `admin-ui`/`customer-ui`: `VITE_API_BASE_URL` = api URL (build-time; a
  change requires redeploy/rebuild), `RAILWAY_DOCKERFILE_PATH` as above.

## Notes

- All containers listen on Railway's injected `$PORT` (uvicorn shell-form CMD;
  Caddy `{$PORT:80}`). Public domains target port 8080 for the frontends.
- `api` health-checks `/health` (root `railway.json`).
- Reconciliation state is **in-memory** — sessions don't survive an api
  redeploy. Upgrade path: Railway Postgres or a volume.
- CORS: `ALLOWED_ORIGINS` unset ⇒ `*` (local dev behavior).
- The Streamlit app (`app/streamlit_app.py`) is legacy and not deployed.

## Local smoke test

```bash
docker build -t recon-api . && docker run -e PORT=8000 -p 8000:8000 recon-api
docker build -f Dockerfile.admin --build-arg VITE_API_BASE_URL=http://localhost:8000 -t recon-admin .
docker build -f customer-ui.Dockerfile -t recon-customer .
```
