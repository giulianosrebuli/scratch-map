"""Contorno de cidade a partir dos dados locais do Overture Maps, recortado pelo
litoral do OSM — o mesmo litoral dos tiles de país e estado, então a costa da
cidade coincide com a deles.

Arquivos (gerados por scripts/build_geodata.py):
  geodata/localities/         áreas de cidade (locality/localadmin/county) com nome,
                              em parquet particionado por blocos de 10° (cx, cy)
  geodata/localities_large.parquet  as que têm mais de 3° de extensão
  geodata/land.parquet        polígonos de terra do OSM, picados, com bbox

Nada sai da máquina. Usado em tempo de execução (ao marcar uma cidade) e pelo
build (Clipper recorta países e estados).

Modo leve (instalação sem localities/): não há áreas locais, então o contorno
de toda cidade vem do fallback (Nominatim), recortado pelo mesmo litoral.
"""
import os
import unicodedata
from pathlib import Path

import duckdb
import shapely
from shapely import wkb
from shapely.geometry import Point

GEODATA = Path(os.environ.get("SCRATCH_GEODATA", Path(__file__).resolve().parent / "geodata"))
STEP_DEG = 5         # feição grande é recortada em quadrados deste tamanho (memória)
MAX_SPAN_DEG = 3.0   # área maior que isso é região, não cidade
CELL_DEG = 10        # tamanho do bloco das áreas de cidade (pelo centro do bbox)
SIMPLIFY_DEG = 1e-5  # ~1 m, o mesmo dos tiles


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def connect(mem="300MB", threads=1):  # o serviço tem MemoryMax=768M
    con = duckdb.connect()
    con.sql(f"SET threads={threads}; SET memory_limit='{mem}'; SET preserve_insertion_order=false")
    return con


def polys_of(geoms):
    out = []
    for g in geoms:
        out.extend(p for p in shapely.get_parts(g) if p.geom_type == "Polygon" and not p.is_empty)
    return out


def union(polys):
    try:
        return shapely.coverage_union_all(polys)  # pedaços que só se tocam nas bordas: rápido
    except Exception:
        return shapely.union_all(polys)


class Clipper:
    """Recorta uma geometria pelo litoral (interseção com a terra)."""

    def __init__(self, land=GEODATA / "land.parquet", con=None):
        self.land_path = land
        self.con = con or connect()

    def land(self, x0, y0, x1, y1):
        return [wkb.loads(bytes(r[0])) for r in self.con.execute(
            f"SELECT wkb FROM '{self.land_path}' WHERE x1 >= ? AND x0 <= ? AND y1 >= ? AND y0 <= ?",
            [x0, x1, y0, y1]).fetchall()]

    def _tile(self, part, x0, y0, x1, y1):
        local = shapely.clip_by_rect(part, x0, y0, x1, y1)
        if local.is_empty:
            return None
        shapely.prepare(local)
        out = []
        for p in self.land(x0, y0, x1, y1):
            p = shapely.clip_by_rect(p, x0, y0, x1, y1)
            if p.is_empty or not local.intersects(p):
                continue
            if local.contains(p):
                out.append(p)
                continue
            a = shapely.clip_by_rect(local, *p.bounds)
            try:
                out.append(a.intersection(p))
            except shapely.errors.GEOSException:  # o recorte por retângulo às vezes sai inválido
                out.append(shapely.make_valid(a).intersection(shapely.make_valid(p)))
        ps = polys_of(out)
        return union(ps) if ps else None

    def clip(self, g):
        """MultiPolygon só com a parte em terra, ou None."""
        out = []
        for part in shapely.get_parts(g):
            x0, y0, x1, y1 = part.bounds
            x = x0
            while x < x1:
                y = y0
                while y < y1:
                    r = self._tile(part, x, y, min(x + STEP_DEG, x1), min(y + STEP_DEG, y1))
                    if r is not None:
                        out.append(r)
                    y += STEP_DEG
                x += STEP_DEG
        ps = polys_of(out)
        if not ps:
            return None
        u = union(ps)
        if not u.is_valid:
            u = shapely.make_valid(u)
        ps = polys_of([u])
        return shapely.multipolygons(ps) if ps else None


def _same_name(want, names):
    """2 = nome igual, 1 = um contém o outro como palavras ("New York" e
    "New York City"), 0 = diferente."""
    best = 0
    for n in names:
        n = norm(n)
        if not n:
            continue
        if n == want:
            return 2
        if len(min(n, want, key=len)) >= 4 and (f" {n} " in f" {want} " or f" {want} " in f" {n} "):
            best = 1
    return best


def same_box(a, b, tol=0.01):
    """Dois bbox iguais, a menos de tol (fração da extensão)."""
    w, h = max(b[2] - b[0], 1e-6), max(b[3] - b[1], 1e-6)
    return (abs(a[0] - b[0]) < tol * w and abs(a[2] - b[2]) < tol * w
            and abs(a[1] - b[1]) < tol * h and abs(a[3] - b[3]) < tol * h)


def find_area(con, name, lat, lon, state_bbox=None):
    """((division_id, nome, geometria) ou None, descartou_igual_ao_estado).
    Prefere as de mesmo nome (igual > parecido) e, entre elas, a maior: o
    município inteiro, não só a mancha urbana. Sem nome parecido, a menor que
    contém o ponto (ex.: em Tóquio, o distrito), desde que menor que
    MAX_SPAN_DEG. Áreas maiores que isso (ex.: Vitória, que inclui a ilha da
    Trindade) ficam num arquivo à parte e só valem com o nome igual.
    Área com o mesmo contorno do estado é descartada: é erro do dado (no
    Overture, "Plano Piloto", de Brasília, é o Distrito Federal inteiro); aí
    quem chama pode buscar o contorno em outra fonte."""
    # só os blocos em volta: uma área pequena que contém o ponto tem o centro a
    # menos de MAX_SPAN_DEG/2 dele
    cell = lambda v, d: int((v + d) // CELL_DEG)
    r = MAX_SPAN_DEG / 2
    rows = con.execute(f"""SELECT division_id, name, name_pt, geometry, false AS large
                           FROM read_parquet('{GEODATA}/localities/*/*/*.parquet', hive_partitioning = true)
                           WHERE cx BETWEEN ? AND ? AND cy BETWEEN ? AND ?
                             AND x0 <= ? AND x1 >= ? AND y0 <= ? AND y1 >= ?
                             AND x1 - x0 < {MAX_SPAN_DEG} AND y1 - y0 < {MAX_SPAN_DEG}
                           UNION ALL
                           SELECT division_id, name, name_pt, geometry, true FROM '{GEODATA}/localities_large.parquet'
                           WHERE x0 <= ? AND x1 >= ? AND y0 <= ? AND y1 >= ?""",
                       [cell(lon, -r), cell(lon, r), cell(lat, -r), cell(lat, r),
                        lon, lon, lat, lat, lon, lon, lat, lat]).fetchall()
    pt, want = Point(lon, lat), norm(name)
    cand, state_like = [], False
    for div, n, pt_name, w, large in rows:
        same = _same_name(want, (n, pt_name))
        if large and same < 2:
            continue
        g = wkb.loads(bytes(w))
        if not g.contains(pt):
            continue
        if state_bbox and same_box(g.bounds, state_bbox):
            state_like = True
            continue
        cand.append((same, g.area, div, pt_name or n, g))
    if not cand:
        return None, state_like
    top = max(c[0] for c in cand)
    if top:
        best = max((c for c in cand if c[0] == top), key=lambda c: c[1])
    else:
        best = min(cand, key=lambda c: c[1])
    return (best[2], best[3], best[4]), state_like


def city_shape(name, lat, lon, state_bbox=None, fallback=None):
    """(geometria GeoJSON recortada pelo litoral, origem, nome) ou None.
    origem: "overture:<division_id>", ou o que fallback devolver.
    fallback() é chamado quando a única área do ponto é igual ao estado (ou
    sempre, no modo leve); devolve (geometria GeoJSON, origem, nome) de outra
    fonte, ou None."""
    con = connect()
    try:
        if (GEODATA / "localities").exists():
            found, state_like = find_area(con, name, lat, lon, state_bbox)
        else:  # modo leve: sem áreas locais
            found, state_like = None, True
        if found:
            div, area_name, g = found
            source = f"overture:{div}"
        elif state_like and fallback:
            other = fallback()
            if other is None:
                return None
            gj, source, area_name = other
            g = shapely.geometry.shape(gj)
            if state_bbox and same_box(g.bounds, state_bbox):
                return None
        else:
            return None
        g = Clipper(con=con).clip(g)
        if g is None:
            return None
        g = shapely.simplify(g, SIMPLIFY_DEG, preserve_topology=True)
        g = shapely.set_precision(g, 1e-6)  # 6 casas (~10 cm): JSON menor
        return shapely.geometry.mapping(g), source, area_name
    finally:
        con.close()
