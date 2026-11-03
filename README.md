# Sillage AI

Self-hosted fragrance collection and recommendation app. The stack is designed for a Debian 13 VM on Proxmox VE and uses Docker Compose.

## Start

1. Copy `.env.example` to `.env` and set strong values for `POSTGRES_PASSWORD`, `SESSION_SECRET`, and `CREDENTIAL_ENCRYPTION_KEY` (32 bytes, URL-safe base64). Add an OpenRouter key in Settings or set `OPENROUTER_API_KEY`.
2. Run `docker compose up -d --build`.
3. Open `http://<VM-LAN-IP>:8080`. Create the initial account. The first account created is the administrator.

The frontend is served by Caddy. PostgreSQL and backend ports are private to the Compose network. HTTP on a trusted LAN is convenient but does not encrypt credentials or session traffic; use Tailscale Serve, another trusted VPN HTTPS feature, or the optional Caddy domain configuration for remote access. Do not expose port 8080 to the public Internet.

See [docs/MASTER_SPEC.md](docs/MASTER_SPEC.md) for the product/architecture specification and [docs/OPERATIONS.md](docs/OPERATIONS.md) for backup, restore, upgrades, Proxmox, and networking.

## AI spending

Defaults select `openrouter/free`; this never silently falls through to a paid model. Configure paid models and policies explicitly in Settings. Local budget controls are best-effort safeguards, not a financial guarantee. Create a dedicated OpenRouter API key with its own provider-side spending limit.
