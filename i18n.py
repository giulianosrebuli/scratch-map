"""Tradução da interface.

O texto em português é a chave (o código continua legível em português) e
i18n/<idioma>.json traz a tradução de cada um; sem tradução, fica o português.
Variáveis no texto: {nome}. Plural: duas chaves ("{n} cidade" / "{n} cidades").

Nomes de lugares (países, estados, cidades) vêm dos dados do mapa e não passam
por aqui. As páginas recebem a tabela inteira (window.I18N) para o JS usar com
SM.t(); o servidor usa t() nos templates (_) e nas mensagens de erro.
"""
import json
import re
from pathlib import Path

LANGS = {"pt-BR": "Português", "en": "English"}
DEFAULT = "pt-BR"
DIR = Path(__file__).resolve().parent / "i18n"
_tables = {}


def table(lang):
    if lang == DEFAULT or lang not in LANGS:
        return {}
    if lang not in _tables:
        _tables[lang] = json.loads((DIR / f"{lang}.json").read_text(encoding="utf-8"))
    return _tables[lang]


def t(text, lang, **kw):
    s = table(lang).get(text, text)
    return re.sub(r"\{(\w+)\}", lambda m: str(kw.get(m[1], m[0])), s) if kw else s


def from_header(accept_language):
    """Idioma inicial (antes de escolher): o do navegador, se for um dos nossos."""
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()
        if code.startswith("pt"):
            return "pt-BR"
        if code.startswith("en"):
            return "en"
    return DEFAULT
