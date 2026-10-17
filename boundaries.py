"""Limites (polígonos) das cidades e sugestão de nome de landmark.

O GeoNames só tem o ponto central da cidade. Quando uma cidade é marcada,
calculamos o contorno uma única vez a partir dos dados locais do Overture
(geoshapes.py, nada sai da máquina) e guardamos no scratch.db do perfil (tabela
city_shapes).

O Nominatim (OpenStreetMap) é usado em dois casos:
- sugerir o nome de um landmark: sai a coordenada dele;
- exceção: cidade cuja única área no Overture é igual ao estado (erro do dado,
  ex.: Brasília = DF inteiro). Aí o contorno é pedido uma vez ao Nominatim:
  saem o nome da cidade, o país e as coordenadas. No modo leve (instalação sem
  as áreas de cidade do Overture) é assim para toda cidade marcada.
Política do Nominatim: no máximo 1 requisição/s e User-Agent identificável.
https://operations.osmfoundation.org/policies/nominatim/
"""
import json
import logging
import sqlite3
import threading
import time
import urllib.parse
import urllib.request

from shapely.geometry import Point, shape

import geoshapes

log = logging.getLogger("scratch-map.boundaries")

NOMINATIM = "https://nominatim.openstreetmap.org"
USER_AGENT = "scratch-map/0.1 (self-hosted personal app)"

_lock = threading.Lock()    # serializa chamadas (limite de 1 req/s)
_last_call = [0.0]

SCHEMA = """
CREATE TABLE IF NOT EXISTS city_shapes (
    city_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,        -- ok | none (sem área de cidade) | error (tentar de novo)
    geometry TEXT,               -- GeoJSON geometry (Polygon/MultiPolygon)
    osm_name TEXT,               -- nome da área usada
    method TEXT,                 -- overture:<division_id> | nominatim:search | nominatim:reverse
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _get(path, params):
    with _lock:
        wait = 1.1 - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        url = f"{NOMINATIM}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt,en"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        finally:
            _last_call[0] = time.time()


MAX_SPAN_DEG = 3.0   # resultado da busca por nome maior que isso é região, não cidade
CITY_TYPES = {"city", "town", "village", "municipality", "hamlet", "suburb", "city_district"}


def nominatim_boundary(name, country, lat, lon):
    """(geometria GeoJSON, origem, nome) do contorno da cidade no OSM, ou None.
    1) busca por nome (pega o município inteiro); 2) reverso no ponto (zoom 10)."""
    common = {"format": "geojson", "polygon_geojson": 1, "polygon_threshold": 0.00001}
    pt = Point(lon, lat)
    res = _get("search", {**common, "city": name, "countrycodes": (country or "").lower(), "limit": 5})
    for f in res.get("features", []):
        p, bbox = f["properties"], f.get("bbox") or [0, 0, 999, 999]
        if f.get("geometry", {}).get("type") not in ("Polygon", "MultiPolygon"):
            continue
        if p.get("addresstype") not in CITY_TYPES or not 10 <= (p.get("place_rank") or 0) <= 16:
            continue
        if max(bbox[2] - bbox[0], bbox[3] - bbox[1]) > MAX_SPAN_DEG:
            continue
        if not shape(f["geometry"]).buffer(0.05).contains(pt):
            continue
        return f["geometry"], "nominatim:search", p.get("name")
    res = _get("reverse", {**common, "lat": lat, "lon": lon, "zoom": 10})
    for f in res.get("features", []):
        if f.get("geometry", {}).get("type") in ("Polygon", "MultiPolygon"):
            return f["geometry"], "nominatim:reverse", f["properties"].get("name")
    return None


def poi_name(lat, lon):
    """Nome do ponto turístico/estabelecimento mais próximo (sugestão p/ landmark)."""
    res = _get("reverse", {"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18})
    return res.get("name") or None


def _nominatim_off():
    # status 'error' (e não 'none'): tenta de novo quando o Nominatim for religado
    raise RuntimeError("Nominatim desligado na configuração")


def fetch_and_store(db_path, geo_db_path, city_id, allow_nominatim=True):
    """Busca e grava o limite de uma cidade. Seguro para chamar várias vezes.
    allow_nominatim=False: sem o pedido de exceção ao Nominatim (configuração)."""
    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        row = con.execute("SELECT status FROM city_shapes WHERE city_id = ?", (int(city_id),)).fetchone()
        if row and row[0] in ("ok", "none"):
            return row[0]
        geo = sqlite3.connect(f"file:{geo_db_path}?mode=ro", uri=True)
        city = geo.execute("""SELECT c.name, c.lat, c.lon, s.x0, s.y0, s.x1, s.y1, c.country_id FROM cities c
                              LEFT JOIN states s ON s.id = c.state_id WHERE c.id = ?""", (int(city_id),)).fetchone()
        geo.close()
        if city is None:
            return None
        try:
            name, lat, lon = city[:3]
            state_bbox = city[3:7] if city[3] is not None else None
            fallback = (lambda: nominatim_boundary(name, city[7], lat, lon)) if allow_nominatim else _nominatim_off
            found = geoshapes.city_shape(name, lat, lon, state_bbox, fallback=fallback)
        except Exception as e:  # arquivo faltando, rede fora etc. — tenta de novo depois
            log.warning("limite de %s (%s): %s", city[0], city_id, e)
            con.execute("INSERT OR REPLACE INTO city_shapes (city_id, status) VALUES (?, 'error')", (int(city_id),))
            con.commit()
            return "error"
        if found is None:
            con.execute("INSERT OR REPLACE INTO city_shapes (city_id, status) VALUES (?, 'none')", (int(city_id),))
        else:
            geom, source, area_name = found
            con.execute("""INSERT OR REPLACE INTO city_shapes (city_id, status, geometry, osm_name, method)
                           VALUES (?, 'ok', ?, ?, ?)""", (int(city_id), json.dumps(geom), area_name, source))
        con.commit()
        log.info("limite de %s: %s", city[0], "ok" if found else "não encontrado")
        return "ok" if found else "none"
    finally:
        con.close()


def backfill(db_path, geo_db_path, allow_nominatim=True):
    """Busca limites de cidades marcadas que ainda não têm (ou deram erro)."""
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    ids = [r[0] for r in con.execute("""
        SELECT v.ref_id FROM visits v LEFT JOIN city_shapes s ON s.city_id = v.ref_id
         WHERE v.kind = 'city' AND (s.city_id IS NULL OR s.status = 'error')""")]
    con.close()
    for cid in ids:
        fetch_and_store(db_path, geo_db_path, cid, allow_nominatim)


_bf_lock = threading.Lock()
_bf = {"running": False, "queue": {}}   # banco do perfil -> argumentos


def backfill_running():
    return _bf["running"]


def start_backfill(db_path, geo_db_path, allow_nominatim=True):
    """Um backfill por vez, numa fila só para todos os perfis: pedido no meio de
    outro (ex.: lista de cidades marcada logo depois de outra) roda quando o
    atual terminar, em vez de dois ao mesmo tempo pedirem ao Nominatim."""
    with _bf_lock:
        _bf["queue"][str(db_path)] = (db_path, geo_db_path, allow_nominatim)
        if _bf["running"]:
            return
        _bf["running"] = True

    def run():
        while True:
            with _bf_lock:
                if not _bf["queue"]:
                    _bf["running"] = False
                    return
                args = _bf["queue"].pop(next(iter(_bf["queue"])))
            try:
                backfill(*args)
            except Exception:
                log.exception("backfill de contornos")

    threading.Thread(target=run, daemon=True, name="city-boundaries").start()
