"""Perfis da casa: cada pessoa com seus dados, sem senha (estilo "quem está
usando?"). Confia em quem está na rede, como o resto do app.

Cada perfil é uma pasta em data/profiles/<id>/ com tudo o que é dele:

  scratch.db    visitas, monumentos, fotos (registro), configurações, contornos
  photos/       as fotos (original, exibição, miniatura, lixeira)
  profile.jpg   a foto de perfil
  flags/        bandeiras de estado baixadas
  backups/      cópias "antes de restaurar"

Da casa toda (fora dos perfis): os dados do mapa (geodata/) e o que o
assistente decidiu (data/setup.json). Cada aparelho lembra o perfil escolhido
num cookie; com um perfil só, ele é usado direto, sem perguntar.

Apagar um perfil move a pasta para data/profiles-removed/ (dá para desfazer à
mão). Os ids não são reaproveitados.
"""
import os
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("SCRATCH_DATA", ROOT / "data"))
PROFILES = DATA / "profiles"
REMOVED = DATA / "profiles-removed"
COOKIE = "perfil"
# o que era de data/ antes dos perfis e passa a ser do perfil 1
LEGACY = ("scratch.db", "scratch.db-wal", "scratch.db-shm", "photos", "profile.jpg", "flags", "backups")


class Profile:
    def __init__(self, pid):
        self.id = str(pid)
        self.dir = PROFILES / self.id
        self.db = self.dir / "scratch.db"
        self.photos = self.dir / "photos"
        self.photo = self.dir / "profile.jpg"
        self.flags = self.dir / "flags"
        self.backups = self.dir / "backups"

    def info(self):
        """Nome e versão da foto, para a tela de escolha."""
        try:
            con = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
            try:
                st = dict(con.execute("SELECT key, value FROM settings WHERE key IN ('profile_name', 'profile_photo')"))
            finally:
                con.close()
        except sqlite3.Error:
            st = {}
        return {"id": self.id, "name": st.get("profile_name") or "", "photo": st.get("profile_photo")}


def list_all():
    if not PROFILES.exists():
        return []
    return [Profile(p.name) for p in sorted((p for p in PROFILES.iterdir() if p.name.isdigit() and p.is_dir()),
                                            key=lambda p: int(p.name))]


def get(pid):
    if not pid or not str(pid).isdigit():
        return None
    p = Profile(int(pid))
    return p if p.dir.is_dir() else None


def _next_id():
    used = [int(p.name) for p in PROFILES.iterdir() if p.name.isdigit()] if PROFILES.exists() else []
    if REMOVED.exists():
        used += [int(p.name.split("-")[0]) for p in REMOVED.iterdir() if p.name.split("-")[0].isdigit()]
    return max(used, default=0) + 1


def create():
    p = Profile(_next_id())
    p.dir.mkdir(parents=True)
    return p


def remove(p):
    REMOVED.mkdir(parents=True, exist_ok=True)
    shutil.move(p.dir, REMOVED / f"{p.id}-{time.strftime('%Y%m%d-%H%M%S')}")


def setup():
    """Na subida: instalação de antes dos perfis vira o perfil 1; sem nenhum
    perfil, cria o primeiro (o assistente preenche)."""
    if not list_all():
        p = Profile(1)
        p.dir.mkdir(parents=True, exist_ok=True)
        for name in LEGACY:
            if (DATA / name).exists():
                shutil.move(DATA / name, p.dir / name)
        for old in DATA.glob("scratch.db.bak-*"):  # cópias antigas do banco vão junto
            shutil.move(old, p.dir / old.name)
