"""Voos: código, data, origem e destino (aeroportos do geo.db) e os horários.

O código do voo não diz a rota: "LA3456" é companhia + número, e a rota e o
horário estão no quadro de horários da companhia (e mudam com o tempo). Por
isso o voo é preenchido à mão, e a consulta é opcional: com uma chave da
AeroDataBox (RapidAPI, tem plano gratuito) na configuração, uma para o
servidor todo, o código e a data preenchem origem, destino e horários.

Sai da máquina (só na consulta, e só com chave): o código do voo e a data.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from flags import USER_AGENT

SCHEMA = """
-- Voo: marca os dois aeroportos. Horários na hora local de cada aeroporto.
CREATE TABLE IF NOT EXISTS flights (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,          -- LA3456 (maiúsculo, sem espaço)
    date TEXT NOT NULL,          -- AAAA-MM-DD, data local da partida
    origin TEXT NOT NULL,        -- código IATA (geo.airports)
    destination TEXT NOT NULL,
    departs TEXT,                -- HH:MM, opcional
    arrives TEXT,                -- HH:MM, opcional
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS flights_date ON flights(date);
"""

KEY_SETTING = "aerodatabox_key"   # em data/server.json (app.server_conf): vale para todos os perfis
HOST = "aerodatabox.p.rapidapi.com"


class LookupFailed(Exception):
    """Falha na consulta, com mensagem para mostrar (em português; a rota traduz)."""
    def __init__(self, msg, **kw):
        super().__init__(msg)
        self.msg, self.kw = msg, kw


def norm_code(code):
    """'la 3456' -> 'LA3456'; None se não parece um código de voo (2-3 letras/dígitos da
    companhia, IATA ou ICAO, + número de 1 a 4 dígitos e uma letra opcional)."""
    c = re.sub(r"[\s-]", "", str(code or "")).upper()
    return c if re.fullmatch(r"[A-Z0-9]{2}[A-Z]?\d{1,4}[A-Z]?", c) else None


def valid_time(s):
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(s)))


def _clock(t):
    """Hora local (HH:MM) de um horário da AeroDataBox: {"local": "2024-05-01 09:00-03:00"}
    nas versões novas, "2024-05-01 09:00-03:00" (scheduledTimeLocal) nas antigas."""
    if isinstance(t, dict):
        t = t.get("local")
    m = re.search(r"\d{4}-\d\d-\d\d[ T](\d\d:\d\d)", t or "")
    return m and m.group(1)


def lookup(key, code, date):
    """Pernas do voo nessa data: [{origin, destination, departs, arrives, airline}]
    (um número pode ter mais de uma perna no mesmo dia). [] se não achou."""
    url = (f"https://{HOST}/flights/number/{urllib.parse.quote(code)}/{date}"
           "?withAircraftImage=false&withLocation=false&dateLocalRole=Departure")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "X-RapidAPI-Key": key,
                                               "X-RapidAPI-Host": HOST})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        if e.code in (401, 403):
            raise LookupFailed("A AeroDataBox recusou a chave.")
        if e.code == 429:
            raise LookupFailed("Limite de consultas da AeroDataBox atingido.")
        raise LookupFailed("A AeroDataBox respondeu {codigo}.", codigo=e.code)
    except (urllib.error.URLError, TimeoutError):
        raise LookupFailed("Sem resposta da AeroDataBox.")
    if not raw.strip():  # 204: nada nessa data
        return []
    out = []
    for f in json.loads(raw):
        dep, arr = f.get("departure") or {}, f.get("arrival") or {}
        origin, dest = (dep.get("airport") or {}).get("iata"), (arr.get("airport") or {}).get("iata")
        if not origin or not dest:
            continue
        out.append({
            "origin": origin, "destination": dest,
            "departs": _clock(dep.get("scheduledTime") or dep.get("scheduledTimeLocal")),
            "arrives": _clock(arr.get("scheduledTime") or arr.get("scheduledTimeLocal")),
            "airline": (f.get("airline") or {}).get("name"),
        })
    return out
