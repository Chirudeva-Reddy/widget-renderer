import json
import secrets
import sqlite3
from pathlib import Path
from typing import Literal, cast

from app.cart import require_session
from app.menu import MenuResponse


class MenuViewError(ValueError):
    pass


def initialize_menu_views(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS menu_views (id TEXT PRIMARY KEY, session_hash TEXT NOT NULL, menu_revision INTEGER NOT NULL, locale TEXT NOT NULL, menu_json TEXT NOT NULL, UNIQUE(session_hash, menu_revision, locale))")


def issue_menu_view(connection: sqlite3.Connection, session_hash: str, menu: MenuResponse, locale: Literal["en", "ar"]) -> str:
    """Reuse one immutable menu view per session, inventory revision and locale."""
    previous: tuple[str] | None = connection.execute("SELECT id FROM menu_views WHERE session_hash = ? AND menu_revision = ? AND locale = ?", (session_hash, menu["revision"], locale)).fetchone()
    if previous is not None:
        return previous[0]
    view_id: str = secrets.token_urlsafe(24)
    connection.execute("INSERT INTO menu_views (id, session_hash, menu_revision, locale, menu_json) VALUES (?, ?, ?, ?, ?)", (view_id, session_hash, menu["revision"], locale, json.dumps(menu, ensure_ascii=False)))
    return view_id


def read_menu_view(connection: sqlite3.Connection, session_hash: str, view_id: str | None, menu_revision: int, locale: Literal["en", "ar"]) -> MenuResponse | None:
    if view_id is None:
        return None
    row: tuple[int, str, str] | None = connection.execute("SELECT menu_revision, locale, menu_json FROM menu_views WHERE id = ? AND session_hash = ?", (view_id, session_hash)).fetchone()
    if row is None or row[0] != menu_revision or row[1] != locale:
        raise MenuViewError("The displayed menu could not be verified. Wait for live updates, then resend your message.")
    return cast(MenuResponse, json.loads(row[2]))


def get_menu_view(path: Path, token: str, view_id: str | None, menu_revision: int, locale: Literal["en", "ar"]) -> MenuResponse | None:
    with sqlite3.connect(path) as connection:
        session_hash: str = require_session(connection, token)
        return read_menu_view(connection, session_hash, view_id, menu_revision, locale)
