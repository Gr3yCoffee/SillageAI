FROM python:3.12-slim AS build
WORKDIR /build
COPY requirements*.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --system --uid 10002 --create-home catalog && mkdir -p /app/data && chown -R catalog:catalog /app
WORKDIR /app
COPY --from=build /install /usr/local
COPY --chown=catalog:catalog api ./api
COPY --chown=catalog:catalog scraper ./scraper
COPY --chown=catalog:catalog utils ./utils
COPY --chown=catalog:catalog data ./data
COPY --chown=catalog:catalog assets ./assets
USER catalog
EXPOSE 9000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "9000", "--workers", "1"]
