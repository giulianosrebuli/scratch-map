#!/usr/bin/env python3
"""Baixa e processa os dados geográficos de referência.

Gera (tudo usado pelo app em tempo de execução):
  geodata/world.pmtiles       tiles vetoriais de países e estados (camadas
                              "countries" e "states"), servidos ao navegador
  geodata/geo.db              SQLite com países, estados, cidades e aeroportos
                              (cidade já vem com o estado e o país a que pertence)
  geodata/localities/         áreas de cidade do Overture, com nome (parquet
                              particionado em blocos de 10°)
  geodata/localities_large.parquet  as com mais de 3° de extensão
  geodata/land.parquet        litoral do OSM picado, para recortar o contorno da
                              cidade na hora de marcar (geoshapes.py)

Fontes:
  Overture Maps, tema divisions (dados do OpenStreetMap, ODbL)
                        países, estados e áreas de cidade
  OSM land polygons (osmdata.openstreetmap.de, ODbL)
                        litoral: país, estado e cidade são todos recortados por
                        ele, então a costa é a mesma linha nas três camadas
  GeoNames cities1000 (CC-BY 4.0)      cidades com população >= 1000
  OurAirports (domínio público)        aeroportos

Etapas (cada uma pula se a saída já existe; --redo ETAPA refaz):
  download  ~6 GB em geodata/raw e geodata/work (só usados no build)
  clip      recorta países/estados pelo litoral (~30 min)
  tiles     gera o world.pmtiles com o tippecanoe (~45 min)
  db        gera o geo.db
  cleanup   (só com --cleanup) apaga geodata/raw e geodata/work

Modos (--mode):
  completo  tudo acima (~6,3 GB no fim)
  leve      sem as áreas de cidade (localities*, ~4,4 GB a menos): o contorno
            da cidade vem do Nominatim (geoshapes.city_shape)

Versão do Overture: a mais nova publicada (o Overture só mantém as últimas),
ou --release. Fica em geodata/geodata.json junto com o modo.

Assistente de primeira execução (installer.py): --status ARQUIVO grava o
andamento em JSON; --simulate PASTA imita as etapas copiando os arquivos
prontos de outra instalação (para testar o assistente sem o build de 1h30).

Requer: venv com shapely e duckdb; o binário `tippecanoe` (github.com/felt/tippecanoe)
no PATH ou em TIPPECANOE. Memória: roda em 8 GB, mas apertado; mais é melhor.

Uso:  venv/bin/python scripts/build_geodata.py [--mode leve] [--redo ETAPA ...] [--maxzoom 12]
Depois de um rebuild de estados/países, rode scripts/migrate_ids.py se os ids
mudaram (ex.: na troca do Natural Earth pelo Overture).
"""
import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import unicodedata
import urllib.request
import zipfile
import sys
from multiprocessing import Pool
from pathlib import Path

import duckdb
import shapely
from shapely import wkb
from shapely.geometry import Point, mapping
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from geoshapes import Clipper, norm  # noqa: E402

GEODATA = Path(os.environ.get("SCRATCH_GEODATA", ROOT / "geodata"))
RAW = GEODATA / "raw"
WORK = GEODATA / "work"
GEO_DB = GEODATA / "geo.db"
TILES = GEODATA / "world.pmtiles"
LOCALITIES = GEODATA / "localities"
LAND = GEODATA / "land.parquet"
MANIFEST = GEODATA / "geodata.json"

OVERTURE_BUCKET = "overturemaps-us-west-2"
OVERTURE = None   # s3://…/release/<versão>/theme=divisions (definido no download)
MODE = "completo"
RELEASE = None    # --release; sem ele, a mais nova
SOURCES = {
    "cities1000.zip": "https://download.geonames.org/export/dump/cities1000.zip",
    "admin1CodesASCII.txt": "https://download.geonames.org/export/dump/admin1CodesASCII.txt",
    "airports.csv": "https://davidmegginson.github.io/ourairports-data/airports.csv",
    "land-polygons-split-4326.zip": "https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip",
}
TILE_TOL = 1e-5      # simplificação antes dos tiles (~1 m, menor que o pixel do zoom 12)
LOOKUP_TOL = 1e-3    # simplificação para achar o estado de uma cidade (~100 m)


STATUS = None     # --status: andamento em JSON, lido pelo assistente
_status = {}


def status(**kw):
    if STATUS is None:
        return
    _status.update(kw, updated_at=time.time())
    tmp = STATUS.with_name(STATUS.name + ".tmp")
    tmp.write_text(json.dumps(_status))
    os.replace(tmp, STATUS)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)
    status(msg=" ".join(map(str, a)))


def latest_release():
    """A versão mais nova do Overture no bucket público (ex.: 2026-09-23.1)."""
    url = f"https://{OVERTURE_BUCKET}.s3.amazonaws.com/?list-type=2&prefix=release/&delimiter=/"
    with urllib.request.urlopen(url, timeout=30) as r:
        found = re.findall(r"<Prefix>release/([^/<]+)/</Prefix>", r.read().decode())
    if not found:
        raise RuntimeError("nenhuma versão do Overture encontrada")
    return max(found)


def fetch(url, dest):
    """Baixa para dest (via .part), com o andamento no status."""
    last = [0.0]

    def hook(blocks, size, total):
        now = time.time()
        if total > 0 and now - last[0] > 2:
            last[0] = now
            status(msg=f"baixando {dest.name}: {blocks * size / 1e6:,.0f} de {total / 1e6:,.0f} MB")
    part = dest.with_name(dest.name + ".part")
    urllib.request.urlretrieve(url, part, reporthook=hook)
    os.replace(part, dest)


def duck(mem="2GB", threads=4):
    con = duckdb.connect()
    con.sql(f"""INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';
                SET threads={threads}; SET memory_limit='{mem}'; SET preserve_insertion_order=false""")
    return con


# ---------------------------------------------------------------- download
def download():
    RAW.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        dest = RAW / name
        if not dest.exists():
            log("baixando", url)
            fetch(url, dest)
    if not (RAW / "cities1000.txt").exists():
        with zipfile.ZipFile(RAW / "cities1000.zip") as z:
            z.extract("cities1000.txt", RAW)
    if not (RAW / "land-polygons-split-4326").exists():
        with zipfile.ZipFile(RAW / "land-polygons-split-4326.zip") as z:
            z.extractall(RAW)

    global OVERTURE
    release_file = WORK / "release.txt"
    if not release_file.exists():
        release_file.write_text(RELEASE or latest_release())
    OVERTURE = f"s3://{OVERTURE_BUCKET}/release/{release_file.read_text().strip()}/theme=divisions"
    log("Overture:", release_file.read_text().strip())
    con = duck()
    area = f"read_parquet('{OVERTURE}/type=division_area/*.parquet')"
    if not (WORK / "admin.parquet").exists():
        # versão territorial (sem recorte): o recorte pelo litoral é nosso
        log("Overture: países e estados")
        con.sql(f"""COPY (SELECT division_id, subtype, country, region, geometry FROM {area}
                    WHERE subtype IN ('country','dependency','region') AND is_territorial)
                    TO '{WORK}/admin.parquet' (FORMAT parquet)""")
    if not (WORK / "names.parquet").exists():
        log("Overture: nomes")
        con.sql(f"""COPY (SELECT id AS division_id, names.primary AS name, names.common['pt'] AS name_pt,
                           names.common['en'] AS name_en, population
                    FROM read_parquet('{OVERTURE}/type=division/*.parquet')
                    WHERE subtype IN ('country','dependency','region','county','localadmin','locality'))
                    TO '{WORK}/names.parquet' (FORMAT parquet)""")
    if MODE == "completo" and not LOCALITIES.exists():
        log("Overture: áreas de cidade")
        # particionado por blocos de 10° (centro do bbox): ordenar 4,5 GB não cabe em 8 GB
        con.sql(f"""COPY (SELECT division_id, subtype, country, names.primary AS name, names.common['pt'] AS name_pt,
                           bbox.xmin x0, bbox.xmax x1, bbox.ymin y0, bbox.ymax y1, geometry
                    FROM {area} WHERE subtype IN ('locality','localadmin','county'))
                    TO '{WORK}/localities_raw.parquet' (FORMAT parquet)""")
        con2 = duck(mem="2500MB", threads=1)
        con2.sql(f"SET temp_directory='{WORK}/duck-tmp'")
        con2.sql(f"""COPY (SELECT *, CAST(floor((x0 + x1) / 20) AS INT) AS cx, CAST(floor((y0 + y1) / 20) AS INT) AS cy
                     FROM '{WORK}/localities_raw.parquet')
                     TO '{LOCALITIES}' (FORMAT parquet, PARTITION_BY (cx, cy), ROW_GROUP_SIZE 256)""")
        # as com mais de 3° (ex.: Vitória, com a ilha da Trindade) também num arquivo
        # à parte, sempre consultado: o centro delas pode cair longe do ponto
        con2.sql(f"""COPY (SELECT * FROM '{WORK}/localities_raw.parquet' WHERE x1 - x0 >= 3 OR y1 - y0 >= 3)
                     TO '{GEODATA}/localities_large.parquet' (FORMAT parquet, ROW_GROUP_SIZE 64)""")
    if not LAND.exists():
        # ordenado por curva de Hilbert: a busca por bbox lê só alguns blocos
        log("litoral → parquet")
        con.sql(f"""COPY (SELECT ST_AsWKB(geom) AS wkb, ST_XMin(geom) x0, ST_XMax(geom) x1,
                           ST_YMin(geom) y0, ST_YMax(geom) y1
                    FROM ST_Read('{RAW}/land-polygons-split-4326/land_polygons.shp')
                    ORDER BY ST_Hilbert((ST_XMin(geom)+ST_XMax(geom))/2, (ST_YMin(geom)+ST_YMax(geom))/2,
                                        {{'min_x':-180,'min_y':-90,'max_x':180,'max_y':90}}::BOX_2D))
                    TO '{LAND}' (FORMAT parquet, ROW_GROUP_SIZE 2048)""")


# ---------------------------------------------------------------- recorte
_clipper = None


def _clip_admin(row):
    global _clipper
    _clipper = _clipper or Clipper(LAND)
    div, subtype, country, region, w = row
    g = _clipper.clip(wkb.loads(w))
    if g is None:
        return None
    layer = "states" if subtype == "region" else "countries"
    props = {"id": (region or div) if layer == "states" else country, "country": country, "subtype": subtype}
    return layer, div, props, shapely.to_geojson(g)


def clip():
    """WORK/clipped_{countries,states}.geojsonl, uma feição por linha."""
    names = admin_names()
    con = duck()
    ids = [r[0] for r in con.sql(f"""SELECT division_id FROM '{WORK}/admin.parquet'
                                     ORDER BY ST_NPoints(geometry) DESC""").fetchall()]

    def rows():  # lê uma de cada vez: o arquivo inteiro não cabe na memória
        for d in ids:
            r = con.execute(f"""SELECT division_id, subtype, country, region, ST_AsWKB(geometry)
                                FROM '{WORK}/admin.parquet' WHERE division_id = ?""", [d]).fetchone()
            yield r[:4] + (bytes(r[4]),)

    outs = {k: open(WORK / f"clipped_{k}.geojsonl.tmp", "w") for k in ("countries", "states")}
    n = 0
    with Pool(2) as pool:
        for res in pool.imap_unordered(_clip_admin, rows(), chunksize=1):
            n += 1
            if res:
                layer, div, props, gj = res
                props["oid"] = div
                props["name"] = admin_label(layer, names.get(div))[0] or ""
                outs[layer].write(f'{{"type":"Feature","properties":{json.dumps(props)},"geometry":{gj}}}\n')
            if n % 250 == 0:
                log(f"recorte: {n}/{len(ids)}")
    for k, f in outs.items():
        f.close()
        os.replace(f.name, WORK / f"clipped_{k}.geojsonl")


def admin_names():
    """division_id -> (português, inglês, original)."""
    con = duck()
    return {d: (pt, en, name) for d, name, pt, en in con.sql(
        f"SELECT division_id, name, name_pt, name_en FROM '{WORK}/names.parquet'").fetchall()}


def latin(s):
    return all(not ch.isalpha() or unicodedata.name(ch, "").startswith("LATIN") for ch in s)


def admin_label(layer, names):
    """Nomes de um país ou estado: (name, name_en, search). País no idioma da
    interface (Alemanha / Germany); estado com o nome de lá (Bayern), como as
    cidades, ou em inglês quando o de lá não é em alfabeto latino (東京都 → Tokyo)."""
    pt, en, orig = names or (None, None, None)
    if layer == "countries":
        name, name_en = pt or en or orig, en or orig or pt
    else:
        name = orig if orig and latin(orig) else en or pt or orig
        name_en = None
    search = " ".join(dict.fromkeys(norm(x) for x in (name, pt, en, orig) if x))  # acha por qualquer um
    return name, name_en, search


def features(path):
    """(propriedades, geometria) de cada linha de um .geojsonl, sem carregar o arquivo."""
    with open(path) as fh:
        for line in fh:
            i = line.index('"properties"')
            props = json.loads(line[line.index("{", i): line.index("}", i) + 1])
            if props.get("id") is None:  # estado sem código ISO: id do Overture
                props["id"] = props["oid"]
            yield props, shapely.from_geojson(line)


# ---------------------------------------------------------------- tiles
def tiles(maxzoom):
    """Separa cada feição em polígonos e simplifica a ~1 m (o tippecanoe não
    precisa segurar países inteiros na memória), e gera o world.pmtiles."""
    for layer in ("countries", "states"):
        with open(WORK / f"tiles_{layer}.geojsonl", "w") as out:
            for props, g in features(WORK / f"clipped_{layer}.geojsonl"):
                pj = json.dumps(props)
                for p in shapely.get_parts(g):
                    s = shapely.simplify(p, TILE_TOL, preserve_topology=True)
                    if not s.is_empty:
                        out.write(f'{{"type":"Feature","properties":{pj},"geometry":{shapely.to_geojson(s)}}}\n')
        log("tiles: preparado", layer)
    tmp = WORK / "tippecanoe-tmp"
    tmp.mkdir(exist_ok=True)
    tip = os.environ.get("TIPPECANOE") or shutil.which("tippecanoe") or "tippecanoe"
    subprocess.run([tip, "-q", "-o", str(TILES) + ".tmp.pmtiles", "--force", "-t", str(tmp),
                    "-Z0", f"-z{maxzoom}", "--detect-shared-borders", "--no-tile-size-limit", "--no-feature-limit",
                    "-L", f"countries:{WORK}/tiles_countries.geojsonl",
                    "-L", f"states:{WORK}/tiles_states.geojsonl"], check=True)
    os.replace(str(TILES) + ".tmp.pmtiles", TILES)


# ---------------------------------------------------------------- geo.db
def bbox(g):
    """bbox para o mapa enquadrar. Ignora ilhas minúsculas (< 2% da maior parte,
    ex.: Trindade no Espírito Santo, Havaí nos EUA), e quem cruza o antimeridiano
    (Rússia, Fiji…) sai com leste > 180."""
    parts = shapely.get_parts(g)
    big = max(p.area for p in parts)
    parts = [p for p in parts if p.area >= big * 0.02]
    g = shapely.multipolygons(parts)
    x0, y0, x1, y1 = g.bounds
    if x1 - x0 > 180:
        shifted = [shapely.transform(p, lambda c: c + [360, 0]) if p.bounds[2] < 0 else p for p in parts]
        b = shapely.union_all([shapely.box(*p.bounds) for p in shifted]).bounds
        if b[2] - b[0] < x1 - x0:
            return b
    return x0, y0, x1, y1


class Locator:
    """Ponto -> feição que o contém (com fallback para a mais próxima, até 0,5°)."""

    def __init__(self, items):  # [(id, grupo, geometria)]
        self.ids, self.groups, self.geoms = [], [], []
        for id_, group, g in items:
            for p in shapely.get_parts(g):
                self.ids.append(id_)
                self.groups.append(group)
                self.geoms.append(p)
        self.tree = STRtree(self.geoms)
        shapely.prepare(self.geoms)

    def find(self, lon, lat, group=None, max_dist=0.5):
        p = Point(lon, lat)
        for i in self.tree.query(p, predicate="intersects"):
            if group is None or self.groups[i] == group:
                return self.ids[i]
        # cidades costeiras às vezes caem no mar (ponto do GeoNames fora do litoral)
        best, best_d = None, max_dist
        for i in self.tree.query(p.buffer(max_dist)):
            if group is not None and self.groups[i] != group:
                continue
            d = self.geoms[i].distance(p)
            if d < best_d:
                best, best_d = self.ids[i], d
        return best


def load_admin(layer):
    """[(props, geometria simplificada para busca, bbox)]."""
    out = []
    for props, g in features(WORK / f"clipped_{layer}.geojsonl"):
        # sem preservar topologia: ~100x mais rápido em país grande (3 s × 400 s);
        # para achar o estado de um ponto, um polígono inválido aqui e ali tanto faz
        s = shapely.simplify(g, LOOKUP_TOL, preserve_topology=False)
        if not s.is_valid:
            s = shapely.make_valid(s)
        out.append((props, s, bbox(g)))
    return out


def build_db():
    countries = load_admin("countries")
    states = load_admin("states")
    names = admin_names()
    for layer, rows in (("countries", countries), ("states", states)):
        for p, _, _ in rows:
            name, p["name_en"], p["search"] = admin_label(layer, names.get(p["oid"]))
            p["name"] = name or p.get("name") or p["id"]
            p["search"] = p["search"] or norm(p["name"])
    log("db: contornos carregados")
    country_ids = {p["id"] for p, _, _ in countries}
    country_loc = Locator([(p["id"], None, g) for p, g, _ in countries])
    state_loc = Locator([(p["id"], p["country"], g) for p, g, _ in states])

    tmp = GEO_DB.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("""
        CREATE TABLE countries (id TEXT PRIMARY KEY, name TEXT, search TEXT,
                                x0 REAL, y0 REAL, x1 REAL, y1 REAL, name_en TEXT);
        CREATE TABLE states (id TEXT PRIMARY KEY, name TEXT, country_id TEXT, search TEXT,
                             x0 REAL, y0 REAL, x1 REAL, y1 REAL);
        CREATE TABLE cities (id INTEGER PRIMARY KEY, name TEXT, region TEXT, country_id TEXT,
                             state_id TEXT, lat REAL, lon REAL, population INTEGER, search TEXT);
        CREATE TABLE airports (id TEXT PRIMARY KEY, name TEXT, municipality TEXT, country_id TEXT,
                               lat REAL, lon REAL, type TEXT, search TEXT);
    """)
    db.executemany("INSERT INTO countries VALUES (?,?,?,?,?,?,?,?)",
                   [(p["id"], p["name"], p["search"], *b, p["name_en"]) for p, _, b in countries])
    db.executemany("INSERT INTO states VALUES (?,?,?,?,?,?,?,?)",
                   [(p["id"], p["name"], p["country"], p["search"], *b) for p, _, b in states])

    admin1 = {}
    with open(RAW / "admin1CodesASCII.txt", encoding="utf-8") as fh:
        for line in fh:
            code, name, *_ = line.rstrip("\n").split("\t")
            admin1[code] = name

    rows = []
    with open(RAW / "cities1000.txt", encoding="utf-8") as fh:
        for n, line in enumerate(fh):
            c = line.rstrip("\n").split("\t")
            gid, name, ascii_name = int(c[0]), c[1], c[2]
            lat, lon, cc, a1, pop = float(c[4]), float(c[5]), c[8], c[10], int(c[14] or 0)
            country = cc if cc in country_ids else country_loc.find(lon, lat)
            state = state_loc.find(lon, lat, group=country) or state_loc.find(lon, lat)
            search = " ".join({norm(name), norm(ascii_name)})
            rows.append((gid, name, admin1.get(f"{cc}.{a1}", ""), country, state, lat, lon, pop, search))
            if n % 20000 == 0:
                log(f"cidades: {n}")
    db.executemany("INSERT INTO cities VALUES (?,?,?,?,?,?,?,?,?)", rows)

    # Aeroportos: só os com código IATA e (grandes/médios ou com voo regular).
    rows = []
    with open(RAW / "airports.csv", encoding="utf-8") as fh:
        for a in csv.DictReader(fh):
            iata = (a["iata_code"] or "").strip()
            if not iata or a["type"] not in ("large_airport", "medium_airport", "small_airport"):
                continue
            if a["type"] == "small_airport" and a["scheduled_service"] != "yes":
                continue
            lat, lon = float(a["latitude_deg"]), float(a["longitude_deg"])
            cc = a["iso_country"]
            country = cc if cc in country_ids else country_loc.find(lon, lat)
            rows.append((iata, a["name"], a["municipality"], country, lat, lon, a["type"],
                         f"{iata.lower()} {norm(a['name'])} {norm(a['municipality'])}"))
    db.executemany("INSERT OR IGNORE INTO airports VALUES (?,?,?,?,?,?,?,?)", rows)

    db.executescript("""
        CREATE INDEX cities_pop ON cities(population DESC);
        CREATE INDEX cities_state ON cities(state_id);
        CREATE INDEX states_country ON states(country_id);
    """)
    db.commit()
    for t in ("countries", "states", "cities", "airports"):
        log(t, db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    log("cidades sem estado:", db.execute("SELECT COUNT(*) FROM cities WHERE state_id IS NULL").fetchone()[0])
    db.close()
    os.replace(tmp, GEO_DB)


# ---------------------------------------------------------------- fim
def cleanup():
    for d in (RAW, WORK):
        shutil.rmtree(d, ignore_errors=True)


def write_manifest():
    old = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    rel = WORK / "release.txt"
    release = rel.read_text().strip() if rel.exists() else old.get("release")
    MANIFEST.write_text(json.dumps({"mode": MODE, "release": release,
                                    "built_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2))


def simulate(src, step):
    """Teste do assistente: espera um pouco e copia de src o que a etapa geraria."""
    outputs = {"download": ["land.parquet"] + (["localities_large.parquet", "localities"] if MODE == "completo" else []),
               "clip": [], "tiles": ["world.pmtiles"], "db": ["geo.db"], "cleanup": []}
    secs = {"download": 20, "clip": 15, "tiles": 15, "db": 8, "cleanup": 2}[step]
    for i in range(secs):
        status(msg=f"simulação: {step} ({i + 1}/{secs} s)")
        time.sleep(1)
    if step == "cleanup":
        return cleanup()
    WORK.mkdir(parents=True, exist_ok=True)
    if step == "download":
        (WORK / "release.txt").write_text(json.loads((src / "geodata.json").read_text())["release"]
                                          if (src / "geodata.json").exists() else "simulação")
    for name in outputs[step]:
        s, d = src / name, GEODATA / name
        log("simulação: copiando", name)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copyfile(s, d.with_name(d.name + ".tmp"))
            os.replace(d.with_name(d.name + ".tmp"), d)


STEPS = ["download", "clip", "tiles", "db"]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--redo", nargs="*", default=[], choices=STEPS)
    ap.add_argument("--maxzoom", type=int, default=12)
    ap.add_argument("--mode", choices=("completo", "leve"), default="completo")
    ap.add_argument("--release", help="versão do Overture (padrão: a mais nova)")
    ap.add_argument("--status", type=Path, help="grava o andamento neste JSON")
    ap.add_argument("--cleanup", action="store_true", help="apaga raw/ e work/ no fim")
    ap.add_argument("--simulate", type=Path, help="copia os arquivos prontos desta pasta (teste)")
    args = ap.parse_args()
    MODE, RELEASE, STATUS = args.mode, args.release, args.status
    GEODATA.mkdir(parents=True, exist_ok=True)
    steps = STEPS + (["cleanup"] if args.cleanup else [])
    status(state="running", mode=MODE, steps=steps, done=[], step=None, error=None, started_at=time.time())
    done = {
        "clip": (WORK / "clipped_states.geojsonl").exists() or TILES.exists() and GEO_DB.exists(),
        "tiles": TILES.exists(),
        "db": GEO_DB.exists() and sqlite3.connect(GEO_DB).execute(
            "SELECT 1 FROM pragma_table_info('countries') WHERE name = 'name_en'").fetchone() is not None,
    }
    try:
        for step in steps:
            status(step=step)
            if step in done and done[step] and step not in args.redo:
                log("pulando", step)
            elif args.simulate:
                log("etapa", step, "(simulação)")
                simulate(args.simulate, step)
            else:
                log("etapa", step)
                {"download": download, "clip": clip, "tiles": lambda: tiles(args.maxzoom),
                 "db": build_db, "cleanup": cleanup}[step]()
            status(done=_status.get("done", []) + [step])
            if step == "db":
                write_manifest()
    except BaseException as e:
        status(state="error", error=f"{type(e).__name__}: {e}")
        raise
    log("ok")
    status(state="done", step=None, finished_at=time.time())
