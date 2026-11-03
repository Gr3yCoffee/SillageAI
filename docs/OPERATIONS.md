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

PerfumAPI runs as a private Compose service and stores its catalog in the existing PostgreSQL database. It has no published host port; the authenticated SillageAI backend proxies search requests from the Add fragrance form. The catalog starts empty, so lookup suggestions appear as entries are added to the catalog. Lookup failure leaves manual entry available. Search responses are cached in the backend for five minutes.

Set a separate random `PERFUMAPI_ADMIN_TOKEN` in `.env` before starting the stack. The catalog ingestion routes require this token and are not exposed on the host. The upstream scraper targets Fragrantica and may be slow or unavailable. Its README says it is for educational/personal use and requires users to respect the source site's robots.txt and terms. Do not run bulk scraping by default; see `perfumapi/UPSTREAM.md` for provenance and local changes.
