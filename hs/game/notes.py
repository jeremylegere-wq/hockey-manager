"""Your notebook and short list (phase A).

Notes are free text you keep in the save, optionally about a player or a club (the Notes screen, or "Add note" on a
player). The short list is the players you are watching, from any club or league, with the day you added them and
an optional reason; it shows on the Roster screen's Short list tab and in the transactions hub.
"""
from __future__ import annotations


def ensure_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS notes (note_id INTEGER PRIMARY KEY, created TEXT, text TEXT, player_id INTEGER, "
                 "team_id INTEGER)")
    conn.execute("CREATE TABLE IF NOT EXISTS shortlist (player_id INTEGER PRIMARY KEY, added TEXT, reason TEXT)")


def add_note(conn, day, text, player_id=None, team_id=None):
    ensure_tables(conn)
    text = (text or "").strip()
    if not text:
        raise ValueError("A note needs some text.")
    if len(text) > 4000:
        raise ValueError("Keep a note under 4,000 characters.")
    cur = conn.execute("INSERT INTO notes (created, text, player_id, team_id) VALUES (?,?,?,?)", (day, text, player_id, team_id))
    return cur.lastrowid


def edit_note(conn, note_id, text):
    ensure_tables(conn)
    text = (text or "").strip()
    if not text:
        raise ValueError("A note needs some text.")
    if not conn.execute("UPDATE notes SET text=? WHERE note_id=?", (text, note_id)).rowcount:
        raise ValueError("No such note.")


def delete_note(conn, note_id):
    ensure_tables(conn)
    if not conn.execute("DELETE FROM notes WHERE note_id=?", (note_id,)).rowcount:
        raise ValueError("No such note.")


def notes(conn, player_id=None, team_id=None):
    ensure_tables(conn)
    q, a = "SELECT * FROM notes", []
    if player_id:
        q, a = q + " WHERE player_id=?", [player_id]
    elif team_id:
        q, a = q + " WHERE team_id=?", [team_id]
    return [dict(r) for r in conn.execute(q + " ORDER BY created DESC, note_id DESC", a)]


def shortlist_add(conn, day, pid, reason=""):
    ensure_tables(conn)
    if not conn.execute("SELECT 1 FROM players WHERE player_id=?", (pid,)).fetchone():
        raise ValueError("No such player.")
    conn.execute("INSERT OR REPLACE INTO shortlist VALUES (?,?,?)", (pid, day, (reason or "").strip()[:200]))


def shortlist_remove(conn, pid):
    ensure_tables(conn)
    if not conn.execute("DELETE FROM shortlist WHERE player_id=?", (pid,)).rowcount:
        raise ValueError("He is not on your short list.")


def on_shortlist(conn, pid):
    ensure_tables(conn)
    return bool(conn.execute("SELECT 1 FROM shortlist WHERE player_id=?", (pid,)).fetchone())


def shortlist(conn):
    ensure_tables(conn)
    return [dict(r) for r in conn.execute("SELECT * FROM shortlist ORDER BY added DESC")]
