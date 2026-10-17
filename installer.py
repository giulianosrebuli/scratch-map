"""Primeira execução: o assistente em /setup e a montagem dos dados do mapa.

O container sobe sem os dados do mapa. O assistente pergunta o básico e, no
fim, roda scripts/build_geodata.py em segundo plano, que baixa das fontes
abertas (Overture, GeoNames, OurAirports, litoral do OSM) e monta tudo:

  leve      sem as áreas de cidade (~1,9 GB): o contorno da cidade vem do Nominatim
  completo  tudo local (~6,3 GB)

O andamento fica em geodata/build-status.json (lido pela tela de progresso) e
o log em geodata/build.log. Se o container reiniciar no meio, a montagem
continua de onde parou (as etapas do build são retomáveis).

data/setup.json guarda o que o assistente decidiu ({"done", "mode"}). Fica
fora do banco de propósito: restaurar um backup não reabre o assistente.
Instância de antes do assistente (dados do mapa já prontos) é adotada como
instalada (adopt_legacy).

Teste: SCRATCH_BUILD_SIMULATE=<pasta com dados prontos> imita as etapas
copiando os arquivos de lá, em ~1 min.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("SCRATCH_DATA", ROOT / "data"))
GEODATA = Path(os.environ.get("SCRATCH_GEODATA", ROOT / "geodata"))
SETUP = DATA / "setup.json"
STATUS = GEODATA / "build-status.json"
MANIFEST = GEODATA / "geodata.json"
LOG = GEODATA / "build.log"
PID = GEODATA / "build.pid"
SIMULATE = os.environ.get("SCRATCH_BUILD_SIMULATE")
MODES = ("leve", "completo")

_proc = None


def _read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def setup():
    return _read(SETUP)


def done():
    return bool(setup().get("done"))


def running():
    """O build está rodando (por este processo ou um anterior, que sobreviveu)."""
    if _proc is not None:
        return _proc.poll() is None
    try:
        pid = int(PID.read_text())
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, ValueError, IndexError):
        return False
    return state != "Z" and b"build_geodata" in cmd


def ready():
    """Dados do mapa prontos para o app (o geo.db é o último a ficar pronto)."""
    return (GEODATA / "geo.db").exists() and (GEODATA / "world.pmtiles").exists() and not running()


def mode():
    m = _read(MANIFEST).get("mode") or setup().get("mode")
    if m in MODES:
        return m
    return "completo" if (GEODATA / "localities").exists() else "leve"


def adopt_legacy():
    if not SETUP.exists() and ready():
        _write_setup(done=True, mode=mode())


def _write_setup(**kw):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = SETUP.with_name(SETUP.name + ".tmp")
    tmp.write_text(json.dumps({**setup(), **kw}))
    os.replace(tmp, SETUP)


def start(chosen):
    """Fim do assistente: grava a escolha e começa a montagem."""
    if chosen not in MODES:
        raise ValueError(chosen)
    _write_setup(done=True, mode=chosen)
    _spawn(chosen)


def resume():
    """Na subida: assistente concluído mas dados incompletos, e nada rodando."""
    if done() and not ready() and not running() and status().get("state") != "error":
        _spawn(setup().get("mode", "leve"))


def _spawn(chosen):
    global _proc
    if running():
        return
    GEODATA.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ROOT / "scripts" / "build_geodata.py"),
           "--mode", chosen, "--status", str(STATUS), "--cleanup"]
    if SIMULATE:
        cmd += ["--simulate", SIMULATE]
    with open(LOG, "a") as log:
        # sessão própria: sobrevive a um restart do worker do gunicorn
        _proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                 cwd=ROOT, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    PID.write_text(str(_proc.pid))


def status():
    return _read(STATUS)


def manifest():
    """Versão do Overture e modo dos dados montados (geodata/geodata.json)."""
    return _read(MANIFEST)


def state():
    """Tudo o que a tela do assistente precisa saber."""
    st = setup()
    return {"done": bool(st.get("done")), "mode": st.get("mode"), "running": running(),
            "ready": ready(), "build": status(), "simulate": bool(SIMULATE)}
