"""scratch-map — mapa pessoal de lugares visitados, com fotos.

Backend Flask + SQLite. Dois bancos:
  geodata/geo.db   referência (países, estados, cidades, aeroportos) — gerado por
                   scripts/build_geodata.py, somente leitura
  data/profiles/<id>/scratch.db  os dados de cada perfil (visitas e fotos) — é
                   o que importa fazer backup, junto com as fotos (profiles.py)
"""
import datetime as dt
import gzip
import json
import logging
import math
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path

from flask import (Flask, abort, g, has_request_context, jsonify, redirect, render_template, request, send_file,
                   send_from_directory)
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from shapely.geometry import Point, shape

import boundaries
import i18n
import installer
import profiles
import version
import flags as state_flags  # o nome "flags" já é uma função aqui

register_heif_opener()  # fotos .HEIC do iPhone

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("SCRATCH_DATA", ROOT / "data"))
GEODATA = Path(os.environ.get("SCRATCH_GEODATA", ROOT / "geodata"))
GEO_DB = GEODATA / "geo.db"
TILES = GEODATA / "world.pmtiles"
KINDS = ("country", "state", "city", "airport")   # o que pode ser marcado (visits)
PHOTO_KINDS = KINDS + ("landmark",)                # o que pode ter foto
DISPLAY_PX = 2000  # lado maior da versão exibida
THUMB_PX = 600

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 ** 3  # o backup (restaurar) é o maior envio

SCHEMA = """
-- configurações da instância (por enquanto editadas à mão; ver README)
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS visits (
    kind TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (kind, ref_id)
);
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    file TEXT NOT NULL,          -- nome base (uuid); ver photo_paths()
    original_name TEXT,
    original_ext TEXT,
    taken_on TEXT,               -- AAAA-MM-DD (só data, sem hora)
    width INTEGER,
    height INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS photos_place ON photos(kind, ref_id);
-- Landmark: ponto criado a partir de uma foto (só existe enquanto tiver foto).
CREATE TABLE IF NOT EXISTS landmarks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    lat REAL,
    lon REAL,
    city_id INTEGER,             -- cidade mais próxima (só para exibir; não marca nada)
    draft INTEGER NOT NULL DEFAULT 1,  -- 1 enquanto o formulário de criação não foi salvo
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
""" + boundaries.SCHEMA + state_flags.SCHEMA


def prof():
    """O perfil desta requisição (pick_profile), com os caminhos dos dados dele."""
    return g.prof


def each_profile(fn):
    """fn() uma vez para cada perfil, com prof() e db() apontando para ele."""
    for p in profiles.list_all():
        with app.app_context():
            g.prof = p
            fn()


def init_storage():
    for d in (prof().dir, prof().photos / "orig", prof().photos / "display", prof().photos / "thumb",
              prof().photos / "trash"):
        d.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(prof().db) as con:
        con.executescript(SCHEMA)
        con.row_factory = sqlite3.Row
        # rascunho de landmark abandonado (fechou a página no meio): fotos vão pro trash
        old = con.execute("""SELECT id FROM landmarks
                             WHERE draft = 1 AND created_at < datetime('now', '-1 day')""").fetchall()
        for r in old:
            delete_landmark_rows(con, r["id"])


def geo_ready():
    """O que depende dos dados do mapa, em segundo plano: bandeiras de estado dos
    países visitados e contornos de cidade que faltam, de cada perfil. Na
    subida, ou quando a montagem da primeira execução termina."""
    each_profile(geo_ready_profile)


def geo_ready_profile():
    fetch_state_flags()
    if not app.config.get("TESTING"):
        boundaries.start_backfill(prof().db, GEO_DB, allow_nominatim=ext_on("ext_city_shape"))


_installed = False


def installed():
    """Assistente concluído e dados do mapa prontos (installer.py)."""
    global _installed
    if not _installed and installer.done() and installer.ready():
        _installed = True
        geo_ready()
    return _installed


def db():
    if "db" not in g:
        g.db = sqlite3.connect(prof().db)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        if GEO_DB.exists():  # na primeira execução, só depois da montagem
            g.db.execute(f"ATTACH DATABASE 'file:{GEO_DB}?mode=ro' AS geo")
            # países no idioma da interface; estados e cidades ficam com o nome de lá
            en = lang() != "pt-BR" and g.db.execute(
                "SELECT 1 FROM pragma_table_info('countries', 'geo') WHERE name = 'name_en'").fetchone()
            g.db.execute(f"""CREATE TEMP VIEW countries AS SELECT id, {'COALESCE(name_en, name)' if en else 'name'}
                             AS name, search, x0, y0, x1, y1 FROM geo.countries""")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    con = g.pop("db", None)
    if con is not None:
        con.close()


# Visitados = marcados explicitamente + implícitos.
# Cidade marca estado e país; estado marca país. Aeroporto não marca nada.
VISITED_STATES_SQL = """
    SELECT ref_id AS id FROM visits WHERE kind = 'state'
    UNION
    SELECT c.state_id FROM visits v JOIN geo.cities c ON c.id = v.ref_id
     WHERE v.kind = 'city' AND c.state_id IS NOT NULL
"""
VISITED_COUNTRIES_SQL = """
    SELECT ref_id AS id FROM visits WHERE kind = 'country'
    UNION
    SELECT s.country_id FROM visits v JOIN geo.states s ON s.id = v.ref_id WHERE v.kind = 'state'
    UNION
    SELECT c.country_id FROM visits v JOIN geo.cities c ON c.id = v.ref_id
     WHERE v.kind = 'city' AND c.country_id IS NOT NULL
"""


def photo_counts():
    return {(r["kind"], r["ref_id"]): r["n"] for r in db().execute(
        "SELECT kind, ref_id, COUNT(*) n FROM photos GROUP BY kind, ref_id")}


def explicit_set():
    return {(r["kind"], r["ref_id"]) for r in db().execute("SELECT kind, ref_id FROM visits")}


def visited_set():
    """Tudo o que conta como visitado (marcado ou implícito por uma cidade/estado)."""
    con = db()
    out = explicit_set()
    out |= {("state", r[0]) for r in con.execute(VISITED_STATES_SQL)}
    out |= {("country", r[0]) for r in con.execute(VISITED_COUNTRIES_SQL)}
    return out


def flags(kind, ref_id, ex, vis):
    return {"explicit": (kind, str(ref_id)) in ex, "visited": (kind, str(ref_id)) in vis}


@app.after_request
def compress(resp):
    """JSON grande vai comprimido (os contornos de cidade são ~4 MB crus, ~1 MB
    em gzip): faz diferença fora de casa, pela tailnet."""
    if (resp.mimetype == "application/json" and not resp.direct_passthrough
            and "gzip" in request.headers.get("Accept-Encoding", "")
            and "Content-Encoding" not in resp.headers):
        data = resp.get_data()
        if len(data) > 2048:
            resp.set_data(gzip.compress(data, compresslevel=6))
            resp.headers["Content-Encoding"] = "gzip"
            resp.headers["Vary"] = "Accept-Encoding"
    return resp


# ------------------------------------------------------------------ app instalável (PWA)
# Manifesto, service worker (static/sw.js, servido da raiz para valer no site
# todo) e a página "sem conexão" que ele guarda. Ícone: static/icons/.
PWA_PATHS = ("/manifest.webmanifest", "/sw.js", "/offline")


@app.get("/manifest.webmanifest")
def web_manifest():
    icons = [{"src": f"/static/icons/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png", "purpose": purpose}
             for n in (192, 512) for purpose in ("any", "maskable")]
    resp = jsonify(id="/", name="Scratch Map", short_name="Scratch Map", lang=lang(),
                   description=tr("Seu mapa de raspar: os lugares por onde passou, com as fotos de cada um."),
                   start_url="/", scope="/", display="standalone", orientation="any",
                   background_color="#0f1830", theme_color="#fbf8f2", icons=icons)
    resp.mimetype = "application/manifest+json"
    return resp


@app.get("/sw.js")
def service_worker():
    resp = send_from_directory(ROOT / "static", "sw.js", mimetype="text/javascript", max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/offline")
def offline():
    return render_template("offline.html")


# ------------------------------------------------------------------ primeira execução
# Enquanto o assistente não terminou (ou o mapa está sendo montado), tudo leva a
# /setup. Ficam abertos o que o assistente usa: perfil, preferências, restaurar.
SETUP_OPEN = ("/setup", "/api/setup", "/static/", "/api/restore", "/api/settings",
              "/api/profile/photo", "/profile.jpg") + PWA_PATHS


# Perfis (profiles.py): o do cookie; com um perfil só, ele mesmo. Com vários e
# nenhum escolhido, a tela de escolha (que usa o primeiro só para idioma e tema).
PROFILE_FREE = ("/static/", "/perfis") + PWA_PATHS


@app.before_request
def pick_profile():
    p = profiles.get(request.cookies.get(profiles.COOKIE))
    if p is None:
        every = profiles.list_all()
        if len(every) == 1 or request.path.startswith(PROFILE_FREE):
            p = every[0]
        elif request.path.startswith("/api/"):
            abort(409, "escolha um perfil em /perfis")
        else:
            return redirect("/perfis")
    g.prof = p
    return None


@app.before_request
def setup_gate():
    if installed() or request.path.startswith(SETUP_OPEN):
        return None
    if request.path.startswith("/api/"):
        abort(503, "instalação em andamento")
    return redirect("/setup")


@app.get("/setup")
def setup_page():
    # depois de instalado, só para um perfil novo (setup_pending): sem a parte
    # dos dados do mapa, que já estão prontos
    if installed() and not settings().get("setup_pending"):
        return redirect("/")
    return render_template("setup.html", settings=settings(), state=installer.state(),
                           counts=backup_counts(db()), new_profile=installed())


@app.get("/api/setup")
def setup_state():
    return jsonify(installer.state() | {"installed": installed(), "counts": backup_counts(db())})


@app.post("/api/setup/start")
def setup_start():
    """Fim do assistente: começa (ou retoma, depois de um erro) a montagem."""
    mode = (request.get_json(force=True) or {}).get("mode")
    if mode not in installer.MODES:
        abort(400, "modo inválido")
    if installer.done() and installer.ready():
        abort(409, "já instalado")
    installer.start(mode)
    return setup_state()


@app.get("/")
def index():
    if settings().get("setup_pending"):  # perfil novo chegou ao mapa: assistente concluído
        set_setting("setup_pending", None)
        db().commit()
    # versão dos tiles = mtime; muda quando o build_geodata roda e fura o cache do navegador
    geo_v = int(TILES.stat().st_mtime)
    return render_template("index.html", geo_v=geo_v, settings=settings())


def settings():
    """Configurações da instância (tabela settings). Ver prefs() e a página
    /config. Vista inicial do mapa: start_view = country (cidades visitadas em
    home_country) | all | last (onde parou, por aparelho) | fixed (start_fixed
    = "lon,lat,zoom"); sem start_view, country se houver home_country, senão all."""
    return {r["key"]: r["value"] for r in db().execute("SELECT key, value FROM settings")}


@app.get("/mural")
def mural():
    return render_template("mural.html")


# ------------------------------------------------------------------ preferências e perfil
# Ficam na tabela settings do perfil (profiles.py): valem em todos os
# aparelhos. theme: light | dark | auto (segue o sistema). color_<tipo>: cor do
# mapa (sem a chave = padrão do CSS). profile_name; profile_photo = versão da
# foto (profile.jpg do perfil), para furar o cache do navegador. Vista inicial:
# start_view, home_country, start_fixed (ver settings()).
THEMES = ("light", "dark", "auto")
LANGUAGES = tuple(i18n.LANGS)
START_VIEWS = ("country", "all", "last", "fixed")
PROJECTIONS = ("mercator", "globe")
# O que sai da máquina, cada um com liga/desliga na configuração (ligado por
# padrão; desligado = "0" na tabela settings).
EXTERNAL = ("ext_landmark_name", "ext_city_shape", "ext_state_flags")
# Bordas no mapa (linha branca): "1"/"0"; sem a chave, o padrão daqui.
BORDERS = {"borders_country": True, "borders_state": True, "borders_city": False}


def ext_on(key, con=None):
    r = (con or db()).execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return not r or r[0] != "0"
MAP_COLORS = {  # mesmos padrões do :root em static/app.css
    "water": "#86b9dc", "land": "#8db37c", "country": "#f2b143", "state": "#e5705b",
    "city": "#6a4bc0", "airport": "#1f3a68", "landmark": "#0d7f73",
}


def prefs():
    st = settings()
    return {
        "theme": st.get("theme") if st.get("theme") in THEMES else "light",
        "colors": {k: st[f"color_{k}"] for k in MAP_COLORS if st.get(f"color_{k}")},
        "name": st.get("profile_name", ""),
        "photo": st.get("profile_photo"),
        "projection": st.get("projection") if st.get("projection") in PROJECTIONS else "mercator",
        "external": {k: st.get(k) != "0" for k in EXTERNAL},
        "borders": {k: st[k] == "1" if k in st else d for k, d in BORDERS.items()},
    }


def lang():
    """Idioma da interface: o escolhido (language); no assistente, antes de
    escolher, o do navegador; instalação de antes da tradução, português."""
    if "lang" not in g:
        st = settings()
        chosen = st.get("language")
        if chosen in LANGUAGES:
            g.lang = chosen
        elif has_request_context() and (not installer.done() or st.get("setup_pending")):
            g.lang = i18n.from_header(request.headers.get("Accept-Language"))
        else:
            g.lang = i18n.DEFAULT
    return g.lang


def tr(text, **kw):
    return i18n.t(text, lang(), **kw)


@app.template_filter("day")
def fmt_day(iso):
    """'2026-10-09...' -> 09/10/2026 (pt-BR) ou Oct 9, 2026 (en)."""
    if not iso:
        return ""
    d = dt.date.fromisoformat(str(iso)[:10])
    return d.strftime("%d/%m/%Y") if lang() == "pt-BR" else f"{d:%b} {d.day}, {d.year}"


@app.context_processor
def inject_prefs():
    # tema, cores e idioma entram no <head> de todas as páginas (templates/_head.html)
    return {"prefs": prefs(), "map_colors": MAP_COLORS, "_": tr, "lang": lang(),
            "i18n_table": i18n.table(lang()), "languages": i18n.LANGS,
            "profile_id": prof().id, "profile_count": len(profiles.list_all())}


def valid_view(value):
    """"lon,lat,zoom" dentro dos limites do mapa (ou None)."""
    if value is None:
        return True
    try:
        lon, lat, zoom = (float(x) for x in str(value).split(","))
    except ValueError:
        return False
    return -540 <= lon <= 540 and -90 <= lat <= 90 and 0 <= zoom <= 14


def set_setting(key, value):
    if value is None:
        db().execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        db().execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


@app.patch("/api/settings")
def patch_settings():
    """Grava preferências. `null` volta ao padrão. Chaves aceitas: theme,
    color_<tipo> (#rrggbb), profile_name, start_view, home_country,
    start_fixed, projection, language, ext_* e borders_* (true/false)."""
    import re
    body = request.get_json(force=True) or {}
    for key, value in body.items():
        if key == "theme" and (value in THEMES or value is None):
            set_setting(key, value)
        elif key.startswith("color_") and key[6:] in MAP_COLORS and (
                value is None or re.fullmatch(r"#[0-9a-fA-F]{6}", str(value))):
            set_setting(key, value and value.lower())
        elif key == "profile_name" and (value is None or isinstance(value, str)):
            set_setting(key, (value or "").strip()[:80] or None)
        elif key == "start_view" and (value in START_VIEWS or value is None):
            set_setting(key, value)
        elif key == "home_country" and (value is None or db().execute(
                "SELECT 1 FROM countries WHERE id = ?", (value,)).fetchone()):
            set_setting(key, value)
        elif key == "start_fixed" and valid_view(value):
            set_setting(key, value)
        elif key == "projection" and (value in PROJECTIONS or value is None):
            set_setting(key, value)
        elif key == "language" and (value in LANGUAGES or value is None):
            set_setting(key, value)
        elif key in EXTERNAL and isinstance(value, bool):
            set_setting(key, None if value else "0")
        elif key in BORDERS and isinstance(value, bool):
            set_setting(key, "1" if value else "0")
        else:
            abort(400, f"configuração inválida: {key}")
    db().commit()
    if body.get("ext_state_flags") is True:
        fetch_state_flags()  # religou: busca o que faltou
    return jsonify(prefs())


@app.post("/api/profile/photo")
def upload_profile_photo():
    """Foto de perfil: recorte quadrado do centro, 512 px."""
    f = request.files.get("photo") or abort(400)
    try:
        with Image.open(f.stream) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img = ImageOps.fit(img, (512, 512), Image.LANCZOS)
            img.save(prof().photo, "JPEG", quality=88, optimize=True)
    except Exception as e:
        abort(400, tr("imagem inválida: {erro}", erro=e))
    set_setting("profile_photo", uuid.uuid4().hex[:8])
    db().commit()
    return jsonify(prefs())


@app.delete("/api/profile/photo")
def delete_profile_photo():
    prof().photo.unlink(missing_ok=True)
    set_setting("profile_photo", None)
    db().commit()
    return jsonify(prefs())


@app.get("/profile.jpg")
def profile_photo():
    if not prof().photo.exists():
        abort(404)
    return send_file(prof().photo, mimetype="image/jpeg", max_age=30 * 86400)


# ------------------------------------------------------------------ perfis
# Tela "quem está usando?" (/perfis): escolher grava o cookie neste aparelho.
# Perfil novo passa pelo assistente sem a parte dos dados do mapa.
def use(resp, p):
    resp.set_cookie(profiles.COOKIE, p.id, max_age=10 * 365 * 86400, samesite="Lax")
    return resp


@app.get("/perfis")
def profiles_page():
    chosen = profiles.get(request.cookies.get(profiles.COOKIE))
    return render_template("perfis.html", people=[p.info() for p in profiles.list_all()],
                           chosen=chosen and chosen.id, can_add=installed())


@app.get("/perfis/<pid>/usar")
def use_profile(pid):
    return use(redirect("/"), profiles.get(pid) or abort(404))


@app.get("/perfis/<pid>/foto.jpg")
def profile_photo_of(pid):
    p = profiles.get(pid) or abort(404)
    if not p.photo.exists():
        abort(404)
    return send_file(p.photo, mimetype="image/jpeg", max_age=30 * 86400)


@app.post("/perfis/novo")
def new_profile():
    if not installed():
        abort(409, "instalação em andamento")
    p = profiles.create()
    with app.app_context():
        g.prof = p
        init_storage()
        set_setting("setup_pending", "1")
        db().commit()
    return use(redirect("/setup"), p)


@app.delete("/api/profile")
def delete_profile():
    """Apaga o perfil em uso (a pasta vai para data/profiles-removed/). O
    único perfil não pode ser apagado."""
    if len(profiles.list_all()) < 2:
        abort(409, tr("é o único perfil"))
    close_db(None)
    profiles.remove(prof())
    resp = jsonify(ok=True)
    resp.delete_cookie(profiles.COOKIE)
    return resp


# ------------------------------------------------------------------ backup
# Um .zip com tudo o que é seu: o banco (visitas, landmarks, fotos, configuração,
# contornos de cidade), as fotos (original + exibição + miniatura), as bandeiras
# baixadas e a foto de perfil. A lixeira de fotos fica de fora. Restaurar troca
# tudo pelo conteúdo do .zip, depois de guardar uma cópia do estado atual em
# backups/ do perfil.
BACKUP_DIRS = ("photos/orig", "photos/display", "photos/thumb", "flags")
BACKUP_FILES = ("manifest.json", "scratch.db", "profile.jpg")
KEEP_SAFETY = 5   # cópias "antes de restaurar" guardadas (as mais antigas saem)


def backup_counts(con):
    one = lambda q: con.execute(q).fetchone()[0]
    return {"visits": one("SELECT COUNT(*) FROM visits"), "photos": one("SELECT COUNT(*) FROM photos"),
            "landmarks": one("SELECT COUNT(*) FROM landmarks WHERE draft = 0")}


def write_backup(path):
    """Grava o .zip em path. O banco é copiado pela API de backup do SQLite
    (cópia consistente mesmo com o app no ar)."""
    with tempfile.TemporaryDirectory(dir=prof().dir) as tmp:
        dbcopy = Path(tmp) / "scratch.db"
        src, dst = sqlite3.connect(prof().db), sqlite3.connect(dbcopy)
        try:
            src.backup(dst)
            counts = backup_counts(dst)
        finally:
            src.close()
            dst.close()
        manifest = {"app": "scratch-map", "format": 1, "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                    **counts}
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
            z.write(dbcopy, "scratch.db", compress_type=zipfile.ZIP_DEFLATED)
            for part in BACKUP_DIRS:  # jpg/webp já são comprimidos: só guarda
                for f in sorted((prof().dir / part).glob("*")):
                    if f.is_file():
                        z.write(f, f"{part}/{f.name}")
            if prof().photo.exists():
                z.write(prof().photo, "profile.jpg")
    return manifest


@app.get("/api/backup/info")
def backup_info():
    size = prof().db.stat().st_size + sum(f.stat().st_size for part in BACKUP_DIRS
                                   for f in (prof().dir / part).glob("*") if f.is_file())
    return jsonify(**backup_counts(db()), bytes=size, last_backup=settings().get("last_backup"))


@app.get("/api/backup")
def download_backup():
    fd, tmp = tempfile.mkstemp(suffix=".zip", dir=prof().dir)
    os.close(fd)
    write_backup(tmp)
    set_setting("last_backup", dt.datetime.now().isoformat(timespec="seconds"))
    db().commit()
    # abre e já apaga do disco: o espaço é liberado quando o envio termina
    # (e não sobra arquivo se o download for interrompido)
    fh = open(tmp, "rb")
    os.unlink(tmp)
    return send_file(fh, mimetype="application/zip", as_attachment=True,
                     download_name=f"scratch-map-backup-{dt.date.today().isoformat()}.zip")


def backup_member_ok(name):
    """Só caminhos conhecidos (nada de ../ ou pastas fora de data/)."""
    if name in BACKUP_FILES or name.endswith("/"):
        return True
    folder, _, file = name.rpartition("/")
    return folder in BACKUP_DIRS and file not in ("", ".", "..") and "\\" not in file


@app.post("/api/restore")
def restore_backup():
    """Troca os dados pelos do .zip. Antes, guarda o estado atual em backups/ do perfil."""
    f = request.files.get("backup") or abort(400, tr("nenhum arquivo"))
    with tempfile.TemporaryDirectory(dir=prof().dir) as tmp:
        zpath = Path(tmp) / "in.zip"
        f.save(zpath)
        try:
            z = zipfile.ZipFile(zpath)
        except zipfile.BadZipFile:
            abort(400, tr("o arquivo não é um .zip"))
        with z:
            names = z.namelist()
            try:
                manifest = json.loads(z.read("manifest.json"))
            except (KeyError, ValueError):
                manifest = {}
            if manifest.get("app") != "scratch-map" or "scratch.db" not in names:
                abort(400, tr("não é um backup do scratch map"))
            bad = [n for n in names if not backup_member_ok(n)]
            if bad:
                abort(400, tr("o backup tem arquivos inesperados: {nomes}", nomes=", ".join(bad[:3])))
            z.extract("scratch.db", tmp)
            newdb = Path(tmp) / "scratch.db"
            chk = sqlite3.connect(newdb)
            try:
                ok = chk.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                chk.execute("SELECT kind, ref_id FROM visits LIMIT 1")
            except sqlite3.DatabaseError:
                ok = False
            finally:
                chk.close()
            if not ok:
                abort(400, tr("o banco dentro do backup está corrompido"))

            # rede de segurança: o estado atual, antes de trocar
            prof().backups.mkdir(exist_ok=True)
            safety = prof().backups / f"antes-de-restaurar-{dt.datetime.now():%Y-%m-%d-%H%M%S}.zip"
            write_backup(safety)
            for old in sorted(prof().backups.glob("antes-de-restaurar-*.zip"))[:-KEEP_SAFETY]:
                old.unlink()

            src, dst = sqlite3.connect(newdb), sqlite3.connect(prof().db)
            try:
                src.backup(dst)  # troca o conteúdo do banco em uso, sem apagar o arquivo
            finally:
                src.close()
                dst.close()
            for part in BACKUP_DIRS:
                shutil.rmtree(prof().dir / part, ignore_errors=True)
                (prof().dir / part).mkdir(parents=True)
            prof().photo.unlink(missing_ok=True)
            for n in names:
                if n.endswith("/") or n in ("manifest.json", "scratch.db"):
                    continue
                with z.open(n) as src_f, open(prof().dir / n, "wb") as out:
                    shutil.copyfileobj(src_f, out)
    init_storage()  # backup mais antigo: cria as tabelas que faltarem
    if installed():
        geo_ready()  # bandeiras e contornos que o backup não tiver
    log = logging.getLogger("scratch-map")
    log.info("backup restaurado (%s); estado anterior em %s", manifest.get("created_at"), safety.name)
    return jsonify(ok=True, restored=manifest, safety=safety.name)


@app.get("/perfil")
def perfil():
    return render_template("perfil.html")


@app.get("/stats")
def stats():
    return redirect("/perfil")  # aba antiga


@app.get("/config")
def config():
    # países visitados, para o "cidades visitadas em …" da vista inicial
    countries = db().execute(f"""SELECT co.id, co.name FROM ({VISITED_COUNTRIES_SQL}) v
                                 JOIN countries co ON co.id = v.id ORDER BY co.name""").fetchall()
    geo_v = int(TILES.stat().st_mtime)
    # dados do mapa (Sobre): montagem de antes do assistente não tem o
    # geodata.json; aí a data é a do desenho do mapa (o geo.db pode ter sido
    # atualizado depois, sem remontar)
    built = installer.manifest().get("built_at") or dt.datetime.fromtimestamp(TILES.stat().st_mtime).isoformat()
    return render_template("config.html", settings=settings(), countries=countries, geo_v=geo_v,
                           geodata={"mode": installer.mode()} | installer.manifest() | {"built_at": built},
                           version=version.VERSION, released=version.RELEASED)


@app.get("/geo/world.pmtiles")
def tiles():
    """Tiles vetoriais de países e estados. O navegador lê só trechos do arquivo
    (cabeçalho Range), então ele nunca é baixado inteiro."""
    resp = send_file(TILES, mimetype="application/octet-stream", conditional=True, max_age=604800)
    resp.headers["Accept-Ranges"] = "bytes"
    return resp


# Foto de capa do landmark: a mais antiga (por data, depois por envio).
COVER_SQL = """SELECT file FROM photos p WHERE p.kind = 'landmark' AND p.ref_id = l.id
               ORDER BY p.taken_on IS NULL, p.taken_on, p.id LIMIT 1"""


@app.get("/api/visited")
def visited():
    con = db()
    pc = photo_counts()
    ex = explicit_set()
    # a contagem da cidade inclui as fotos dos landmarks e aeroportos dela
    for p in photo_index():
        if p["kind"] in ("landmark", "airport") and p["city"]:
            key = ("city", p["city"]["id"])
            pc[key] = pc.get(key, 0) + 1

    def decorate(kind, rows):
        out = []
        for r in rows:
            d = dict(r)
            d["kind"] = kind
            d["explicit"] = kind == "landmark" or (kind, str(d["id"])) in ex
            d["photos"] = pc.get((kind, str(d["id"])), 0)
            out.append(d)
        return out

    countries = con.execute(f"""
        SELECT co.id, co.name FROM ({VISITED_COUNTRIES_SQL}) v
        JOIN countries co ON co.id = v.id ORDER BY co.name""").fetchall()
    states = con.execute(f"""
        SELECT s.id, s.name, s.country_id, co.name AS country FROM ({VISITED_STATES_SQL}) v
        JOIN geo.states s ON s.id = v.id LEFT JOIN countries co ON co.id = s.country_id
        ORDER BY co.name, s.name""").fetchall()
    cities = con.execute("""
        SELECT c.id, c.name, c.region, c.lat, c.lon, c.state_id, c.country_id,
               s.name AS state, co.name AS country, cs.status = 'ok' AS has_shape
          FROM visits v JOIN geo.cities c ON c.id = v.ref_id
          LEFT JOIN city_shapes cs ON cs.city_id = c.id
          LEFT JOIN geo.states s ON s.id = c.state_id
          LEFT JOIN countries co ON co.id = c.country_id
         WHERE v.kind = 'city' ORDER BY co.name, c.name""").fetchall()
    airports = con.execute("""
        SELECT a.id, a.name, a.municipality, a.lat, a.lon, a.country_id, co.name AS country
          FROM visits v JOIN geo.airports a ON a.id = v.ref_id
          LEFT JOIN countries co ON co.id = a.country_id
         WHERE v.kind = 'airport' ORDER BY a.id""").fetchall()
    landmarks = con.execute(f"""
        SELECT l.id, l.name, l.lat, l.lon, c.name AS city, co.name AS country,
               ({COVER_SQL}) AS cover
          FROM landmarks l LEFT JOIN geo.cities c ON c.id = l.city_id
          LEFT JOIN countries co ON co.id = c.country_id
         WHERE l.draft = 0 ORDER BY l.name""").fetchall()
    return jsonify({
        "country": decorate("country", countries),
        "state": decorate("state", states),
        "city": decorate("city", cities),
        "airport": decorate("airport", airports),
        "landmark": decorate("landmark", landmarks),
    })


# ------------------------------------------------------------------ stats
# Bandeiras: de país (e as poucas subdivisões que o pacote tem) prontas em
# static/vendor/flags/<ID>.svg (flag-icons, quadradas); de estado, baixadas do
# Wikidata para flags/<ID>.webp do perfil quando o país é visitado (flags.py).
# Estado/cidade sem bandeira: sigla na tela.
FLAGS = ROOT / "static" / "vendor" / "flags"
FLAG_IDS = {p.stem for p in FLAGS.glob("*.svg")}


def flag_url(place_id):
    if place_id in FLAG_IDS:
        return f"/static/vendor/flags/{place_id}.svg"
    if (prof().flags / f"{place_id}.webp").exists():
        return f"/flags/{place_id}.webp"
    return None


def fetch_state_flags():
    """Bandeiras dos estados dos países visitados (em segundo plano, uma vez por
    país). Nada se desligado na configuração (ext_state_flags)."""
    if not ext_on("ext_state_flags"):
        return
    countries = [r[0] for r in db().execute(VISITED_COUNTRIES_SQL)]
    state_flags.ensure(prof().db, GEO_DB, prof().flags, countries)


@app.post("/api/flags/refetch")
def refetch_state_flags():
    """Busca de novo as bandeiras de estado (as já baixadas ficam; pega as que
    faltaram ou foram cadastradas no Wikidata depois)."""
    if not ext_on("ext_state_flags"):
        abort(409, tr("bandeiras de estado desligadas na configuração"))
    db().execute("DELETE FROM state_flags_fetched")
    db().commit()
    fetch_state_flags()
    return jsonify(ok=True)


@app.get("/flags/<name>")
def state_flag(name):
    return send_from_directory(prof().flags, name, max_age=30 * 86400)


def by_visited(rows, key=lambda r: r["name"]):
    """Visitados primeiro; dentro de cada grupo, pela chave."""
    return sorted(rows, key=lambda r: (not r["visited"], key(r)))


@app.get("/api/stats")
def stats_countries():
    """Álbum de países (só os que têm bandeira) + totais de visitados por tipo."""
    vis = visited_set()
    countries = [{"id": r["id"], "name": r["name"], "visited": ("country", r["id"]) in vis}
                 for r in db().execute("SELECT id, name FROM countries") if r["id"] in FLAG_IDS]
    totals = {k: sum(1 for kind, _ in vis if kind == k) for k in ("country", "state", "city", "airport")}
    totals["landmark"] = db().execute("SELECT COUNT(*) FROM landmarks WHERE draft = 0").fetchone()[0]
    return jsonify(countries=by_visited(countries, lambda r: norm(r["name"])), totals=totals,
                   countries_total=len(countries))


@app.get("/api/stats/country/<cid>")
def stats_country(cid):
    """Estados de um país, com quantas cidades de cada um foram visitadas."""
    con, vis = db(), visited_set()
    c = con.execute("SELECT id, name FROM countries WHERE id = ?", (cid,)).fetchone() or abort(404)
    seen = {}
    for r in con.execute("""SELECT c.state_id FROM visits v JOIN geo.cities c ON c.id = v.ref_id
                             WHERE v.kind = 'city' AND c.country_id = ?""", (cid,)):
        seen[r[0]] = seen.get(r[0], 0) + 1
    states = [{"id": r["id"], "name": r["name"], "visited": ("state", r["id"]) in vis,
               "flag": flag_url(r["id"]), "cities": seen.get(r["id"], 0)}
              for r in con.execute("SELECT id, name FROM geo.states WHERE country_id = ?", (cid,))]
    return jsonify(country={"id": c["id"], "name": c["name"], "visited": ("country", cid) in vis, "flag": flag_url(cid)},
                   states=by_visited(states, lambda r: norm(r["name"])))


@app.get("/api/stats/state/<sid>")
def stats_state(sid):
    """Cidades de um estado: visitadas primeiro, depois as maiores."""
    con, vis, pc = db(), visited_set(), photo_counts()
    st = con.execute("""SELECT s.id, s.name, s.country_id, co.name AS country FROM geo.states s
                          JOIN countries co ON co.id = s.country_id WHERE s.id = ?""", (sid,)).fetchone() or abort(404)
    cities = [{"id": str(r["id"]), "name": r["name"], "visited": ("city", str(r["id"])) in vis,
               "photos": pc.get(("city", str(r["id"])), 0), "population": r["population"] or 0}
              for r in con.execute("SELECT id, name, population FROM geo.cities WHERE state_id = ?", (sid,))]
    cities.sort(key=lambda r: (not r["visited"], norm(r["name"]) if r["visited"] else -r["population"]))
    return jsonify(state={"id": st["id"], "name": st["name"], "visited": ("state", sid) in vis, "flag": flag_url(sid)},
                   country={"id": st["country_id"], "name": st["country"]}, cities=cities)


@app.get("/api/city-shapes")
def city_shapes():
    """Limites das cidades visitadas (os que já foram calculados). `?ids=1,2`
    devolve só essas: o navegador guarda os que já tem e pede só os novos."""
    ids = [i for i in request.args.get("ids", "").split(",") if i]
    only = f"AND v.ref_id IN ({','.join('?' * len(ids))})" if ids else ""
    rows = db().execute(f"""
        SELECT c.id, c.name, cs.geometry FROM visits v
          JOIN geo.cities c ON c.id = v.ref_id
          JOIN city_shapes cs ON cs.city_id = c.id
         WHERE v.kind = 'city' AND cs.status = 'ok' {only}""", ids).fetchall()
    # pending: o backfill ainda vai calcular alguma das pedidas (o mapa pede de novo)
    pending = boundaries.backfill_running() and db().execute(f"""
        SELECT 1 FROM visits v LEFT JOIN city_shapes cs ON cs.city_id = v.ref_id
         WHERE v.kind = 'city' AND (cs.status IS NULL OR cs.status = 'error') {only} LIMIT 1""", ids).fetchone() is not None
    return jsonify({"type": "FeatureCollection", "pending": pending, "features": [
        {"type": "Feature", "properties": {"id": str(r["id"]), "name": r["name"]},
         "geometry": json.loads(r["geometry"])} for r in rows]})


def norm(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


SEARCH_SQL = {
    "country": """SELECT id, name, NULL AS sub FROM countries
                  WHERE search LIKE :pre OR search LIKE :mid ORDER BY search LIKE :pre DESC, name LIMIT 15""",
    "state": """SELECT s.id, s.name, co.name AS sub FROM geo.states s
                LEFT JOIN countries co ON co.id = s.country_id
                WHERE s.search LIKE :pre OR s.search LIKE :mid
                ORDER BY s.search LIKE :pre DESC, s.name LIMIT 15""",
    "city": """SELECT c.id, c.name, COALESCE(s.name, c.region) || ', ' || COALESCE(co.name, c.country_id) AS sub
               FROM geo.cities c LEFT JOIN geo.states s ON s.id = c.state_id
               LEFT JOIN countries co ON co.id = c.country_id
               WHERE c.search LIKE :pre OR c.search LIKE :mid
               ORDER BY c.search LIKE :pre DESC, c.population DESC LIMIT 15""",
    "airport": """SELECT a.id, a.id || ' — ' || a.name AS name,
                         COALESCE(a.municipality, '') || ', ' || COALESCE(co.name, a.country_id) AS sub
                  FROM geo.airports a LEFT JOIN countries co ON co.id = a.country_id
                  WHERE a.id = :exact OR a.search LIKE :mid
                  ORDER BY a.id = :exact DESC, a.type, a.name LIMIT 15""",
    # landmarks são poucos: filtra em Python (norm) para ignorar acento
    "landmark": """SELECT l.id, l.name, c.name || ', ' || COALESCE(co.name, c.country_id) AS sub
                   FROM landmarks l LEFT JOIN geo.cities c ON c.id = l.city_id
                   LEFT JOIN countries co ON co.id = c.country_id
                   WHERE l.draft = 0 ORDER BY l.name""",
}


@app.get("/api/search")
def search():
    q = norm(request.args.get("q", ""))
    kinds = [k for k in request.args.get("kind", ",".join(PHOTO_KINDS)).split(",") if k in PHOTO_KINDS]
    if len(q) < 2:
        return jsonify([])
    params = {"pre": f"{q}%", "mid": f"%{q}%", "exact": q.upper()}
    ex, vis = explicit_set(), visited_set()
    per_kind = 15 if len(kinds) == 1 else 5
    out = []
    for k in kinds:
        rows = db().execute(SEARCH_SQL[k], params).fetchall()
        if k == "landmark":
            rows = [r for r in rows if q in norm(r["name"])]
        for r in rows[:per_kind]:
            out.append({**dict(r), "kind": k, **flags(k, r["id"], ex, vis)})
    # Código IATA exato ("gru") vem antes de tudo.
    out.sort(key=lambda r: not (r["kind"] == "airport" and r["id"] == params["exact"]))
    return jsonify(out)


# ------------------------------------------------------------------ lista de cidades
@app.get("/api/names")
def place_names():
    """Nome de cada país e estado, para o hover do mapa: o nome gravado nas
    tiles é o da montagem, sem idioma."""
    con = db()
    return jsonify(country={r["id"]: r["name"] for r in con.execute("SELECT id, name FROM countries")},
                   state={r["id"]: r["name"] for r in con.execute("SELECT id, name FROM geo.states")})


# Marcar várias de uma vez (fim do assistente e "Lista de cidades" no +): as
# cidades de um país (ou estado), das maiores para as menores, com filtro por nome.
CITY_PAGE = 50


@app.get("/api/countries")
def countries_list():
    """Todos os países, por nome, e qual seria o "de casa" (o mais visitado).
    Sem os territórios disputados X* do Overture (como no álbum), exceto os com
    bandeira (Kosovo)."""
    rows = [r for r in db().execute("SELECT id, name FROM countries")
            if not r["id"].startswith("X") or r["id"] in FLAG_IDS]
    top = db().execute("""SELECT c.country_id FROM visits v JOIN geo.cities c ON c.id = v.ref_id
                          WHERE v.kind = 'city' GROUP BY c.country_id ORDER BY COUNT(*) DESC LIMIT 1""").fetchone()
    return jsonify(countries=sorted(({"id": r["id"], "name": r["name"]} for r in rows), key=lambda r: norm(r["name"])),
                   home=top[0] if top else None)


@app.get("/api/cities")
def cities_list():
    """`?country=BR[&state=BR-SP][&q=…][&offset=0]`: cidades do país/estado,
    maiores primeiro, CITY_PAGE por vez. Na primeira página, os estados do país."""
    country = request.args.get("country", "")
    state = request.args.get("state") or None
    q = norm(request.args.get("q", ""))
    offset = max(0, request.args.get("offset", 0, type=int))
    where, params = ["c.country_id = ?"], [country]
    if state:
        where.append("c.state_id = ?")
        params.append(state)
    if q:
        where.append("c.search LIKE ?")
        params.append(f"%{q}%")
    rows = db().execute(f"""SELECT c.id, c.name, s.name AS state FROM geo.cities c
                             LEFT JOIN geo.states s ON s.id = c.state_id
                            WHERE {' AND '.join(where)}
                            ORDER BY c.population DESC LIMIT ? OFFSET ?""",
                        params + [CITY_PAGE + 1, offset]).fetchall()
    vis = visited_set()
    out = {"cities": [{"id": str(r["id"]), "name": r["name"], "state": r["state"] or "",
                       "visited": ("city", str(r["id"])) in vis} for r in rows[:CITY_PAGE]],
           "more": len(rows) > CITY_PAGE}
    if offset == 0 and not state:
        out["states"] = [{"id": r["id"], "name": r["name"]} for r in sorted(db().execute(
            "SELECT id, name FROM geo.states WHERE country_id = ?", (country,)), key=lambda r: norm(r["name"]))]
    return jsonify(out)


@app.post("/api/visits/batch")
def add_visits_batch():
    """`{ids: [...]}`: marca várias cidades. Os contornos vêm em segundo plano
    (no modo leve, 1 por segundo do Nominatim); o mapa vai buscando."""
    ids = [str(i) for i in (request.get_json(force=True) or {}).get("ids", [])][:2000]
    known = {str(r[0]) for r in db().execute(
        f"SELECT id FROM geo.cities WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else set()
    for cid in known:
        mark("city", cid)
    db().commit()
    fetch_state_flags()
    if known and not app.config.get("TESTING"):
        boundaries.start_backfill(prof().db, GEO_DB, allow_nominatim=ext_on("ext_city_shape"))
    return jsonify(ok=True, added=len(known))


@app.get("/api/nearby")
def nearby():
    """Cidades/aeroportos mais próximos de um clique no mapa."""
    kind = request.args.get("kind", "city")
    lat, lon = float(request.args["lat"]), float(request.args["lon"])
    radius = float(request.args.get("r", 1.0))  # graus
    limit = min(int(request.args.get("limit", 10)), 30)
    table, sub = {
        "city": ("geo.cities t", "t.name, COALESCE(s.name, t.region) || ', ' || co.name AS sub"),
        "airport": ("geo.airports t", "t.id || ' — ' || t.name AS name, t.municipality || ', ' || co.name AS sub"),
    }[kind]
    join = "LEFT JOIN geo.states s ON s.id = t.state_id" if kind == "city" else ""
    weight = "- t.population / 5e7" if kind == "city" else ""
    rows = db().execute(f"""
        SELECT t.id, {sub},
               ((t.lat - :lat) * (t.lat - :lat) + (t.lon - :lon) * (t.lon - :lon)) {weight} AS d
          FROM {table} {join} LEFT JOIN countries co ON co.id = t.country_id
         WHERE t.lat BETWEEN :lat - :r AND :lat + :r AND t.lon BETWEEN :lon - :r AND :lon + :r
         ORDER BY d LIMIT :limit""", {"lat": lat, "lon": lon, "r": radius, "limit": limit}).fetchall()
    ex, vis = explicit_set(), visited_set()
    return jsonify([{**dict(r), "kind": kind, **flags(kind, r["id"], ex, vis)} for r in rows])


def place_info(kind, ref_id):
    con = db()
    if kind == "country":
        r = con.execute("SELECT id, name, x0, y0, x1, y1 FROM countries WHERE id = ?", (ref_id,)).fetchone()
        crumbs = []
    elif kind == "state":
        r = con.execute("""SELECT s.id, s.name, s.country_id, co.name AS country, s.x0, s.y0, s.x1, s.y1
                           FROM geo.states s LEFT JOIN countries co ON co.id = s.country_id
                           WHERE s.id = ?""", (ref_id,)).fetchone()
        crumbs = [("country", r["country_id"], r["country"])] if r else []
    elif kind == "city":
        r = con.execute("""SELECT c.id, c.name, c.lat, c.lon, c.state_id, c.country_id,
                                  s.name AS state, co.name AS country
                           FROM geo.cities c LEFT JOIN geo.states s ON s.id = c.state_id
                           LEFT JOIN countries co ON co.id = c.country_id WHERE c.id = ?""",
                        (ref_id,)).fetchone()
        crumbs = [("state", r["state_id"], r["state"]), ("country", r["country_id"], r["country"])] if r else []
    elif kind == "airport":
        r = con.execute("""SELECT a.id, a.name, a.municipality, a.lat, a.lon, a.country_id, co.name AS country
                           FROM geo.airports a LEFT JOIN countries co ON co.id = a.country_id
                           WHERE a.id = ?""", (ref_id,)).fetchone()
        crumbs = [("country", r["country_id"], r["country"])] if r else []
    elif kind == "landmark":
        r = con.execute("""SELECT l.id, l.name, l.lat, l.lon, l.draft, l.city_id,
                                  c.name AS city, c.state_id, s.name AS state, c.country_id, co.name AS country
                           FROM landmarks l LEFT JOIN geo.cities c ON c.id = l.city_id
                           LEFT JOIN geo.states s ON s.id = c.state_id
                           LEFT JOIN countries co ON co.id = c.country_id
                           WHERE l.id = ?""", (ref_id,)).fetchone()
        crumbs = [("city", r["city_id"], r["city"]), ("state", r["state_id"], r["state"]),
                  ("country", r["country_id"], r["country"])] if r else []
    else:
        r = None
    if r is None:
        abort(404)
    r = dict(r)
    if "x0" in r:  # estado/país: bbox para o mapa enquadrar
        r["bbox"] = [r.pop("x0"), r.pop("y0"), r.pop("x1"), r.pop("y1")]
    return r, [{"kind": k, "id": i, "name": n} for k, i, n in crumbs if i]


def implied_by(kind, ref_id):
    """Quais visitas explícitas fazem este lugar contar como visitado."""
    con = db()
    if kind == "state":
        rows = con.execute("""SELECT 'city' AS kind, c.id, c.name FROM visits v
                              JOIN geo.cities c ON c.id = v.ref_id
                              WHERE v.kind = 'city' AND c.state_id = ? ORDER BY c.name""", (ref_id,))
    elif kind == "country":
        rows = con.execute("""SELECT 'state' AS kind, s.id, s.name FROM visits v
                              JOIN geo.states s ON s.id = v.ref_id
                              WHERE v.kind = 'state' AND s.country_id = ?
                              UNION ALL
                              SELECT 'city', c.id, c.name FROM visits v
                              JOIN geo.cities c ON c.id = v.ref_id
                              WHERE v.kind = 'city' AND c.country_id = ?
                              ORDER BY 1 DESC, 3""", (ref_id, ref_id))
    else:
        return []
    return [dict(r) for r in rows]


def photo_json(r):
    return {"id": r["id"], "taken_on": r["taken_on"], "width": r["width"], "height": r["height"],
            "url": f"/photos/display/{r['file']}.jpg", "thumb": f"/photos/thumb/{r['file']}.jpg"}


def newest_first(photos):
    """Mais recentes primeiro (data da foto); sem data no fim."""
    photos.sort(key=lambda p: p["id"], reverse=True)
    photos.sort(key=lambda p: p["taken_on"] or "", reverse=True)
    return photos


def photo_index():
    """Todas as fotos, cada uma com o lugar dono (label) e a cidade/estado/país
    em que está. Landmark entra pela cidade dele; aeroporto, pela cidade mais
    próxima. Foto de estado/país não tem cidade."""
    con = db()
    rows = con.execute("""
        SELECT p.*,
               CASE p.kind WHEN 'city' THEN c.name WHEN 'landmark' THEN l.name
                           WHEN 'airport' THEN a.id
                           WHEN 'state' THEN s.name WHEN 'country' THEN co.name END AS label,
               CASE p.kind WHEN 'city' THEN c.id WHEN 'landmark' THEN l.city_id END AS city_id,
               a.lat AS a_lat, a.lon AS a_lon,
               CASE p.kind WHEN 'state' THEN s.id END AS own_state,
               CASE p.kind WHEN 'state' THEN s.country_id WHEN 'country' THEN co.id END AS own_country
          FROM photos p
          LEFT JOIN geo.cities c ON p.kind = 'city' AND c.id = p.ref_id
          LEFT JOIN landmarks l ON p.kind = 'landmark' AND l.id = p.ref_id
          LEFT JOIN geo.airports a ON p.kind = 'airport' AND a.id = p.ref_id
          LEFT JOIN geo.states s ON p.kind = 'state' AND s.id = p.ref_id
          LEFT JOIN countries co ON p.kind = 'country' AND co.id = p.ref_id
         WHERE p.kind != 'landmark' OR l.draft = 0""").fetchall()
    airport_city = {}
    for r in rows:
        if r["kind"] == "airport" and r["ref_id"] not in airport_city and r["a_lat"] is not None:
            c = nearest_city(r["a_lat"], r["a_lon"])
            airport_city[r["ref_id"]] = c and c["id"]
    city_ids = {r["city_id"] for r in rows if r["city_id"]} | {v for v in airport_city.values() if v}
    cities = {r["id"]: dict(r) for r in con.execute(f"""
        SELECT c.id, c.name, c.state_id, s.name AS state, c.country_id, co.name AS country
          FROM geo.cities c LEFT JOIN geo.states s ON s.id = c.state_id
          LEFT JOIN countries co ON co.id = c.country_id
         WHERE c.id IN ({",".join("?" * len(city_ids))})""", list(city_ids))}
    names = {}

    def name(table, id_):
        if id_ and (table, id_) not in names:
            r = con.execute(f"SELECT name FROM geo.{table} WHERE id = ?", (id_,)).fetchone()
            names[(table, id_)] = r and r["name"]
        return names.get((table, id_))

    out = []
    for r in rows:
        cid = airport_city.get(r["ref_id"]) if r["kind"] == "airport" else r["city_id"]
        c = cities.get(cid)
        if c:
            city = {"id": str(c["id"]), "name": c["name"]}
            state = c["state_id"] and {"id": c["state_id"], "name": c["state"]}
            country = c["country_id"] and {"id": c["country_id"], "name": c["country"]}
        else:
            city = None
            state = r["own_state"] and {"id": r["own_state"], "name": name("states", r["own_state"])}
            country = r["own_country"] and {"id": r["own_country"], "name": name("countries", r["own_country"])}
        out.append({**photo_json(r), "kind": r["kind"], "ref_id": r["ref_id"], "label": r["label"],
                    "city": city, "state": state or None, "country": country or None})
    return newest_first(out)


def group_photos(photos, with_state=False):
    """Agrupa por cidade (ou pelo estado/país, para foto marcada direto neles),
    grupos em ordem alfabética e, dentro, mais recentes primeiro."""
    groups = {}
    for p in photos:
        if p["city"]:
            key, link = ("city", p["city"]["id"]), {"kind": "city", **p["city"]}
            title = p["city"]["name"]
            if with_state and p["state"]:
                title += f" · {p['state']['name']}"
        elif p["kind"] == "state":
            key, link = ("state", p["ref_id"]), {"kind": "state", **p["state"]}
            title = tr("{nome} (estado)", nome=p['state']['name'])   # não confundir com a cidade homônima
        else:
            key, link = ("country", p["ref_id"]), {"kind": "country", **p["country"]}
            title = tr("{nome} (país)", nome=p['country']['name'])
        g = groups.setdefault(key, {"title": title, "place": link, "photos": []})
        g["photos"].append(p)
    return sorted(groups.values(), key=lambda g: norm(g["title"]))


@app.get("/api/place/<kind>/<ref_id>")
def place(kind, ref_id):
    info, crumbs = place_info(kind, ref_id)
    explicit = kind == "landmark" or db().execute(
        "SELECT 1 FROM visits WHERE kind = ? AND ref_id = ?", (kind, str(ref_id))).fetchone() is not None
    via = implied_by(kind, ref_id)
    photos, groups = place_photos(kind, str(ref_id))
    return jsonify({**info, "kind": kind, "crumbs": crumbs, "explicit": explicit, "via": via,
                    "visited": explicit or bool(via), "photos": photos, "groups": groups})


def place_photos(kind, ref_id):
    """(fotos da tela do lugar, grupos das fotos de dentro dele).
    Cidade: as dela + as dos landmarks e aeroportos dela, misturadas. Estado/país: as dele e,
    à parte, um grupo por cidade (ou estado) contida."""
    own = lambda p: p["kind"] == kind and p["ref_id"] == ref_id
    if kind == "landmark" or kind == "airport":
        return newest_first([{**photo_json(r), "kind": kind, "ref_id": ref_id} for r in db().execute(
            "SELECT * FROM photos WHERE kind = ? AND ref_id = ?", (kind, ref_id))]), []
    idx = photo_index()
    if kind == "city":
        return [p for p in idx if own(p) or (p["city"] and p["city"]["id"] == ref_id)], []
    inside = (lambda p: p["state"] and p["state"]["id"] == ref_id) if kind == "state" \
        else (lambda p: p["country"] and p["country"]["id"] == ref_id)
    return [p for p in idx if own(p)], group_photos([p for p in idx if inside(p) and not own(p)],
                                                    with_state=kind == "country")


@app.get("/api/photos")
def all_photos():
    """Mural: todas as fotos, mais recentes primeiro, e agrupadas por localidade."""
    idx = photo_index()
    return jsonify(recent=idx, groups=group_photos(idx))


def mark(kind, ref_id):
    db().execute("INSERT OR IGNORE INTO visits (kind, ref_id) VALUES (?, ?)", (kind, str(ref_id)))


@app.post("/api/visits")
def add_visit():
    body = request.get_json(force=True)
    kind, ref_id = body.get("kind"), str(body.get("id"))
    if kind not in KINDS:
        abort(400)
    place_info(kind, ref_id)  # 404 se não existir
    mark(kind, ref_id)
    db().commit()
    fetch_state_flags()
    if kind == "city":  # ~1-3 s na primeira vez
        boundaries.fetch_and_store(prof().db, GEO_DB, ref_id, allow_nominatim=ext_on("ext_city_shape"))
    return jsonify(ok=True)


def trash_photo(row, con=None):
    for sub, ext in (("display", "jpg"), ("thumb", "jpg"), ("orig", row["original_ext"] or "jpg")):
        src = prof().photos / sub / f"{row['file']}.{ext}"
        if src.exists():
            shutil.move(src, prof().photos / "trash" / f"{row['file']}.{sub}.{ext}")
    (con or db()).execute("DELETE FROM photos WHERE id = ?", (row["id"],))


def delete_landmark_rows(con, landmark_id):
    """Apaga o landmark; as fotos vão para o trash."""
    for row in con.execute("SELECT * FROM photos WHERE kind = 'landmark' AND ref_id = ?",
                           (str(landmark_id),)).fetchall():
        trash_photo(row, con)
    con.execute("DELETE FROM landmarks WHERE id = ?", (landmark_id,))


@app.delete("/api/visits/<kind>/<ref_id>")
def remove_visit(kind, ref_id):
    """Desmarca. As fotos do lugar vão para photos/trash do perfil (recuperáveis à mão)."""
    con = db()
    for row in con.execute("SELECT * FROM photos WHERE kind = ? AND ref_id = ?", (kind, ref_id)).fetchall():
        trash_photo(row)
    con.execute("DELETE FROM visits WHERE kind = ? AND ref_id = ?", (kind, ref_id))
    con.commit()
    return jsonify(ok=True)


def exif_date(img):
    """Data da foto (AAAA-MM-DD) a partir do EXIF, se houver."""
    exif = img.getexif()
    raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal / DateTime
    if not raw:
        return None
    try:
        return dt.datetime.strptime(str(raw).strip()[:10], "%Y:%m:%d").date().isoformat()
    except ValueError:
        return None


def exif_gps(img):
    """(lat, lon) do GPS no EXIF, se houver. Fica só aqui: não é gravado na foto exibida."""
    gps = img.getexif().get_ifd(0x8825)
    try:
        def deg(v, ref):
            d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
            return -d if str(ref).upper() in ("S", "W") else d
        lat, lon = deg(gps[2], gps.get(1, "N")), deg(gps[4], gps.get(3, "E"))
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0) or math.isnan(lat + lon):
        return None
    return round(lat, 6), round(lon, 6)


def save_photos(kind, ref_id, files, fallback_date=None):
    """Grava original + versão de exibição + miniatura. Retorna (ids, erros, gps da 1ª foto que tiver)."""
    saved, errors, gps = [], [], None
    for f in files:
        base = uuid.uuid4().hex
        ext = (Path(f.filename or "").suffix.lstrip(".").lower() or "jpg")[:5]
        orig = prof().photos / "orig" / f"{base}.{ext}"
        f.save(orig)
        try:
            with Image.open(orig) as img:
                taken = exif_date(img) or fallback_date
                gps = gps or exif_gps(img)
                img = ImageOps.exif_transpose(img).convert("RGB")
                full = img.copy()
                full.thumbnail((DISPLAY_PX, DISPLAY_PX), Image.LANCZOS)
                full.save(prof().photos / "display" / f"{base}.jpg", "JPEG", quality=86, optimize=True)
                img.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
                img.save(prof().photos / "thumb" / f"{base}.jpg", "JPEG", quality=82, optimize=True)
        except Exception as e:  # arquivo que não é imagem, corrompido, etc.
            orig.unlink(missing_ok=True)
            errors.append(f"{f.filename}: {e}")
            continue
        cur = db().execute("""INSERT INTO photos (kind, ref_id, file, original_name, original_ext,
                                                  taken_on, width, height)
                              VALUES (?,?,?,?,?,?,?,?)""",
                           (kind, str(ref_id), base, f.filename, ext, taken, full.width, full.height))
        saved.append(cur.lastrowid)
    return saved, errors, gps


@app.post("/api/place/<kind>/<ref_id>/photos")
def upload_photos(kind, ref_id):
    if kind not in PHOTO_KINDS:
        abort(400)
    place_info(kind, ref_id)
    saved, errors, _ = save_photos(kind, ref_id, request.files.getlist("photos"),
                                   request.form.get("date") or None)
    if saved and kind in KINDS:
        mark(kind, ref_id)  # foto num lugar = esteve lá (landmark não marca nada)
    db().commit()
    if saved and kind in KINDS:
        fetch_state_flags()
    if saved and kind == "city":
        boundaries.fetch_and_store(prof().db, GEO_DB, ref_id, allow_nominatim=ext_on("ext_city_shape"))
    return jsonify(saved=saved, errors=errors), (200 if saved or not errors else 400)


# ------------------------------------------------------------------ landmarks
def nearest_city(lat, lon, radius=1.0):
    """Cidade de um ponto, com distância em km até o centro dela.

    1) contorno (OSM) de uma cidade já marcada que contém o ponto;
    2) senão, a mais próxima, com um empurrão para as grandes: no Cristo Redentor
       dá Rio de Janeiro, não o bairro Botafogo (que o GeoNames lista como cidade).
    """
    k = max(math.cos(math.radians(lat)), 0.05)
    dist = """SELECT id, name, state_id, country_id,
                     (lat - :lat) * (lat - :lat) + ((lon - :lon) * :k) * ((lon - :lon) * :k) AS d2
                FROM geo.cities"""
    params = {"lat": lat, "lon": lon, "k": k, "r": radius}
    pt = Point(lon, lat)
    for r in db().execute("SELECT city_id, geometry FROM city_shapes WHERE status = 'ok'"):
        if shape(json.loads(r["geometry"])).contains(pt):
            c = db().execute(f"{dist} WHERE id = :id", {**params, "id": r["city_id"]}).fetchone()
            if c:
                return {**dict(c), "km": round(math.sqrt(c["d2"]) * 111.2, 1)}
    c = db().execute(f"""{dist}
         WHERE lat BETWEEN :lat - :r AND :lat + :r AND lon BETWEEN :lon - :r / :k AND :lon + :r / :k
         ORDER BY d2 - population / 2e8 LIMIT 1""", params).fetchone()
    if c is None:
        return None
    return {**dict(c), "km": round(math.sqrt(c["d2"]) * 111.2, 1)}


@app.get("/api/landmarks/near")
def landmark_near():
    """Cidade/estado/país em volta de um ponto, para o "também marcar" do formulário."""
    lat, lon = float(request.args["lat"]), float(request.args["lon"])
    c = nearest_city(lat, lon)
    if c is None:
        return jsonify([])
    con, ex, vis = db(), explicit_set(), visited_set()
    out = [{"kind": "city", "id": str(c["id"]), "name": c["name"], "km": c["km"]}]
    if c["state_id"]:
        s = con.execute("SELECT name FROM geo.states WHERE id = ?", (c["state_id"],)).fetchone()
        out.append({"kind": "state", "id": c["state_id"], "name": s["name"]})
    co = con.execute("SELECT name FROM countries WHERE id = ?", (c["country_id"],)).fetchone()
    if co:
        out.append({"kind": "country", "id": c["country_id"], "name": co["name"]})
    return jsonify([{**o, **flags(o["kind"], o["id"], ex, vis)} for o in out])


@app.get("/api/landmarks/suggest")
def landmark_suggest():
    """Sugestão de nome pelo OSM (só as coordenadas saem da máquina).
    Desligada na configuração: não pede nada."""
    if not ext_on("ext_landmark_name"):
        return jsonify(name=None)
    try:
        name = boundaries.poi_name(float(request.args["lat"]), float(request.args["lon"]))
    except Exception as e:
        logging.getLogger("scratch-map").warning("sugestão de nome: %s", e)
        name = None
    return jsonify(name=name)


@app.post("/api/landmarks")
def create_landmark():
    """Cria um rascunho de landmark a partir de fotos; o formulário depois dá nome e posição."""
    files = request.files.getlist("photos")
    if not files:
        abort(400)
    con = db()
    lid = con.execute("INSERT INTO landmarks DEFAULT VALUES").lastrowid
    saved, errors, gps = save_photos("landmark", lid, files)
    if not saved:
        con.rollback()
        return jsonify(saved=[], errors=errors), 400
    if gps:
        set_landmark_position(lid, *gps)
    con.commit()
    return jsonify(id=lid, gps=gps, errors=errors)


def set_landmark_position(lid, lat, lon):
    c = nearest_city(lat, lon)
    db().execute("UPDATE landmarks SET lat = ?, lon = ?, city_id = ? WHERE id = ?",
                 (lat, lon, c and c["id"], lid))


@app.patch("/api/landmarks/<int:lid>")
def edit_landmark(lid):
    body = request.get_json(force=True)
    place_info("landmark", lid)
    if "lat" in body and "lon" in body:
        set_landmark_position(lid, float(body["lat"]), float(body["lon"]))
    if "name" in body:
        name = (body["name"] or "").strip()[:200]
        if not name or db().execute("SELECT lat FROM landmarks WHERE id = ?", (lid,)).fetchone()["lat"] is None:
            abort(400)  # precisa de nome e posição para sair do rascunho
        db().execute("UPDATE landmarks SET name = ?, draft = 0 WHERE id = ?", (name, lid))
    db().commit()
    return jsonify(ok=True)


@app.delete("/api/landmarks/<int:lid>")
def remove_landmark(lid):
    delete_landmark_rows(db(), lid)
    db().commit()
    return jsonify(ok=True)


@app.patch("/api/photos/<int:photo_id>")
def edit_photo(photo_id):
    body = request.get_json(force=True)
    taken = body.get("taken_on") or None
    if taken:
        dt.date.fromisoformat(taken)
    db().execute("UPDATE photos SET taken_on = ? WHERE id = ?", (taken, photo_id))
    db().commit()
    return jsonify(ok=True)


@app.delete("/api/photos/<int:photo_id>")
def delete_photo(photo_id):
    row = db().execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if row is None:
        abort(404)
    trash_photo(row)
    gone = False
    if row["kind"] == "landmark" and not db().execute(
            "SELECT 1 FROM photos WHERE kind = 'landmark' AND ref_id = ?", (row["ref_id"],)).fetchone():
        delete_landmark_rows(db(), int(row["ref_id"]))  # landmark só existe com foto
        gone = True
    db().commit()
    return jsonify(ok=True, place_deleted=gone)


@app.get("/photos/<sub>/<name>")
def photo_file(sub, name):
    if sub not in ("display", "thumb", "orig"):
        abort(404)
    resp = send_from_directory(prof().photos / sub, name)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


profiles.setup()
each_profile(init_storage)
installer.adopt_legacy()  # instalação de antes do assistente: já está pronta
if not installed():
    installer.resume()    # montagem interrompida (container reiniciou no meio)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5020)), debug=True)
