#!/usr/bin/env bash
# Prepara uma instância do zero: venv + dados geográficos. Idempotente.
set -euo pipefail
cd "$(dirname "$0")"
[ -d venv ] || python3 -m venv venv
venv/bin/pip install -q -r requirements.txt
# Dados geográficos: o build leva ~1h30 e precisa de ~8 GB de RAM e do tippecanoe
# (veja o README). Se já tiver os arquivos prontos, copie-os para geodata/.
for f in geo.db world.pmtiles localities localities_large.parquet land.parquet; do
  if [ ! -e "geodata/$f" ]; then
    venv/bin/python scripts/build_geodata.py
    break
  fi
done
mkdir -p data
echo "ok — rode: venv/bin/gunicorn -b 0.0.0.0:5020 app:app"
