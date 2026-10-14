# Customer UI — serves a locally prebuilt bundle (frontend-customer/prebuilt).
# Railway's builder dies (likely OOM) on this app's vite build, so the bundle
# is built on the framework machine and only static files ship. Rebuild with:
#   docker build -f Dockerfile.customer --build-arg VITE_API_BASE_URL=<api url> -t recon-cust .
#   docker create --name recon-cust-extract recon-cust && docker cp recon-cust-extract:/srv/. frontend-customer/prebuilt && docker rm recon-cust-extract
FROM caddy:2-alpine

COPY frontend-customer/Caddyfile /etc/caddy/Caddyfile
COPY frontend-customer/prebuilt /srv
