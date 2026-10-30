import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TypedDict

from app.cart import Cart, read_cart, require_session
from app.menu import MenuResponse, read_menu


class Snapshot(TypedDict):
    menu: MenuResponse
    cart: Cart


def read_snapshot(path: Path, token: str) -> Snapshot:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN")
        session_hash: str = require_session(connection, token)
        menu: MenuResponse = read_menu(connection)
        cart: Cart = read_cart(connection, session_hash)
        return {"menu": menu, "cart": cart}
