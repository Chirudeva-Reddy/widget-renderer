import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TypedDict

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


def read_snapshot(path: Path, token: str) -> Snapshot:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        menu: MenuResponse = read_menu(connection)
        cart: Cart = read_cart(connection, session_hash)
        return {"menu": menu, "cart": cart, "menu_view_ids": {"en": issue_menu_view(connection, session_hash, menu, "en"), "ar": issue_menu_view(connection, session_hash, menu, "ar")}, "menu_widgets": {locale: build_menu_widget(menu, locale) for locale in ("en", "ar")}}
