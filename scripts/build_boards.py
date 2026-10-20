"""Gera geodata/boards.db: contornos simplificados para os quadros (/quadros).

Os quadros são desenhos estáticos (um continente com seus países, um país com
seus estados), então não precisam da resolução do mapa: cada contorno é
simplificado para a escala do quadro e guardado em WKB. Lê os contornos
recortados pelo litoral da montagem (geodata/work/clipped_*.geojsonl) e o
continente/sub-região de cada país do Natural Earth (geodata/raw).

  countries   tolerância 0,01° (~1 km): quadros de continente
  states      tolerância 0,002° (~200 m): quadros de país

Lê linha a linha (um país inteiro chega a 70 MB de JSON), com o leitor em C
do shapely; a simplificação é a comum (Douglas-Peucker: a que preserva a
topologia leva 1 min só na Rússia) e o make_valid conserta o resto.
Uso: python scripts/build_boards.py  (~3 min; --continents refaz só os continentes)
"""
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import shapely
from shapely.geometry import MultiPolygon, Polygon

ROOT = Path(__file__).resolve().parent.parent
GEODATA = ROOT / "geodata"
WORK = GEODATA / "work"
OUT = GEODATA / "boards.db"
TOLERANCE = {"countries": 0.01, "states": 0.002}


def continents():
    """ISO → (continente, sub-região, código de 3 letras) do Natural Earth 10m."""
    d = json.loads((GEODATA / "raw" / "ne_10m_admin_0_countries.geojson").read_text())
    best = {}
    for f in d["features"]:
        p = f["properties"]
        iso = p.get("ISO_A2_EH") if p.get("ISO_A2") in (None, "-99") else p["ISO_A2"]
        if not iso or iso == "-99":
            continue
        # o mesmo código aparece em ilhas avulsas (Clipperton é FR, "Seven
        # seas"): vale o país em si, o mais populoso
        rank = (p["CONTINENT"] != "Seven seas (open ocean)", p.get("POP_EST") or 0)
        if iso not in best or rank > best[iso][0]:
            iso3 = p.get("ISO_A3") if p.get("ISO_A3") not in (None, "-99") else p.get("ADM0_A3")
            best[iso] = (rank, (p["CONTINENT"], p["SUBREGION"], iso3))
    return {iso: v for iso, (_, v) in best.items()}


PROPS = re.compile(r'"properties":\s*(\{[^}]*\})')


def polygons(g, tol):
    """Só as partes de área (o make_valid pode deixar linhas), sem as ilhotas
    menores que a própria tolerância."""
    parts = [q for p in getattr(g, "geoms", [g]) for q in getattr(p, "geoms", [p])
             if isinstance(q, Polygon) and q.area > (tol / 2) ** 2]
    return MultiPolygon(parts) if parts else None


def main():
    if "--continents" in sys.argv:  # só refaz a tabela de continentes
        con = sqlite3.connect(OUT)
        con.execute("DROP TABLE IF EXISTS continents")
        con.execute("CREATE TABLE continents (country_id TEXT PRIMARY KEY, continent TEXT, subregion TEXT, iso3 TEXT)")
        con.executemany("INSERT INTO continents VALUES (?, ?, ?, ?)", [(k, *v) for k, v in continents().items()])
        con.commit()
        return
    tmp = OUT.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript("""
        CREATE TABLE shapes (kind TEXT, id TEXT, country_id TEXT, geom BLOB, PRIMARY KEY (kind, id));
        CREATE INDEX shapes_country ON shapes(country_id);
        CREATE TABLE continents (country_id TEXT PRIMARY KEY, continent TEXT, subregion TEXT, iso3 TEXT);
    """)
    con.executemany("INSERT INTO continents VALUES (?, ?, ?, ?)", [(k, *v) for k, v in continents().items()])
    t = time.time()
    for layer, tol in TOLERANCE.items():
        n = 0
        with open(WORK / f"clipped_{layer}.geojsonl") as f:
            for line in f:
                p = json.loads(PROPS.search(line[:2000]).group(1))
                fid = p.get("id") or p.get("oid")
                g = polygons(shapely.make_valid(shapely.from_geojson(line).simplify(tol, preserve_topology=False)), tol)
                if g is None:
                    continue
                con.execute("INSERT OR REPLACE INTO shapes VALUES (?, ?, ?, ?)",
                            (layer[:-1] if layer == "states" else "country", fid, p.get("country"), g.wkb))
                n += 1
                if n % 200 == 0:
                    print(f"{layer}: {n} ({time.time() - t:.0f} s)", file=sys.stderr, flush=True)
        con.commit()
    con.execute("VACUUM")
    con.close()
    tmp.replace(OUT)
    print(f"{OUT}: {OUT.stat().st_size / 1e6:.1f} MB em {time.time() - t:.0f} s")


if __name__ == "__main__":
    main()
