# Running Recon.AI

Recon.AI runs as a Docker Compose stack on a self-hosted machine, reachable only on a private network
(tailnet). It was hosted on Azure, then Railway; Railway was retired in 2026-11.

The stack definition lives outside this repo, in `~/demos/recon/compose.yaml`, with secrets in
`~/demos/recon/.env` (`OPENAI_API_KEY`). It builds two images from this repo:

| Service | Dockerfile | Notes |
| --- | --- | --- |
| `api` | `Dockerfile` | FastAPI/uvicorn on `$PORT`. `ALLOWED_ORIGINS` = the UI's origin. `OPENAI_MODEL` defaults to `gpt-5.6-luna`. |
| `customer` | `Dockerfile.customer` | Node build, then Caddy serves the static bundle on `$PORT`. `VITE_API_BASE_URL` is a build arg: changing it needs a rebuild. |

```bash
cd ~/demos/recon && docker compose up -d --build
```

Notes:

- gpt-5.6 models reject `temperature`/`max_tokens`; `src/llm/openai_client.py` sends `max_completion_tokens` only.
  Without `OPENAI_API_KEY` every AI step degrades silently and column mapping returns all `ignore`, which then
  fails confirm-columns with a 422.
- Reconciliation state is in memory: sessions don't survive an api restart.
- `ALLOWED_ORIGINS` unset means `*` (local dev behavior).
- `customer-ui.Dockerfile` and `frontend-customer/prebuilt/` were a Railway workaround (its builder ran out of
  memory on the Vite build) and are no longer used.
