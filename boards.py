"""Quadros de raspar (/quadros): desenhos estáticos no estilo dos pôsteres.

Um quadro é um recorte fixo: um continente com seus países, ou um país com
seus estados. Nada de zoom: o servidor projeta os contornos (boards.db, gerado
por scripts/build_boards.py) num retângulo de tamanho fixo e decide onde vai
cada nome. Cabe dentro da porção: o nome fica no centro dela (o ponto mais
longe da borda). Não cabe: o nome vai para a margem do quadro, ligado à porção
por um traço. O navegador só desenha (SVG) e pinta o que foi raspado.

Os quadros não mudam (só com uma nova montagem): cada um é calculado uma vez
por idioma e guardado em memória.
"""
import math
import sqlite3
from functools import lru_cache
from pathlib import Path

from shapely import box, clip_by_rect, from_wkb
from shapely.ops import polylabel
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import transform

W = 1000          # largura da área do mapa (px do SVG)
MAX_H = 1100      # altura máxima (países compridos, como o Chile, ficam mais estreitos)
GUTTER = 190      # margem de cada lado, para os nomes com traço
PAD = 18
LABEL_SIZES = (20, 17, 14.5, 12.5)
CALLOUT_SIZE = 14
CALLOUT_GAP = 17  # distância mínima entre nomes na margem

# Continentes (a América em três). bbox fixo [oeste, sul, leste, norte]; os
# membros vêm do Natural Earth (continente/sub-região). O México fica na do
# Norte, o Caribe na Central.
CONTINENTS = {
    "america-do-norte": {"pt": "América do Norte", "en": "North America", "bbox": (-170, 13, -50, 72),
                         "match": lambda c, s: s == "Northern America" or c == "North America" and s not in ("Central America", "Caribbean")},
    "america-central": {"pt": "América Central e Caribe", "en": "Central America & Caribbean", "bbox": (-93, 6.5, -59, 27),
                        "match": lambda c, s: s in ("Central America", "Caribbean")},
    "america-do-sul": {"pt": "América do Sul", "en": "South America", "bbox": (-82, -56, -34, 13),
                       "match": lambda c, s: c == "South America"},
    "europa": {"pt": "Europa", "en": "Europe", "bbox": (-25, 34, 45, 71.5),
               "match": lambda c, s: c == "Europe"},
    "africa": {"pt": "África", "en": "Africa", "bbox": (-26, -36, 60, 38),
               "match": lambda c, s: c == "Africa"},
    "asia": {"pt": "Ásia", "en": "Asia", "bbox": (25, -11, 150, 56),
             "match": lambda c, s: c == "Asia"},
    "oceania": {"pt": "Oceania", "en": "Oceania", "bbox": (110, -48, 180, 2),
                "match": lambda c, s: c == "Oceania"},
}
MEXICO = "MX"  # o Natural Earth põe na América Central


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


def fit_text(poly, cx, cy, name, sizes=LABEL_SIZES):
    """Tamanho e linhas que cabem dentro do polígono, centrados em (cx, cy)."""
    words = name.split()
    options = [[name]]
    if len(words) > 1:  # quebra em duas linhas no espaço mais perto do meio
        best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        options.append([" ".join(words[:best]), " ".join(words[best:])])
    inner = poly.buffer(-1.5)
    for size in sizes:
        for lines in options:
            w = max(len(t) for t in lines) * size * 0.58
            h = len(lines) * size * 1.15
            r = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            # como nos pôsteres: pode passar um pouco da borda (Itália, Noruega)
            if inner.intersection(r).area >= 0.75 * r.area:
                return size, lines
    return None


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


def build(bbox, members, context):
    """members: [(id, nome, geom)] raspáveis; context: [geom] em volta (apagados)."""
    # Recorta depois de projetar: o quadro é um retângulo na projeção (o bbox
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
    ctx = [c for g in context if (c := clip(g)) is not None]
    scale = min(W / (x1 - x0), MAX_H / (y1 - y0))
    h = (y1 - y0) * scale
    mw = (x1 - x0) * scale
    ox = GUTTER
    to_px = lambda g: transform(lambda x, y, z=None: (ox + (x - x0) * scale, PAD + (y1 - y) * scale), g)
    width, height = mw + 2 * GUTTER, h + 2 * PAD

    out_members, left, right = [], [], []
    for mid, name, g in projected:
        g = polygonal(to_px(g).simplify(0.4))  # o resto da simplificação, já em px
        if g.is_empty:
            continue
        parts = list(g.geoms) if hasattr(g, "geoms") else [g]
        main = max(parts, key=lambda p: p.area)
        pole = polylabel(main, tolerance=0.5)
        m = {"id": mid, "name": name, "d": svg_path(g)}
        fit = fit_text(main, pole.x, pole.y, name)
        if fit:
            m["label"] = {"x": round(pole.x, 1), "y": round(pole.y, 1), "size": fit[0], "lines": fit[1]}
        else:
            co = {"m": m, "tx": round(pole.x, 1), "ty": round(pole.y, 1)}
            (left if pole.x < ox + mw / 2 else right).append(co)
        out_members.append(m)
    # os nomes de fora ficam logo ao lado do mapa (não na borda do quadro)
    place_callouts(left, ox - 10, PAD + 6, height - PAD)
    place_callouts(right, ox + mw + 10, PAD + 6, height - PAD)
    for side, items in (("left", left), ("right", right)):
        for co in items:
            co["m"]["callout"] = {"side": side, "x": co["x"], "y": round(co["y"], 1), "tx": co["tx"], "ty": co["ty"],
                                  "size": CALLOUT_SIZE}
    # margem sem nenhum nome fica de fora do desenho (viewBox começa em x)
    cut_l = 0 if left else GUTTER - PAD
    cut_r = 0 if right else GUTTER - PAD
    return {"x": cut_l, "width": round(width - cut_l - cut_r), "height": round(height),
            "context": [svg_path(to_px(g).simplify(0.6)) for g in ctx], "members": out_members}


@lru_cache(maxsize=64)
def continent(boards_db, geo_db, slug, lang):
    spec = CONTINENTS[slug]
    con = _db(boards_db)
    cont = {r["country_id"]: (r["continent"], r["subregion"]) for r in con.execute("SELECT * FROM continents")}
    names = dict(_db(geo_db).execute(f"SELECT id, {'COALESCE(name_en, name)' if lang == 'en' else 'name'} FROM countries"))
    frame = box(*spec["bbox"])
    members, context, off = [], [], []
    for r in con.execute("SELECT id, geom FROM shapes WHERE kind = 'country'"):
        cid = r["id"]
        c, s = cont.get(cid, (None, None))
        is_member = (cid == MEXICO and slug == "america-do-norte") or (cid != MEXICO and c is not None and spec["match"](c, s))
        g = from_wkb(r["geom"])
        if c is None and g.intersects(frame):  # sem continente no Natural Earth: pelo ponto central
            is_member = frame.contains(g.representative_point())
        if is_member:
            (members if g.intersects(frame) else off).append((cid, names.get(cid, cid), g))
        elif g.intersects(frame):
            context.append(g)
    out = build(spec["bbox"], members, context)
    out.update(kind="continent", id=slug, title=spec[lang if lang == "en" else "pt"], member_kind="country",
               off=[{"id": i, "name": n} for i, n, _ in off])
    return out


def continent_of(boards_db, cid):
    """Slug do quadro de continente em que o país está (para a navegação)."""
    if cid == MEXICO:
        return "america-do-norte"
    r = _db(boards_db).execute("SELECT continent, subregion FROM continents WHERE country_id = ?", (cid,)).fetchone()
    return next((slug for slug, spec in CONTINENTS.items() if r and spec["match"](r[0], r[1])), None)


@lru_cache(maxsize=128)
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
    context = [g for r in con.execute("SELECT id, geom FROM shapes WHERE kind = 'country' AND id != ?", (cid,))
               if (g := from_wkb(r["geom"])).intersects(frame)]
    title = geo.execute(f"SELECT {'COALESCE(name_en, name)' if lang == 'en' else 'name'} FROM countries WHERE id = ?",
                        (cid,)).fetchone()
    title = title[0] if title else cid
    if not members:  # país sem estados: ele mesmo é a única porção
        members = [(cid, title, shape_c)]
    out = build(bbox, members, context)
    out.update(kind="country", id=cid, title=title, member_kind="state" if names else "country",
               off=[{"id": i, "name": n} for i, n, _ in off])
    return out
