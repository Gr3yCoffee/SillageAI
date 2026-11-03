# Upstream attribution and local changes

PerfumAPI source is based on [seccaz/PerfumAPI](https://github.com/seccaz/PerfumAPI), upstream revision `eb27aa047cf962ea36d5ec1b1ed46d62dc124b07`, distributed under the MIT License (see `LICENSE`). The FastAPI routes and scraper are vendored from that revision.

SillageAI changes the storage adapter to use the existing internal PostgreSQL service, replaces Supabase authentication for ingestion endpoints with a private bearer token, and runs the API on the internal Compose network. The SillageAI backend proxies authenticated catalog searches. No credentials or external ports are needed for catalog reads.

The catalog starts empty. Fragrantica's [current terms](https://www.fragrantica.com/terms-of-service.phtml) prohibit scraping, crawling, harvesting, and automated collection unless Fragrantica gives written authorization. Consequently, scraping routes are disabled by default (`PERFUMAPI_SCRAPING_ENABLED=false`) and must stay disabled without that written authorization. PerfumAPI itself is MIT-licensed, but that license does not grant rights to third-party fragrance data. Populate the catalog only with data you have permission to use.
