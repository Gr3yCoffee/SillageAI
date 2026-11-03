# Sillage AI — Master Development Specification

This document is the project specification. It incorporates the required OpenRouter and Proxmox architecture update. The original specification was not present in the workspace; the product areas retained here are My Collection, AI Stylist, Layering Studio, and Travel Planner.

## Product

Sillage AI is a private fragrance wardrobe and stylist. Users manage a collection with brand, notes, family, longevity, projection, and season; receive context-aware recommendations; explore locally ranked layering pairs; and prepare a travel scent edit. Feedback informs future ranking. Deterministic Python ranking considers weather, occasion, temperature, humidity, fragrance families and notes, performance, personal preferences, and past feedback. AI explains a short list selected locally; it does not do deterministic calculations that Python can perform reliably.

## OpenRouter

All cloud inference uses OpenRouter at `https://openrouter.ai/api/v1` through the OpenAI-compatible Chat Completions API. Only the backend communicates with OpenRouter. The Python backend uses the official OpenAI SDK, strict timeouts, no automatic paid-model retries, validated JSON output, and logged errors without credentials or prompt contents. Free is the default mode and `openrouter/free` is the default model. There is no implicit upgrade from a free model or automatic fallback to a costlier model. A configured fallback is retained as a preference only and is never invoked silently.

The model picker reads the live OpenRouter `/models` catalog and presents provider metadata (model ID/name, context window, architecture, and pricing). Structured output capability is model-specific; requests validate returned JSON and locally fall back to the deterministic result on unsupported output formats, malformed responses, rate limits, or provider errors. No repair loop runs. Recommendation prompts contain at most five candidates, and layering candidates are precomputed locally.

### Spending, usage, and credentials

Application defaults: free mode; `openrouter/free`; $2.50 total and monthly local budgets; 700 maximum output tokens; 30-second timeout; six-hour recommendation cache. Settings can choose a paid model and adjust local budgets, request ceiling, token limits, temperature, and caching. Before paid calls, the backend estimates input and maximum output charges from live model pricing, including known request-level charges. Unknown positive non-token units fail closed when they cannot be bounded from available request data. Estimates are explicitly estimates, not final bills. Provider-confirmed response cost is recorded when present; otherwise usage is marked unconfirmed. Estimates are reserved before the request and reconciled when usage returns; a process-local guard serializes reservation decisions. These safeguards reduce overspending risk but are not a financial guarantee. Use a dedicated OpenRouter key with its own provider-side spending limit.

An API key may be supplied via environment or Settings. Settings keys are encrypted with Fernet authenticated encryption using a URL-safe base64 32-byte `CREDENTIAL_ENCRYPTION_KEY`; the environment key takes precedence. Never commit real credentials. Usage records include feature, model, token counts, estimate, reported cost where available, cache status, and timestamp. The dashboard summarizes daily/monthly/all-time requests, model and feature breakdown, cache hit rate, token usage, estimated and provider-confirmed cost, remaining local budget, and an 80% warning. Paid calls are blocked when total or monthly local limits would be exceeded; deterministic suggestions remain available.

Required environment variables:

```env
AI_PROVIDER=openrouter
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=openrouter/free
OPENROUTER_FALLBACK_MODEL=
AI_MODE=free
AI_TOTAL_BUDGET_USD=2.50
AI_MONTHLY_BUDGET_USD=2.50
AI_MAX_OUTPUT_TOKENS=700
CREDENTIAL_ENCRYPTION_KEY=
```

Additional deployment variables are documented in `.env.example`.

### Cache

PostgreSQL stores response cache entries and usage. Keys cover user, collection revision and eligible collection data, preference revision/data, occasion and contextual parameters, location, model, and feature. A six-hour default TTL enables reuse; changed context, collection, preferences, or model changes the key. The client does not regenerate recommendations on reload by itself. Saved travel results should remain reusable until explicit refresh or material context change; this is represented by the shared cache mechanism and can be extended to a persistent saved-trip record.

## Settings and safety

Settings provide OpenRouter credential entry, Free/Economy/Smart mode, preferred and optional fallback model, live model catalog pricing/context/free status, request/output token caps, temperature, monthly and total local budget, per-request ceiling, cache toggle, and usage dashboard. Catalog availability and JSON-schema/structured-output capability must be checked from provider metadata; clients must not assume identical support across models. The backend applies strict input/output schemas, checks IDs against the user's collection, escapes user data as data, instructs the model to ignore embedded prompt instructions, validates JSON, and falls back locally on errors. Rate limits apply at the API. CORS is restricted to configured frontend origin.

Authentication is required for collection, preferences, settings, usage, model catalog, and recommendation operations. Passwords use Argon2. Session cookies are HttpOnly, SameSite=Lax, and can be marked Secure with `COOKIE_SECURE=true`; unsafe requests require a CSRF token and same-origin validation. The API is served same-origin through Caddy and does not enable cross-origin browser access. User ownership is checked for collection mutations and feedback. Secrets and internal provider errors are not returned to users. Local HTTP is appropriate only on a trusted LAN and does not encrypt traffic; remote use should use HTTPS through a trusted private-access service such as Tailscale. Avoid public port forwarding.

## Deployment architecture

Run the app inside a Linux VM on a Proxmox VE node, never on the Proxmox host. Initial target: Debian 13, 2 vCPU, 4 GB RAM, 30 GB disk, bridged network, Docker Engine, and Docker Compose. These are starting resources, not guaranteed minimums. No GPU or local LLM is required. Backend image uses a multi-stage build and runs as a non-root account. Services are `frontend`, `backend`, `postgres`, and `caddy`; no Redis, Celery, or Ollama. PostgreSQL and backend have no published ports and stay on an internal Compose network. PostgreSQL and app uploads use persistent volumes. Health checks, restart policies, and bounded container logs are configured.

Start with `docker compose up -d --build`. Backend migrations run before the API starts; schema migrations are safe to rerun. Defaults serve on port 8080 through Caddy for LAN access. There is no requirement for a public domain or public IP. For private remote access, use Tailscale or another VPN; no port forwarding is needed. Optional public-domain Caddy TLS requires a publicly resolvable domain and reachable validation ports. Caddy cannot obtain public certificates for private IP addresses; use private-access HTTPS instead.

## Acceptance criteria

1. Cloud inference uses OpenRouter, never direct OpenAI service endpoints.
2. A valid key can be configured by environment or Settings and remains backend-only.
3. Free model is the default; paid models are user-selectable and never silently selected.
4. Model choices and prices come from the live OpenRouter model catalog.
5. Usage, estimates, reported charges, and feature/model breakdown are visible.
6. Local total/monthly/per-request guards reserve in-flight estimates and block over-budget paid requests.
7. Deterministic recommendations work without key, credits, or provider availability.
8. Eligible results cache and duplicate concurrent requests coalesce.
9. My Collection, AI Stylist, Layering Studio, and Travel Planner remain available.
10. Compose runs the complete application in the specified Proxmox VM without GPU or public cloud infrastructure.
11. PostgreSQL and backend are not directly exposed; backups and recovery are documented.
