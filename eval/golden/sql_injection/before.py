import sqlite3


def buscar_usuario(conn: sqlite3.Connection, email: str):
    cur = conn.execute("SELECT id, nome FROM usuarios WHERE email = ?", (email,))
    return cur.fetchone()
