# Upstream attribution and local changes

PerfumAPI source is based on [seccaz/PerfumAPI](https://github.com/seccaz/PerfumAPI), upstream revision `eb27aa047cf962ea36d5ec1b1ed46d62dc124b07`, distributed under the MIT License (see `LICENSE`). The FastAPI routes and Fragrantica scraper are vendored from that revision.

SillageAI changes the storage adapter to use the existing internal PostgreSQL service, replaces Supabase authentication for ingestion endpoints with a private bearer token, and runs the API on the internal Compose network. The SillageAI backend proxies authenticated catalog searches. No credentials or external ports are needed for catalog reads.

The upstream README describes scraping as educational/personal use and says users are responsible for respecting the source site's robots.txt and terms. The catalog starts empty. Scraping endpoints are protected; populate selectively and only when permitted. Catalog lookup does not trigger scraping automatically.
