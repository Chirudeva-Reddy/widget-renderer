import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, TypedDict

from app.widgets import WidgetEnvelope, issue_widget

from app.confirmation_widget import ConfirmationStatus, read_latest_confirmation_status
from app.cart import Cart, read_cart, require_session
from app.menu_views import issue_menu_view
from app.menu_widget import build_menu_widget
from app.validator import ContainerNode
from app.menu import MenuResponse, read_menu


class Snapshot(TypedDict):
    state_revision: int
    locale: Literal["en", "ar"]
    confirmation: ConfirmationStatus | None
    menu: MenuResponse
    cart: Cart
    menu_widgets: dict[str, ContainerNode]
    menu_view_ids: dict[str, str]
    widgets: dict[str, WidgetEnvelope]


def read_snapshot(path: Path, token: str) -> Snapshot:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        return read_session_snapshot(connection, session_hash)


def read_session_snapshot(connection: sqlite3.Connection, session_hash: str) -> Snapshot:
    """Allocate a durable revision for changed snapshot content in the caller transaction."""
    menu: MenuResponse = read_menu(connection)
    cart: Cart = read_cart(connection, session_hash)
    ids: dict[str, str] = {"en": issue_menu_view(connection, session_hash, menu, "en"), "ar": issue_menu_view(connection, session_hash, menu, "ar")}
    menus: dict[str, ContainerNode] = {locale: build_menu_widget(menu, locale) for locale in ("en", "ar")}
    widgets: dict[str, WidgetEnvelope] = {locale: issue_widget(connection, session_hash, locale, menu, cart, menus[locale], ids[locale]) for locale in ("en", "ar")}
    preference: tuple[Literal["en", "ar"]] | None = connection.execute("SELECT locale FROM session_preferences WHERE session_hash = ?", (session_hash,)).fetchone()
    locale: Literal["en", "ar"] = "en" if preference is None else preference[0]
    confirmation: ConfirmationStatus | None = read_latest_confirmation_status(connection, session_hash, cart["revision"])
    fingerprint: str = hashlib.sha256(json.dumps({"locale": locale, "confirmation": confirmation, "menu": menu, "cart": cart, "widgets": widgets}, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    previous: tuple[int, str] | None = connection.execute("SELECT revision, fingerprint FROM session_snapshots WHERE session_hash = ?", (session_hash,)).fetchone()
    revision: int = 1 if previous is None else previous[0] + int(previous[1] != fingerprint)
    connection.execute("INSERT INTO session_snapshots (session_hash, revision, fingerprint) VALUES (?, ?, ?) ON CONFLICT(session_hash) DO UPDATE SET revision = excluded.revision, fingerprint = excluded.fingerprint", (session_hash, revision, fingerprint))
    return {"locale": locale, "confirmation": confirmation, "state_revision": revision, "menu": menu, "cart": cart, "menu_view_ids": ids, "menu_widgets": menus, "widgets": widgets}


def issue_menu_widget(path: Path, token: str, locale: Literal["en", "ar"]) -> WidgetEnvelope:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        snapshot: Snapshot = read_session_snapshot(connection, session_hash)
        return issue_widget(connection, session_hash, locale, snapshot["menu"], snapshot["cart"], snapshot["menu_widgets"][locale], snapshot["menu_view_ids"][locale])
