"""Tokens da API para integrações (/api/v1): um por integração, criado por
perfil nas Configurações e revogável a qualquer momento.

O token é mostrado uma vez só, na criação: no banco do perfil fica só o hash
(SHA-256). O formato carrega o perfil, então achar o dono é uma consulta só:

  sm_<id do perfil>_<43 caracteres aleatórios>

Quem tem o token age como aquele perfil (marcar, desmarcar, enviar fotos).
Apagar o perfil apaga os tokens junto (estão no banco dele).
"""
import hashlib
import re
import secrets
import sqlite3

import profiles

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_tokens (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    hint TEXT NOT NULL,          -- últimos 4 caracteres, para reconhecer na lista
    hash TEXT NOT NULL UNIQUE,   -- SHA-256 do token (o token em si não fica guardado)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT
);
"""
TOKEN_RE = re.compile(r"^sm_(\d+)_([A-Za-z0-9_-]{43})$")


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create(con, pid, name):
    """Cria e devolve (id, token). O token não pode ser recuperado depois."""
    token = f"sm_{pid}_{secrets.token_urlsafe(32)}"
    cur = con.execute("INSERT INTO api_tokens (name, hint, hash) VALUES (?, ?, ?)",
                      (name, token[-4:], _hash(token)))
    con.commit()
    return cur.lastrowid, token


def listing(con):
    return [dict(r) for r in con.execute(
        "SELECT id, name, hint, created_at, last_used_at FROM api_tokens ORDER BY id")]


def revoke(con, token_id):
    con.execute("DELETE FROM api_tokens WHERE id = ?", (token_id,))
    con.commit()


def lookup(token):
    """O perfil dono do token, ou None (formato errado, perfil ou token
    inexistente, revogado). Marca o uso (no máximo uma vez por minuto)."""
    m = TOKEN_RE.match(token or "")
    p = m and profiles.get(m.group(1))
    if not p or not p.db.exists():
        return None
    con = sqlite3.connect(p.db)
    try:
        con.executescript(SCHEMA)
        row = con.execute("SELECT id FROM api_tokens WHERE hash = ?", (_hash(token),)).fetchone()
        if row is None:
            return None
        con.execute("""UPDATE api_tokens SET last_used_at = datetime('now')
                       WHERE id = ? AND (last_used_at IS NULL OR last_used_at < datetime('now', '-1 minute'))""",
                    (row[0],))
        con.commit()
        return p
    finally:
        con.close()
