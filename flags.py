"""Bandeiras de estados/províncias, baixadas em segundo plano do Wikidata.

As de país vêm prontas (static/vendor/flags, flag-icons). As de estado não têm
um pacote aberto equivalente, então, quando um país passa a ser visitado,
pedimos ao Wikidata as bandeiras dos estados dele (ligando pelo código ISO
3166-2, o mesmo id que o app usa, ex. BR-SP) e guardamos uma miniatura de cada
em flags/<ID>.webp (na pasta do perfil). Cada país é buscado uma vez (tabela
state_flags_fetched); se a rede falhar, tenta de novo da próxima vez.

Sai da máquina: o código do país (na consulta ao Wikidata) e os nomes dos
arquivos das bandeiras (no download do Commons). Nada de visitas ou fotos.
Estado sem bandeira no Wikidata (ou país que não usa) fica com a sigla.
"""
import io
import logging
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

log = logging.getLogger("scratch-map.flags")

SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = "scratch-map/0.1 (self-hosted personal app)"
THUMB_W = 160   # px de largura da miniatura (o círculo tem 62-76 px; 2x para telas retina)

SCHEMA = """
-- países cujas bandeiras de estado já foram buscadas no Wikidata
CREATE TABLE IF NOT EXISTS state_flags_fetched (
    country_id TEXT PRIMARY KEY,
    found INTEGER NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_lock = threading.Lock()
_running = set()


def _get(url, accept=None, tries=4):
    """GET; com 429 (limite de requisições) espera o que o servidor pedir e tenta
    de novo. O Wikidata às vezes limita a 1 consulta por minuto."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == tries - 1:
                raise
            wait = int(e.headers.get("Retry-After") or 0) or 65
            log.info("limite de requisições, esperando %ss", wait)
            time.sleep(min(wait, 300))


def _query(country):
    """{código ISO 3166-2: URL da bandeira no Commons} dos estados do país."""
    import json
    q = f'SELECT ?code ?flag WHERE {{ ?s wdt:P300 ?code; wdt:P41 ?flag. FILTER(STRSTARTS(?code, "{country}-")) }}'
    data = json.loads(_get(f"{SPARQL}?{urllib.parse.urlencode({'query': q})}", "application/sparql-results+json"))
    out = {}
    for b in data["results"]["bindings"]:
        out.setdefault(b["code"]["value"], b["flag"]["value"])  # mais de uma (histórica): fica a primeira
    return out


def _fetch_country(db_path, geo_db, flag_dir, country):
    with sqlite3.connect(geo_db) as geo:
        ids = {r[0] for r in geo.execute("SELECT id FROM states WHERE country_id = ?", (country,))}
    found = 0
    for code, url in sorted(_query(country).items()):
        if code not in ids:
            continue
        dest = flag_dir / f"{code}.webp"
        if dest.exists():
            found += 1
            continue
        # Special:FilePath com width devolve o PNG já renderizado (SVG → PNG) pelo Commons
        png = _get(f"{url}?width={THUMB_W}")
        with Image.open(io.BytesIO(png)) as img:
            img.convert("RGBA").save(dest, "WEBP", quality=88)
        found += 1
        time.sleep(0.3)  # gentileza com o Commons
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT OR REPLACE INTO state_flags_fetched (country_id, found) VALUES (?, ?)", (country, found))
    log.info("bandeiras de estado de %s: %d", country, found)


def ensure(db_path, geo_db, flag_dir: Path, countries):
    """Busca em segundo plano as bandeiras dos estados dos países ainda não buscados."""
    with sqlite3.connect(db_path) as con:
        done = {r[0] for r in con.execute("SELECT country_id FROM state_flags_fetched")}
    with _lock:
        todo = [c for c in countries if c and c not in done and (str(db_path), c) not in _running]
        _running.update((str(db_path), c) for c in todo)
    if not todo:
        return

    def run():
        flag_dir.mkdir(parents=True, exist_ok=True)
        for c in todo:
            try:
                _fetch_country(db_path, geo_db, flag_dir, c)
            except Exception as e:  # sem rede etc.: tenta de novo da próxima vez
                log.warning("bandeiras de estado de %s falharam: %s", c, e)
            finally:
                with _lock:
                    _running.discard((str(db_path), c))

    threading.Thread(target=run, name="state-flags", daemon=True).start()
