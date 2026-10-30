import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, TypedDict

from app.widgets import WidgetEnvelope, issue_widget

from app.cart import Cart, read_cart, require_session
from app.menu_views import issue_menu_view
from app.menu_widget import build_menu_widget
from app.validator import ContainerNode
from app.menu import MenuResponse, read_menu


class Snapshot(TypedDict):
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
    menu: MenuResponse = read_menu(connection)
    cart: Cart = read_cart(connection, session_hash)
    ids: dict[str, str] = {"en": issue_menu_view(connection, session_hash, menu, "en"), "ar": issue_menu_view(connection, session_hash, menu, "ar")}
    menus: dict[str, ContainerNode] = {locale: build_menu_widget(menu, locale) for locale in ("en", "ar")}
    widgets: dict[str, WidgetEnvelope] = {locale: issue_widget(connection, session_hash, locale, menu, cart, menus[locale], ids[locale]) for locale in ("en", "ar")}
    return {"menu": menu, "cart": cart, "menu_view_ids": ids, "menu_widgets": menus, "widgets": widgets}


def issue_menu_widget(path: Path, token: str, locale: Literal["en", "ar"]) -> WidgetEnvelope:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        snapshot: Snapshot = read_session_snapshot(connection, session_hash)
        return issue_widget(connection, session_hash, locale, snapshot["menu"], snapshot["cart"], snapshot["menu_widgets"][locale], snapshot["menu_view_ids"][locale])
