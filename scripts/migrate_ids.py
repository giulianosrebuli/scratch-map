#!/usr/bin/env python3
"""Converte visitas e fotos de estados/países para os ids de um novo geo.db.

Usado na troca do Natural Earth (ids adm1_code, ex. BRA-627) pelo Overture
(ISO 3166-2, ex. BR-RJ). Para cada estado/país marcado direto, acha no geo.db
novo o de maior sobreposição com o polígono antigo. Também apaga os contornos
de cidade antigos (Nominatim), que o app recalcula a partir do Overture.

Faz backup de data/scratch.db antes. Mostra o de-para para conferir.

Uso:  venv/bin/python scripts/migrate_ids.py OLD_COUNTRIES.geojson OLD_STATES.geojson [--apply]
"""
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_geodata import GEO_DB, LOOKUP_TOL, WORK, features  # noqa: E402

DATA = Path(os.environ.get("SCRATCH_DATA", ROOT / "data"))
DB = DATA / "scratch.db"


def load_new(layer):
    ids, geoms = [], []
    for props, g in features(WORK / f"clipped_{layer}.geojsonl"):
        for p in shapely.get_parts(shapely.make_valid(shapely.simplify(g, LOOKUP_TOL, preserve_topology=False))):
            ids.append(props["id"])
            geoms.append(p)
    return ids, geoms, STRtree(geoms)


def best_match(old_geom, new):
    ids, geoms, tree = new
    score = {}
    for i in tree.query(old_geom):
        try:
            a = geoms[i].intersection(old_geom).area
        except shapely.errors.GEOSException:
            a = shapely.make_valid(geoms[i]).intersection(shapely.make_valid(old_geom)).area
        if a > 0:
            score[ids[i]] = score.get(ids[i], 0) + a
    return max(score, key=score.get) if score else None


def main():
    old_countries, old_states, apply = sys.argv[1], sys.argv[2], "--apply" in sys.argv
    con = sqlite3.connect(DB)
    geo = sqlite3.connect(GEO_DB)
    new_names = {("country", r[0]): r[1] for r in geo.execute("SELECT id, name FROM countries")}
    new_names |= {("state", r[0]): r[1] for r in geo.execute("SELECT id, name FROM states")}

    used = {}
    for kind in ("country", "state"):
        for (ref,) in con.execute("""SELECT ref_id FROM visits WHERE kind = ?
                                     UNION SELECT ref_id FROM photos WHERE kind = ?""", (kind, kind)):
            used[(kind, ref)] = None
    if not used:
        print("nada a migrar")
    olds = {}
    for kind, path in (("country", old_countries), ("state", old_states)):
        for f in json.load(open(path))["features"]:
            if (kind, str(f["properties"]["id"])) in used:
                olds[(kind, str(f["properties"]["id"]))] = (f["properties"].get("name"), shape(f["geometry"]))

    new = {}
    mapping = {}
    for (kind, ref) in used:
        if (kind, ref) in new_names:  # id continua valendo (ex.: país ISO)
            mapping[(kind, ref)] = ref
            continue
        if (kind, ref) not in olds:
            print(f"!! {kind} {ref}: não está nos polígonos antigos, fica como está")
            continue
        layer = "countries" if kind == "country" else "states"
        if layer not in new:
            new[layer] = load_new(layer)
        mapping[(kind, ref)] = best_match(olds[(kind, ref)][1], new[layer])

    print("de-para:")
    for (kind, ref), to in sorted(mapping.items()):
        old_name = olds.get((kind, ref), (ref,))[0]
        print(f"  {kind:7} {ref:12} {old_name or '':28} -> {to} {new_names.get((kind, to), '??')}")
    n_shapes = con.execute("SELECT COUNT(*) FROM city_shapes").fetchone()[0]
    print(f"contornos de cidade antigos a apagar: {n_shapes}")
    if not apply:
        print("\nnada alterado (use --apply)")
        return

    backup = DB.with_name(f"scratch.db.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    con.close()
    shutil.copy2(DB, backup)
    con = sqlite3.connect(DB)
    for (kind, ref), to in mapping.items():
        if not to or to == ref:
            continue
        con.execute("INSERT OR IGNORE INTO visits (kind, ref_id, created_at) SELECT kind, ?, created_at FROM visits WHERE kind = ? AND ref_id = ?",
                    (to, kind, ref))
        con.execute("DELETE FROM visits WHERE kind = ? AND ref_id = ?", (kind, ref))
        con.execute("UPDATE photos SET ref_id = ? WHERE kind = ? AND ref_id = ?", (to, kind, ref))
    con.execute("DELETE FROM city_shapes")
    con.commit()
    print(f"aplicado (backup em {backup})")


if __name__ == "__main__":
    main()
