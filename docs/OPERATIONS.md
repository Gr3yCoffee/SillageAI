# Operations: Proxmox, deployment, and recovery

## Proxmox VM

Create a Debian 13 Linux VM on the Proxmox VE node. Start with 2 vCPUs, 4 GB RAM, and a 30 GB virtual disk, then monitor usage and resize if needed. Use bridged networking for LAN access. Install Docker Engine and the Docker Compose plugin inside the VM. Do not install or run this stack on the Proxmox host.

Copy the project into the VM, copy `.env.example` to `.env`, and create unique secrets. Generate an encryption key with `python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())'`. Set `POSTGRES_PASSWORD`, `SESSION_SECRET`, and `CREDENTIAL_ENCRYPTION_KEY`; keep `.env` private and backed up. Add an OpenRouter API key in app Settings or the VM environment. We recommend a dedicated OpenRouter key with a provider-side spending cap.

Start or upgrade with:

```sh
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 backend caddy
```

All containers use `restart: unless-stopped`. PostgreSQL health gates backend startup; migrations run before the API process. Check `/health` through Caddy after deployment. The default LAN endpoint is `http://VM-LAN-IP:8080`. Keep port 8080 restricted to trusted LAN devices using the VM firewall. Local HTTP does not encrypt passwords, session cookies, or API traffic. Set `COOKIE_SECURE=true` when the browser-facing endpoint is HTTPS.

## Private remote access and HTTPS

For remote use, connect the VM and client devices to Tailscale or another private VPN. Keep service access private and avoid router port forwarding. Use the VPN's trusted HTTPS feature (for example, Tailscale Serve) where available. Alternatively, configure `SITE_ADDRESS` to a public domain you control and set `HTTP_PORT=80` and `HTTPS_PORT=443`, then route public DNS and certificate-validation traffic to Caddy; this is optional. Public ACME certificate issuance does not work for a private IP address alone. Restrict Caddy and host firewall exposure to the access method you select.

## Existing Nginx HTTPS reverse proxy

When Nginx terminates HTTPS and forwards to this stack's Caddy port, set `PUBLIC_BASE_URL` in `.env` to the exact browser origin, for example `https://sillage.example.com`. This makes CSRF origin checks compare against the public HTTPS origin even though the internal Nginx-to-Caddy hop uses HTTP. Session cookies automatically use the `Secure` flag for an HTTPS `PUBLIC_BASE_URL`. Keep `VITE_API_BASE_URL=/api` for a root-mounted, same-origin app; the browser calls `https://sillage.example.com/api/...` and Nginx forwards it with the rest of the request.

Example Nginx location (replace the upstream address with the SillageAI VM):

```nginx
location / {
    proxy_pass http://172.16.20.3:8080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Port $server_port;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Rebuild the frontend after changing `VITE_API_BASE_URL`, because Vite embeds it into the static bundle. For a non-root URL prefix, set it to the matching same-origin API path (for example `/sillage/api`) and configure Nginx to preserve or rewrite that prefix consistently. Avoid using a separate cross-origin API host unless CORS and cookie policy are deliberately configured for it.

## PostgreSQL backup and restore

Take a logical database backup before upgrades and regularly on a schedule. The PostgreSQL service has no published host port, so execute `pg_dump` inside its container:

```sh
mkdir -p backups
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/sillage-$(date +%F-%H%M).sql
```

Stop writes or use a consistent dump for restore. Restore into an empty database:

```sh
cat backups/sillage-YYYY-MM-DD-HHMM.sql | docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" "$POSTGRES_DB"'
```

Back up uploaded perfume images from the `app_data` volume. One simple offline copy is:

```sh
docker compose stop backend
docker run --rm -v sillageai_app_data:/data -v "$PWD/backups:/backup" alpine tar czf /backup/app-data-$(date +%F).tgz -C /data .
docker compose start backend
```

Use the actual Compose project volume name if it differs. Also preserve `.env`, especially `CREDENTIAL_ENCRYPTION_KEY`; losing that key makes Settings-stored provider credentials unrecoverable. Store backups encrypted and off the VM.

## Updates and VM recovery

Before an update, take a PostgreSQL dump and app-data copy. Pull or copy the reviewed application release, then run `docker compose up -d --build`; inspect health and logs. Keep a rollback copy of the previous release and compatible database backup. For VM failure, provision a replacement Debian VM, install Docker, restore project and `.env`, create the named volumes, restore PostgreSQL and app data, then start the stack and verify login, collection images, and health.

Proxmox VM snapshots and scheduled VM backups are useful optional infrastructure protection. A snapshot while services are running is not a substitute for a database-consistent backup: use PostgreSQL logical backups (and quiesce writes where practical), particularly before database upgrades.

## PerfumAPI fragrance catalog

PerfumAPI runs as a private Compose service and stores its catalog in the existing PostgreSQL database. It has no published host port; the authenticated SillageAI backend proxies search requests from the Add fragrance form. Its database is seeded from the bundled Scento dataset. Current fragrance search uses Fragella; the PerfumAPI service remains internal for catalog storage and its original scraper routes remain disabled.

Set a separate random `PERFUMAPI_ADMIN_TOKEN` in `.env` before starting the stack. The catalog ingestion routes require this token and are not exposed on the host. The bundled Scento dataset contains 1,473 distinct fragrances from 1,479 CC BY 4.0 rows; see `perfumapi/assets/ATTRIBUTION.md` for required credit. Longevity and projection are not included, so Sillage uses its neutral defaults. PerfumAPI's Fragrantica scraping routes stay disabled unless `PERFUMAPI_SCRAPING_ENABLED=true`; Fragrantica's terms require written authorization for automated scraping. See `perfumapi/UPSTREAM.md` for details.

## Fragella fragrance lookup

Add the Fragella API key to the server's ignored `.env` file as `FRAGELLA_API_KEY`. The backend keeps this credential server-side. In My Collection, catalog requests run only when the user presses **Search Fragella**; typing does not consume requests. The backend enforces a conservative 20-request rolling 30-day cap and reuses results in memory for one hour. Searches matching fragrances already saved to that user's collection are served locally.

When a user adds a Fragella result, Sillage stores its selected name, house, note list, accord family, available season and occasion metadata, and performance labels in PostgreSQL. If Fragella supplies a bottle image, the backend downloads it from Fragella's CDN to the persistent `app_data` volume and serves it through the authenticated collection image route. Failed image downloads do not block saving the fragrance; the user can upload a photo instead. Missing longevity or projection stays unknown rather than being shown as a default 3/5. Catalog entries are user-selected rather than bulk imported; Fragella's terms restrict caching large portions of its API dataset.
