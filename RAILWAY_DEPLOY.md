# Deploying Recon.AI on Railway

Three services from this one repo (monorepo pattern — each service gets a
different **root directory**):

| Service        | Root directory      | Serves                        |
| -------------- | ------------------- | ----------------------------- |
| `api`          | `/` (repo root)     | FastAPI backend (uvicorn)     |
| `admin-ui`     | `/frontend`         | Admin React app (Caddy)       |
| `customer-ui`  | `/frontend-customer`| Customer React app (Caddy)    |

Each root directory contains its own `Dockerfile` and `railway.json`, so
Railway picks up build + deploy settings automatically.

## One-time setup

1. **Create a project** on railway.com → *Deploy from GitHub repo* →
   `nolatl/recon.ai`. The first service it creates becomes `api`
   (root directory `/`).
2. **Add the two frontend services**: in the project canvas, *New →
   GitHub repo* → same repo. In each new service's *Settings → Source*,
   set **Root Directory** to `/frontend` and `/frontend-customer`
   respectively.
3. **Generate public domains**: each service → *Settings → Networking →
   Generate Domain*. Do the `api` service first — the frontends need its URL
   at build time.

## Environment variables

### `api`
| Variable          | Value                                                              |
| ----------------- | ------------------------------------------------------------------ |
| `OPENAI_API_KEY`  | your key (required — AI advisory layer)                            |
| `ALLOWED_ORIGINS` | `https://<admin-ui-domain>,https://<customer-ui-domain>` (comma-separated, no spaces needed) |

Using Railway references keeps this in sync automatically:
`ALLOWED_ORIGINS = https://${{admin-ui.RAILWAY_PUBLIC_DOMAIN}},https://${{customer-ui.RAILWAY_PUBLIC_DOMAIN}}`

### `admin-ui` and `customer-ui`
| Variable            | Value                                        |
| ------------------- | -------------------------------------------- |
| `VITE_API_BASE_URL` | `https://${{api.RAILWAY_PUBLIC_DOMAIN}}`     |

This is a **build-time** variable (Vite bakes it into the bundle). The
frontend Dockerfiles declare it as `ARG`, which Railway populates from
service variables. Changing it requires a redeploy of the frontend.

## Notes / gotchas

- **Ports**: all three containers listen on Railway's injected `$PORT`
  (uvicorn via shell-form CMD; Caddy via `{$PORT:80}` in the Caddyfile).
  No manual port configuration needed.
- **Health check**: the `api` service health-checks `/health` (configured in
  root `railway.json`).
- **State is in-memory**: reconciliation sessions do not survive an API
  redeploy/restart. Fine for a POC; a Railway Postgres/volume is the upgrade
  path if persistence is ever needed.
- **CORS**: with `ALLOWED_ORIGINS` unset the API allows `*` (local dev
  behavior). Set it in production.
- **The Streamlit app** (`app/streamlit_app.py`) is legacy and not deployed.

## Local smoke test

```bash
docker build -t recon-api . && docker run -e PORT=8000 -p 8000:8000 recon-api
docker build -t recon-admin --build-arg VITE_API_BASE_URL=http://localhost:8000 frontend/
docker build -t recon-customer --build-arg VITE_API_BASE_URL=http://localhost:8000 frontend-customer/
```
