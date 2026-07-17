# Customer UI — serves a locally prebuilt bundle (frontend-customer/prebuilt).
# Railway's builder dies (likely OOM) on this app's vite build, so the bundle
# is built on the framework machine and only static files ship. Rebuild with:
#   docker build -f Dockerfile.customer --build-arg VITE_API_BASE_URL=<api url> -t recon-cust .
#   docker create --name x recon-cust && docker cp x:/srv/. frontend-customer/prebuilt && docker rm x
FROM caddy:2-alpine

COPY frontend-customer/Caddyfile /etc/caddy/Caddyfile
COPY frontend-customer/prebuilt /srv
