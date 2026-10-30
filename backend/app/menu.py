import sqlite3
from pathlib import Path
from typing import Literal, TypedDict


class LocalizedText(TypedDict):
    en: str
    ar: str


class MenuItem(TypedDict):
    id: str
    position: int
    name: LocalizedText
    price_minor: int
    currency: Literal["AED"]
    available: bool


class MenuResponse(TypedDict):
    revision: int
    items: list[MenuItem]


class ItemNotFoundError(ValueError):
    pass


DATABASE_PATH: Path = Path(__file__).resolve().parent.parent / "restaurant.sqlite"


def initialize_menu(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS menu_items (id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, name_en TEXT NOT NULL, name_ar TEXT NOT NULL, price_minor INTEGER NOT NULL CHECK(price_minor >= 0), available INTEGER NOT NULL CHECK(available IN (0, 1)))")
        connection.execute("CREATE TABLE IF NOT EXISTS menu_metadata (id INTEGER PRIMARY KEY CHECK(id = 1), revision INTEGER NOT NULL)")
        connection.execute("INSERT OR IGNORE INTO menu_metadata (id, revision) VALUES (1, 1)")
        connection.executemany(
            "INSERT OR IGNORE INTO menu_items (id, position, name_en, name_ar, price_minor, available) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("hummus", 1, "Hummus", "حمص", 1800, 1),
                ("falafel", 2, "Falafel", "فلافل", 2200, 1),
                ("tabbouleh", 3, "Tabbouleh", "تبولة", 2000, 1),
                ("shawarma", 4, "Chicken shawarma", "شاورما دجاج", 2800, 1),
            ],
        )


def read_menu(connection: sqlite3.Connection) -> MenuResponse:
    metadata = connection.execute("SELECT revision FROM menu_metadata WHERE id = 1").fetchone()
    if metadata is None:
        raise RuntimeError("Menu metadata is missing; initialize the restaurant database.")
    rows = connection.execute("SELECT id, position, name_en, name_ar, price_minor, available FROM menu_items ORDER BY position").fetchall()
    return {
        "revision": metadata[0],
        "items": [
            {"id": row[0], "position": row[1], "name": {"en": row[2], "ar": row[3]}, "price_minor": row[4], "currency": "AED", "available": bool(row[5])}
            for row in rows
        ],
    }


def get_menu(path: Path) -> MenuResponse:
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN")
        return read_menu(connection)


def sell_out_item(path: Path, item_id: str) -> MenuResponse:
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT available FROM menu_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise ItemNotFoundError("Menu item does not exist.")
        if row[0] == 1:
            connection.execute("UPDATE menu_items SET available = 0 WHERE id = ?", (item_id,))
            connection.execute("UPDATE menu_metadata SET revision = revision + 1 WHERE id = 1")
            connection.execute("UPDATE checkout_views SET consumed = 1 WHERE session_hash IN (SELECT session_hash FROM cart_items WHERE item_id = ?)", (item_id,))
    return get_menu(path)


def restock_item(path: Path, item_id: str) -> MenuResponse:
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT available FROM menu_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise ItemNotFoundError("Menu item does not exist.")
        if row[0] == 0:
            connection.execute("UPDATE menu_items SET available = 1 WHERE id = ?", (item_id,))
            connection.execute("UPDATE menu_metadata SET revision = revision + 1 WHERE id = 1")
            connection.execute("UPDATE checkout_views SET consumed = 1 WHERE session_hash IN (SELECT session_hash FROM cart_items WHERE item_id = ?)", (item_id,))
    return get_menu(path)
