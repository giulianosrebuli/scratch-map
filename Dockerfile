# Scratch Map em container. Sobe sem os dados do mapa: na primeira execução o
# assistente (/setup) pergunta o básico e monta os dados aqui dentro, a partir
# das fontes abertas (installer.py, scripts/build_geodata.py).
#   docker compose up -d     → http://<máquina>:5020
# Volumes: /data (seus dados: banco, fotos, backups) e /geodata (dados do mapa).

# ---- tippecanoe (gera o world.pmtiles na montagem)
FROM debian:bookworm-slim AS tippecanoe
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates git libsqlite3-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch 2.79.0 https://github.com/felt/tippecanoe /src \
    && make -C /src -j"$(nproc)" tippecanoe

# ---- app
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libsqlite3-0 zlib1g tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=tippecanoe /src/tippecanoe /usr/local/bin/tippecanoe

RUN useradd --create-home --uid 1000 scratch \
    && mkdir -p /data /geodata && chown scratch:scratch /data /geodata
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

USER scratch
# extensões do DuckDB que a montagem usa (para não baixar na hora)
RUN python -c "import duckdb; duckdb.sql('INSTALL spatial; INSTALL httpfs')"
COPY --chown=scratch:scratch . .

ENV SCRATCH_DATA=/data SCRATCH_GEODATA=/geodata PYTHONUNBUFFERED=1
VOLUME ["/data", "/geodata"]
EXPOSE 5020
# "/" responde 200 (ou leva ao /setup, que também responde) quando o gunicorn está de pé
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5020/', timeout=8)"]
ENTRYPOINT ["tini", "--"]
CMD ["gunicorn", "--bind", "0.0.0.0:5020", "--workers", "1", "--threads", "4", "--timeout", "180", "app:app"]
