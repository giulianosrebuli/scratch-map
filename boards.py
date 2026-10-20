"""Quadros de raspar (/boards): desenhos estáticos no estilo dos pôsteres.

Um quadro é um recorte fixo: um continente com seus países, ou um país com
seus estados. Nada de zoom: o servidor projeta os contornos (boards.db, gerado
por scripts/build_boards.py) num retângulo de tamanho fixo e decide onde vai
cada nome. Cabe dentro da porção: o nome fica no centro dela (o ponto mais
longe da borda). Não cabe: o nome vai para a margem do quadro, ligado à porção
por um traço. O navegador só desenha (SVG) e pinta o que foi raspado.

Os quadros não mudam (só com uma nova montagem): cada um é calculado na
primeira vez que alguém abre (~1 s) e guardado em disco, em
geodata/boards-cache/v<LAYOUT>-<data do boards.db>/, e em memória. Mudou o
desenho (LAYOUT) ou o boards.db: a pasta antiga é apagada e tudo é refeito
aos poucos, conforme os quadros são abertos.
"""
import gzip
import json
import math
import shutil
import sqlite3
from functools import lru_cache, wraps
from pathlib import Path

import numpy as np
from shapely import STRtree, box, clip_by_rect, from_wkb
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import polylabel, transform

# Todo quadro tem a mesma proporção (paisagem, 3:2) e o mesmo desenho: título
# no alto à esquerda, a lista embaixo dele e o mapa na metade direita. Tudo em
# unidades do SVG (1500 × 1000), que o navegador escala por inteiro.
CANVAS = (1500, 1000)
LIST = (100, 290, 900)      # lista: x, topo, fim
MAP_Y = (80, 920)           # o mapa começa depois da lista e vai até MAP_X1
MAP_X1 = 1425
GUTTER = 80       # margem para as siglas com traço (só do lado que precisar)
LABEL_SIZES = (24, 21, 18, 15.5, 13, 11.5)
CALLOUT_SIZE = 16
CALLOUT_GAP = 19  # distância mínima entre nomes na margem
CAPS = 0.68       # largura média de uma letra em caixa alta (× tamanho da letra)
STUB = 12         # trecho reto do traço ao chegar no nome

# Continentes (a América em três). bbox fixo [oeste, sul, leste, norte]; os
# membros vêm do Natural Earth (continente/sub-região). O México fica na do
# Norte, o Caribe na Central.
CONTINENTS = {
    # prune: só o bloco principal (o Havaí, as Bermudas e as ilhas menores dos
    # EUA ficariam soltos no meio do oceano e encolheriam o mapa)
    "north-america": {"pt": "América do Norte", "en": "North America", "bbox": (-170, 13, -50, 72), "prune": 0.15,
                         "match": lambda c, s: s == "Northern America" or c == "North America" and s not in ("Central America", "Caribbean")},
    "central-america": {"pt": "América Central e Caribe", "en": "Central America & Caribbean", "bbox": (-93, 6.5, -59, 27),
                        "match": lambda c, s: s in ("Central America", "Caribbean")},
    "south-america": {"pt": "América do Sul", "en": "South America", "bbox": (-82, -56, -34, 13),
                       "match": lambda c, s: c == "South America"},
    "europe": {"pt": "Europa", "en": "Europe", "bbox": (-25, 34, 45, 71.5),
               "match": lambda c, s: c == "Europe"},
    "africa": {"pt": "África", "en": "Africa", "bbox": (-26, -36, 60, 38),
               "match": lambda c, s: c == "Africa"},
    "asia": {"pt": "Ásia", "en": "Asia", "bbox": (25, -11, 150, 56),
             "match": lambda c, s: c == "Asia"},
    "oceania": {"pt": "Oceania", "en": "Oceania", "bbox": (110, -48, 180, 2),
                "match": lambda c, s: c == "Oceania"},
}
MEXICO = "MX"  # o Natural Earth põe na América Central


LAYOUT = 6  # suba quando mudar o desenho do quadro: invalida o cache em disco


def disk_cached(fn):
    """Cache em disco (JSON gzip) + memória para continent()/country(). A
    chave é o nome da função e os argumentos depois dos dois caminhos."""
    @lru_cache(maxsize=256)
    @wraps(fn)
    def wrapper(boards_db, geo_db, *args):
        root = Path(boards_db).parent / "boards-cache"
        here = root / f"v{LAYOUT}-{int(Path(boards_db).stat().st_mtime)}"
        path = here / f"{fn.__name__}-{'-'.join(map(str, args))}.json.gz"
        if path.exists():
            return json.loads(gzip.decompress(path.read_bytes()))
        out = fn(boards_db, geo_db, *args)
        if out is not None:
            if not here.exists():  # versão nova: as pastas antigas não servem mais
                for old in root.glob("v*") if root.exists() else []:
                    shutil.rmtree(old, ignore_errors=True)
                here.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(json.dumps(out, separators=(",", ":")).encode()))
            tmp.replace(path)
        return out
    return wrapper


def _db(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def albers(bbox):
    """Projeção cônica equivalente (esférica) ajustada ao recorte."""
    w, s, e, n = bbox
    lat1, lat2 = math.radians(s + (n - s) / 6), math.radians(n - (n - s) / 6)
    lon0, lat0 = math.radians((w + e) / 2), math.radians((s + n) / 2)
    nn = (math.sin(lat1) + math.sin(lat2)) / 2
    if abs(nn) < 1e-6:  # recorte no equador: vira cilíndrica equivalente
        return lambda x, y, z=None: (math.radians(x) - lon0, math.sin(math.radians(y)))
    c = math.cos(lat1) ** 2 + 2 * nn * math.sin(lat1)
    rho0 = math.sqrt(c - 2 * nn * math.sin(lat0)) / nn

    def f(x, y, z=None):
        rho = math.sqrt(max(c - 2 * nn * math.sin(math.radians(y)), 0)) / nn
        theta = nn * (math.radians(x) - lon0)
        return rho * math.sin(theta), rho0 - rho * math.cos(theta)
    return f


def main_bbox(geom, near=3):
    """bbox da parte principal e das partes a menos de `near` graus dela
    (a França sem a Guiana, o Brasil sem Trindade)."""
    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    main = max(parts, key=lambda p: p.area)
    x0, y0, x1, y1 = main.bounds
    keep = [p for p in parts if p.distance(main) < near]
    bx = MultiPolygon(keep).bounds
    w, h = bx[2] - bx[0], bx[3] - bx[1]
    m = max(w, h) * 0.06
    return (bx[0] - m, bx[1] - m, bx[2] + m, bx[3] + m)


def candidates(poly, pole, k=24):
    """Onde tentar o nome: o ponto mais longe da borda e, depois, os pontos de
    uma grade dentro do polígono, dos mais longe da borda para os mais perto
    (estado comprido, como o Tocantins, cabe mais em cima ou embaixo)."""
    x0, y0, x1, y1 = poly.bounds
    step = max(min(x1 - x0, y1 - y0) / 8, 3)
    pts = [Point(x, y) for x in np.arange(x0 + step / 2, x1, step) for y in np.arange(y0 + step / 2, y1, step)]
    inside = sorted((p for p in pts if poly.contains(p)), key=lambda p: -poly.exterior.distance(p))
    return [(pole.x, pole.y)] + [(p.x, p.y) for p in inside[:k]]


MINOR = {"de", "do", "da", "dos", "das", "e", "del", "la", "los", "las", "el", "of", "the", "di", "du", "des", "le"}


def abbr(pid, name):
    """Sigla da porção no mapa: o código depois do hífen (BR-SP → SP) ou o
    próprio código do país (AR); sem código curto, as iniciais das palavras
    que contam (como no álbum do Perfil)."""
    code = pid.split("-", 1)[1] if "-" in pid and len(pid) < 12 else pid
    if 1 < len(code) <= 3 and code.isalpha():
        return code.upper()
    words = [w for w in name.replace("-", " ").split() if w.lower() not in MINOR]
    if len(words) > 1:
        return "".join(w[0] for w in words[:3]).upper()
    return (words[0] if words else name)[:3].upper()


def fit_text(poly, points, text, taken, sizes=LABEL_SIZES):
    """(x, y, tamanho) da sigla inteira dentro do polígono, deitada, no
    primeiro ponto em que cabe (a letra maior primeiro), sem encostar nas
    siglas já postas (`taken`, retângulos). Não cabe: None (vai para fora,
    com o traço)."""
    inner = poly.buffer(-2)
    for size in sizes:
        w, h = len(text) * size * CAPS + 2, size * 1.1
        for cx, cy in points:
            r = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            if inner.contains(r) and not any(r.intersects(o) for o in taken):
                taken.append(r.buffer(3))
                return cx, cy, size
    return None


TITLE_SIZE = 76    # letra do título (o navegador reduz se não couber em TITLE_MAX)
TITLE_MAX = 600


def title_width(title):
    return min(len(title) * TITLE_SIZE * 0.8, TITLE_MAX)


def list_layout(names, title):
    """Lista em colunas embaixo do título, o mais estreita possível (o mapa
    fica com o resto): entre as letras de 16 a 13, a de menos colunas (empate:
    a letra maior), em no máximo 5 colunas; não cabendo, letra 11 e
    nomes cortados. Nunca mais estreita que o título."""
    x, top, bottom = LIST
    longest = max((len(n) for n in names), default=1) + 4  # + a sigla antes do nome
    best = None
    for size in (16, 15, 14, 13):
        row_h = size * 1.6
        rows = int((bottom - top) // row_h)
        cols = -(-len(names) // rows)
        col_w = size * 1.5 + longest * size * CAPS + 22
        # menos colunas primeiro (é o que estreita); empate: a letra maior
        if cols <= 5 and cols * col_w <= 640 and (best is None or cols < best["cols"]):
            best = {"size": size, "row_h": row_h, "rows": rows, "cols": cols, "col_w": col_w, "cut": None,
                    "width": cols * col_w}
    if best is None:
        size, row_h = 11, 11 * 1.6
        rows = int((bottom - top) // row_h)
        col_w = 640 / -(-len(names) // rows)
        best = {"size": size, "row_h": row_h, "rows": rows, "col_w": col_w, "width": 640,
                "cut": max(4, int((col_w - 22 - size * 1.5) // (size * CAPS)))}
    best["width"] = max(best["width"], title_width(title))
    best.update(x=x, top=top, bottom=bottom)
    return best


WIDE = (100, 1425, 905)    # disposição larga: lista embaixo, de x0 a x1, terminando em y
WIDE_MAP_TOP = 270         # mapa largo: logo abaixo do título


def list_layout_wide(names):
    """Lista embaixo, na largura toda (disposição larga): a maior letra (16 a
    11) em que ela ocupa no máximo 230 de altura; não cabendo, corta os nomes."""
    x0, x1, bottom = WIDE
    longest = max((len(n) for n in names), default=1) + 4
    for size in (16, 15, 14, 13, 12, 11):
        row_h = size * 1.6
        col_w = size * 1.5 + longest * size * CAPS + 22
        cols = max(1, int((x1 - x0) // col_w))
        rows = -(-len(names) // cols)
        if rows * row_h <= 230 or size == 11:
            cut = None
            if rows * row_h > 230:  # nem na menor: corta os nomes para caber mais colunas
                rows = int(230 // row_h)
                cols = -(-len(names) // rows)
                col_w = (x1 - x0) / cols
                cut = max(4, int((col_w - 22 - size * 1.5) // (size * CAPS)))
            h = rows * row_h
            return {"size": size, "row_h": row_h, "rows": rows, "cols": cols, "col_w": col_w, "cut": cut,
                    "width": x1 - x0, "x": x0, "top": bottom - h, "bottom": bottom}


def trace(co, side):
    """Traço do nome até a porção, como trilha de placa de circuito: sai reto
    (horizontal) da porção, faz a transição a 45° e chega reto ao nome.

    As diagonais terminam todas na mesma coluna (a STUB do nome): como os
    nomes ficam na mesma ordem vertical das porções, duas trilhas nunca se
    cruzam e as diagonais paralelas ficam separadas pelo espaço entre nomes.
    Sem espaço na horizontal para a diagonal inteira, o resto vira vertical."""
    d = 1 if side == "right" else -1
    tx, ty, y = co["tx"], co["ty"], co["y"]
    end = co["x"] - d * (4 + STUB)          # onde a diagonal termina
    dy = y - ty
    start = end - d * abs(dy)               # onde a diagonal começa
    if (start - tx) * d < 6:                # não cabe: diagonal mais curta + vertical
        start = tx + d * 6
    run = abs(end - start)
    mid_y = ty + (run if dy > 0 else -run) if abs(dy) > run else y
    pts = [(tx, ty), (start, ty), (end, mid_y), (end, y), (co["x"] - d * 4, y)]
    out = []
    for p in pts:  # sem pontos repetidos (trechos de tamanho zero)
        if not out or (abs(p[0] - out[-1][0]) > 0.05 or abs(p[1] - out[-1][1]) > 0.05):
            out.append(p)
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in out)


def place_callouts(items, x, top, bottom):
    """Empilha os nomes de uma margem perto da altura de cada porção, sem
    sobrepor (desce o que encosta; se passar do fim, sobe tudo)."""
    items.sort(key=lambda it: it["ty"])
    y = top
    for it in items:
        it["y"] = max(it["ty"], y)
        y = it["y"] + CALLOUT_GAP
    over = (items[-1]["y"] - bottom) if items else 0
    if over > 0:
        y = bottom
        for it in reversed(items):
            it["y"] = min(it["y"], y)
            y = it["y"] - CALLOUT_GAP
    for it in items:
        it["x"] = x


def svg_path(geom):
    polys = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    out = []
    for p in polys:
        if not isinstance(p, Polygon) or p.is_empty:
            continue
        for ring in [p.exterior, *p.interiors]:
            pts = list(ring.coords)
            out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts[:-1]) + "Z")
    return "".join(out)


def polygonal(g):
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    polys = [p for p in getattr(g, "geoms", []) if isinstance(p, (Polygon, MultiPolygon))]
    return MultiPolygon([q for p in polys for q in (p.geoms if isinstance(p, MultiPolygon) else [p])]) if polys else Polygon()


def main_cluster(projected, near, keep=0.01):
    """Só o bloco principal do quadro: as partes ligadas à maior por
    distâncias curtas (cadeias de ilhas entram, como o Japão e a Indonésia) e
    os blocos à parte com área de verdade (a Nova Zelândia); somem as ilhas
    distantes e pequenas (Havaí, Bermudas, Trindade), que encolheriam o mapa.
    near: distância de ligação, em fração da diagonal da maior parte; keep:
    área mínima de um bloco à parte, em fração do principal."""
    parts = [(i, q) for i, (_, _, g) in enumerate(projected) for q in getattr(g, "geoms", [g])]
    if len(parts) < 2:
        return projected, []
    geoms = [q for _, q in parts]
    big = max(geoms, key=lambda q: q.area)
    bx0, by0, bx1, by1 = big.bounds
    thr = near * math.hypot(bx1 - bx0, by1 - by0)
    tree = STRtree(geoms)
    parent = list(range(len(geoms)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, q in enumerate(geoms):
        for b in tree.query(q, predicate="dwithin", distance=thr):
            parent[find(a)] = find(int(b))
    area = {}
    for a, q in enumerate(geoms):
        area[find(a)] = area.get(find(a), 0) + q.area
    main = max(area, key=area.get)
    ok = {c for c, ar in area.items() if c == main or ar >= keep * area[main]}
    kept = {}
    for a, (i, q) in enumerate(parts):
        if find(a) in ok:
            kept.setdefault(i, []).append(q)
    out = [(mid, nm, MultiPolygon(kept[i])) for i, (mid, nm, _) in enumerate(projected) if i in kept]
    dropped = [(mid, nm) for i, (mid, nm, _) in enumerate(projected) if i not in kept]
    return out, dropped


def build(bbox, members, names, title, codes=None, prune=None):
    """members: [(id, nome, geom)] raspáveis, só eles (sem o resto do continente);
    names: os nomes da lista (inclusive os fora do quadro). A lista fica com o
    espaço de que precisa e o mapa com o resto, com margem para os nomes com
    traço só do lado que precisar."""
    lst = list_layout(names, title)
    side_map = (LIST[0] + lst["width"] + 30, MAP_Y[0], MAP_X1, MAP_Y[1])
    # Recorta depois de projetar: o recorte é um retângulo na projeção (o bbox
    # em graus vira um trapézio curvo na cônica, e cortar por ele deixava a
    # Rússia em cunha). Antes, um corte folgado em graus só para não projetar
    # o mundo todo.
    proj = albers(bbox)
    w, s_, e, n = bbox
    loose = (max(w - 25, -180), max(s_ - 12, -89), min(e + 25, 180), min(n + 12, 89))
    x0, y0, x1, y1 = transform(proj, box(*bbox).segmentize(0.5)).bounds

    def clip(g):
        if not g.intersects(box(*loose)):
            return None
        c = polygonal(clip_by_rect(transform(proj, polygonal(clip_by_rect(g, *loose))), x0, y0, x1, y1))
        return None if c.is_empty else c
    projected = [(i, nm, c) for i, nm, g in members if (c := clip(g)) is not None]
    dropped = []
    if prune:  # só o bloco principal (main_cluster); prune = distância de ligação
        projected, dropped = main_cluster(projected, prune)
    if not projected:
        return {"members": [], "list": lst, "dropped": dropped}
    # enquadra o que foi desenhado (não o bbox inteiro)
    x0, y0, x1, y1 = MultiPolygon([q for _, _, g in projected for q in getattr(g, "geoms", [g])]).bounds
    # Disposição: a do esboço (lista à esquerda, mapa à direita) ou, para mapa
    # largo e baixo (Ásia, Caribe), a larga (mapa embaixo do título, lista
    # embaixo do mapa na largura toda). Vale a que deixa o mapa maior.
    fit = lambda r: min((r[2] - r[0]) / (x1 - x0), (r[3] - r[1]) / (y1 - y0))
    wide_lst = list_layout_wide(names)
    wide_map = (WIDE[0], WIDE_MAP_TOP, WIDE[1], wide_lst["top"] - 25)
    MAP = side_map
    if fit(wide_map) > fit(side_map):
        MAP, lst = wide_map, {**wide_lst, "layout": "wide"}

    def attempt(gl, gr):
        """Encaixa o mapa em MAP menos as margens; devolve (membros, esquerda, direita)."""
        mx0, my0, mx1, my1 = MAP[0] + gl, MAP[1], MAP[2] - gr, MAP[3]
        scale = min((mx1 - mx0) / (x1 - x0), (my1 - my0) / (y1 - y0))
        mw, mh = (x1 - x0) * scale, (y1 - y0) * scale
        ox, oy = mx1 - mw if gl == 0 and gr == 0 else (mx0 + mx1 - mw) / 2, (my0 + my1 - mh) / 2
        to_px = lambda g: transform(lambda x, y, z=None: (ox + (x - x0) * scale, oy + (y1 - y) * scale), g)
        out, left, right, taken = [], [], [], []
        # os maiores primeiro: pegam o lugar dos nomes antes dos vizinhos pequenos
        for mid, name, g in sorted(projected, key=lambda m: -m[2].area):
            g = polygonal(to_px(g).simplify(0.4))  # o resto da simplificação, já em px
            if g.is_empty:
                continue
            parts = list(g.geoms) if hasattr(g, "geoms") else [g]
            main = max(parts, key=lambda p: p.area)
            pole = polylabel(main, tolerance=0.5)
            m = {"id": mid, "name": name, "abbr": (codes or {}).get(mid) or abbr(mid, name), "d": svg_path(g)}
            fit = fit_text(main, candidates(main, pole), m["abbr"], taken)
            if fit:
                m["label"] = {"x": round(fit[0], 1), "y": round(fit[1], 1), "size": fit[2]}
            else:
                co = {"m": m, "tx": round(pole.x, 1), "ty": round(pole.y, 1)}
                (left if pole.x < ox + mw / 2 else right).append(co)
            out.append(m)
        return out, left, right, (ox, oy, ox + mw, oy + mh)

    # 1ª passada sem margem, para saber de que lado vão nomes com traço; a 2ª
    # abre a margem só desses lados (o mapa encolhe um pouco)
    out, left, right, _ = attempt(0, 0)
    if left or right:
        out, left, right, (ax0, ay0, ax1, ay1) = attempt(GUTTER if left else 0, GUTTER if right else 0)
        place_callouts(left, ax0 - 10, MAP[1] + 6, MAP[3])
        place_callouts(right, ax1 + 10, MAP[1] + 6, MAP[3])
        for side, items in (("left", left), ("right", right)):
            for co in items:
                co["m"]["callout"] = {"side": side, "x": co["x"], "y": round(co["y"], 1), "size": CALLOUT_SIZE,
                                      "tx": co["tx"], "ty": co["ty"], "path": trace(co, side)}
    return {"members": out, "list": lst, "dropped": dropped}


@disk_cached
def continent(boards_db, geo_db, slug, lang):
    spec = CONTINENTS[slug]
    con = _db(boards_db)
    cont = {r["country_id"]: (r["continent"], r["subregion"]) for r in con.execute("SELECT * FROM continents")}
    codes = {r["country_id"]: r["iso3"] for r in con.execute("SELECT country_id, iso3 FROM continents") if r["iso3"]}
    names = dict(_db(geo_db).execute(f"SELECT id, {'COALESCE(name_en, name)' if lang == 'en' else 'name'} FROM countries"))
    frame = box(*spec["bbox"])
    members, off = [], []
    for r in con.execute("SELECT id, geom FROM shapes WHERE kind = 'country'"):
        cid = r["id"]
        if cid.startswith("X") and cid != "XK":  # áreas disputadas do Overture (XA…XZ), não países
            continue
        c, s = cont.get(cid, (None, None))
        is_member = (cid == MEXICO and slug == "north-america") or (cid != MEXICO and c is not None and spec["match"](c, s))
        g = from_wkb(r["geom"])
        if c is None:  # sem continente no Natural Earth: o recorte mais justo que contém o ponto central
            pt = g.representative_point()
            fits = [k for k, v in CONTINENTS.items() if box(*v["bbox"]).contains(pt)]
            is_member = bool(fits) and min(fits, key=lambda k: box(*CONTINENTS[k]["bbox"]).area) == slug
        if is_member:
            (members if g.intersects(frame) else off).append((cid, names.get(cid, cid), g))
    title = spec[lang if lang == "en" else "pt"]
    out = build(spec["bbox"], members, [n for _, n, _ in members + off], title, codes=codes, prune=spec.get("prune"))
    off = [(i, n) for i, n, _ in off] + out.pop("dropped")
    out.update(kind="continent", id=slug, title=title, member_kind="country",
               off=[{"id": i, "name": n, "abbr": codes.get(i) or abbr(i, n)} for i, n in sorted(off, key=lambda x: x[1])])
    return out


def continent_of(boards_db, cid):
    """Slug do quadro de continente em que o país está (para a navegação)."""
    if cid == MEXICO:
        return "north-america"
    r = _db(boards_db).execute("SELECT continent, subregion FROM continents WHERE country_id = ?", (cid,)).fetchone()
    return next((slug for slug, spec in CONTINENTS.items() if r and spec["match"](r[0], r[1])), None)


@disk_cached
def country(boards_db, geo_db, cid, lang):
    con = _db(boards_db)
    geo = _db(geo_db)
    row = con.execute("SELECT geom FROM shapes WHERE kind = 'country' AND id = ?", (cid,)).fetchone()
    if row is None:
        return None
    shape_c = from_wkb(row["geom"])
    bbox = main_bbox(shape_c)
    frame = box(*bbox)
    names = dict(geo.execute("SELECT id, name FROM states WHERE country_id = ?", (cid,)))
    members, off = [], []
    for r in con.execute("SELECT id, geom FROM shapes WHERE kind = 'state' AND country_id = ?", (cid,)):
        g = from_wkb(r["geom"])
        (members if g.intersects(frame) else off).append((r["id"], names.get(r["id"], r["id"]), g))
    title = geo.execute(f"SELECT {'COALESCE(name_en, name)' if lang == 'en' else 'name'} FROM countries WHERE id = ?",
                        (cid,)).fetchone()
    title = title[0] if title else cid
    if not members:  # país sem estados: ele mesmo é a única porção
        members = [(cid, title, shape_c)]
    out = build(bbox, members, [n for _, n, _ in members + off], title)
    out.pop("dropped")
    out.update(kind="country", id=cid, title=title, member_kind="state" if names else "country",
               off=[{"id": i, "name": n, "abbr": abbr(i, n)} for i, n, _ in off])
    return out
