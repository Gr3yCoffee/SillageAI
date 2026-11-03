# Upstream attribution and local changes

PerfumAPI source is based on [seccaz/PerfumAPI](https://github.com/seccaz/PerfumAPI), upstream revision `eb27aa047cf962ea36d5ec1b1ed46d62dc124b07`, distributed under the MIT License (see `LICENSE`). The FastAPI routes and scraper are vendored from that revision.

SillageAI changes the storage adapter to use the existing internal PostgreSQL service, replaces Supabase authentication for ingestion endpoints with a private bearer token, and runs the API on the internal Compose network. The SillageAI backend proxies authenticated catalog searches. No credentials or external ports are needed for catalog reads.

The catalog is seeded at startup from the bundled Scento dataset in `assets/perfumes.csv` (1,473 distinct fragrances from 1,479 rows), licensed CC BY 4.0. Required attribution: **Scento — [Scento Perfume Database](https://www.scento.com/perfume-database)**; see `assets/ATTRIBUTION.md`.

PerfumAPI's original Fragrantica scraping routes are disabled by default (`PERFUMAPI_SCRAPING_ENABLED=false`). Fragrantica's [current terms](https://www.fragrantica.com/terms-of-service.phtml) prohibit automated scraping unless it gives written authorization. Do not enable those routes without that authorization. PerfumAPI itself is MIT-licensed, but that license does not grant rights to third-party fragrance data.
