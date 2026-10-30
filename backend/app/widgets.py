import hashlib
import json
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, TypedDict, cast

from app.cart import Cart, require_session
from app.menu import MenuResponse
from app.validator import ContainerNode


class WidgetError(ValueError):
    pass


class WidgetEnvelope(TypedDict):
    kind: Literal["widget"]
    widget_id: str
    revision: int
    locale: Literal["en", "ar"]
    payload: ContainerNode
    menu_view_id: str
    cart_revision: str
    menu: MenuResponse
    cart: Cart


def initialize_widgets(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS widgets (id TEXT PRIMARY KEY, session_hash TEXT NOT NULL, locale TEXT NOT NULL, UNIQUE(session_hash, locale))")
        connection.execute("CREATE TABLE IF NOT EXISTS widget_revisions (widget_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, envelope_json TEXT NOT NULL, PRIMARY KEY(widget_id, revision))")
        connection.execute("CREATE TABLE IF NOT EXISTS session_snapshots (session_hash TEXT PRIMARY KEY, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS widget_acknowledgements (widget_id TEXT PRIMARY KEY, revision INTEGER NOT NULL)")


def issue_widget(connection: sqlite3.Connection, session_hash: str, locale: Literal["en", "ar"], menu: MenuResponse, cart: Cart, payload: ContainerNode, view_id: str) -> WidgetEnvelope:
    """Issue or reuse an immutable widget revision within the caller transaction."""
    row: tuple[str] | None = connection.execute("SELECT id FROM widgets WHERE session_hash = ? AND locale = ?", (session_hash, locale)).fetchone()
    widget_id: str = row[0] if row is not None else secrets.token_urlsafe(24)
    if row is None:
        connection.execute("INSERT INTO widgets (id, session_hash, locale) VALUES (?, ?, ?)", (widget_id, session_hash, locale))
    cart_revision: str = cart["revision"]
    fingerprint: str = hashlib.sha256(json.dumps({"payload": payload, "menu_view_id": view_id, "cart_revision": cart_revision, "menu": menu, "cart": cart}, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    latest: tuple[int, str, str] | None = connection.execute("SELECT revision, fingerprint, envelope_json FROM widget_revisions WHERE widget_id = ? ORDER BY revision DESC LIMIT 1", (widget_id,)).fetchone()
    if latest is not None and latest[1] == fingerprint:
        return cast(WidgetEnvelope, json.loads(latest[2]))
    revision: int = 1 if latest is None else latest[0] + 1
    envelope: WidgetEnvelope = {"kind": "widget", "widget_id": widget_id, "revision": revision, "locale": locale, "payload": payload, "menu_view_id": view_id, "cart_revision": cart_revision, "menu": menu, "cart": cart}
    connection.execute("INSERT INTO widget_revisions (widget_id, revision, fingerprint, envelope_json) VALUES (?, ?, ?, ?)", (widget_id, revision, fingerprint, json.dumps(envelope, ensure_ascii=False)))
    return envelope

def acknowledge_widget(path: Path, token: str, widget_id: str, revision: int) -> WidgetEnvelope:
    """Accept an issued revision and retain the highest acknowledged revision."""
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        row: tuple[str] | None = connection.execute("SELECT r.envelope_json FROM widgets w JOIN widget_revisions r ON r.widget_id = w.id WHERE w.id = ? AND w.session_hash = ? AND r.revision = ?", (widget_id, session_hash, revision)).fetchone()
        if row is None:
            raise WidgetError("Widget revision was not issued to this session. Refresh the widget and try again.")
        connection.execute("INSERT INTO widget_acknowledgements (widget_id, revision) VALUES (?, ?) ON CONFLICT(widget_id) DO UPDATE SET revision = excluded.revision WHERE excluded.revision > widget_acknowledgements.revision", (widget_id, revision))
        return cast(WidgetEnvelope, json.loads(row[0]))
