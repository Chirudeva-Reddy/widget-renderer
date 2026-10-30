import json
import hashlib
import secrets
import sqlite3
import time
from pathlib import Path
from typing import TypedDict, cast


class CartItem(TypedDict):
    id: str
    name_en: str
    name_ar: str
    quantity: int
    price_minor: int
    available: bool


class Cart(TypedDict):
    items: list[CartItem]
    total_minor: int
    currency: str
    can_checkout: bool
    revision: str


class SessionError(ValueError):
    pass


class CartError(ValueError):
    pass


def initialize_cart(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS cart_items (session_hash TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 99), PRIMARY KEY (session_hash, item_id), FOREIGN KEY (session_hash) REFERENCES sessions(token_hash), FOREIGN KEY (item_id) REFERENCES menu_items(id))")
        connection.execute("CREATE TABLE IF NOT EXISTS cart_actions (session_hash TEXT NOT NULL, action_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, result_json TEXT NOT NULL, cart_revision TEXT NOT NULL, PRIMARY KEY (session_hash, action_id))")

        columns: set[str] = {row[1] for row in connection.execute("PRAGMA table_info(cart_actions)").fetchall()}
        if "cart_revision" not in columns:
            connection.execute("ALTER TABLE cart_actions ADD COLUMN cart_revision TEXT NOT NULL DEFAULT ''")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(path: Path) -> str:
    token: str = secrets.token_urlsafe(32)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO sessions (token_hash, expires_at) VALUES (?, ?)", (token_hash(token), int(time.time()) + 86400))
    return token


def require_session(connection: sqlite3.Connection, token: str) -> str:
    session_hash: str = token_hash(token)
    row = connection.execute("SELECT expires_at FROM sessions WHERE token_hash = ?", (session_hash,)).fetchone()
    if row is None or row[0] <= int(time.time()):
        raise SessionError("Session is missing or expired.")
    return session_hash


def read_cart(connection: sqlite3.Connection, session_hash: str) -> Cart:
    rows = connection.execute("SELECT m.id, m.name_en, m.name_ar, c.quantity, m.price_minor, m.available FROM cart_items c JOIN menu_items m ON m.id = c.item_id WHERE c.session_hash = ? ORDER BY m.position", (session_hash,)).fetchall()
    items: list[CartItem] = [{"id": row[0], "name_en": row[1], "name_ar": row[2], "quantity": row[3], "price_minor": row[4], "available": bool(row[5])} for row in rows]
    revision: str = hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"items": items, "total_minor": sum(item["quantity"] * item["price_minor"] for item in items), "currency": "AED", "can_checkout": bool(items) and all(item["available"] for item in items), "revision": revision}


def get_cart(path: Path, token: str) -> Cart:
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN")
        session_hash: str = require_session(connection, token)
        return read_cart(connection, session_hash)


def set_quantity(path: Path, token: str, action_id: str, item_id: str, quantity: int, cart_revision: str) -> Cart:
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        if connection.execute("SELECT 1 FROM order_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action_id)).fetchone() is not None:
            raise CartError("Action ID was already used for a different request.")
        previous = connection.execute("SELECT item_id, quantity, result_json, cart_revision FROM cart_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action_id)).fetchone()
        if previous is not None:
            if previous[:2] != (item_id, quantity) or previous[3] != cart_revision:
                raise CartError("Action ID was already used for a different request.")
            return cast(Cart, json.loads(previous[2]))
        if read_cart(connection, session_hash)["revision"] != cart_revision:
            raise CartError("Your cart changed. Review the updated cart and try again.")
        item = connection.execute("SELECT available FROM menu_items WHERE id = ?", (item_id,)).fetchone()
        if item is None:
            raise CartError("Menu item does not exist.")
        existing = connection.execute("SELECT quantity FROM cart_items WHERE session_hash = ? AND item_id = ?", (session_hash, item_id)).fetchone()
        current: int = existing[0] if existing is not None else 0
        if not item[0] and quantity > current:
            raise CartError("Item is sold out; its quantity cannot be increased.")
        if quantity == 0:
            connection.execute("DELETE FROM cart_items WHERE session_hash = ? AND item_id = ?", (session_hash, item_id))
        else:
            connection.execute("INSERT INTO cart_items (session_hash, item_id, quantity) VALUES (?, ?, ?) ON CONFLICT(session_hash, item_id) DO UPDATE SET quantity = excluded.quantity", (session_hash, item_id, quantity))
        result: Cart = read_cart(connection, session_hash)
        connection.execute("INSERT INTO cart_actions (session_hash, action_id, item_id, quantity, result_json, cart_revision) VALUES (?, ?, ?, ?, ?, ?)", (session_hash, action_id, item_id, quantity, json.dumps(result, ensure_ascii=False), cart_revision))
        return result


class Order(TypedDict):
    order_id: str
    status: str
    items: list[CartItem]
    total_minor: int
    currency: str


def initialize_orders(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, session_hash TEXT NOT NULL, result_json TEXT NOT NULL, created_at INTEGER NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS order_actions (session_hash TEXT NOT NULL, action_id TEXT NOT NULL, order_id TEXT NOT NULL, cart_revision TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY (session_hash, action_id))")
        columns: set[str] = {row[1] for row in connection.execute("PRAGMA table_info(order_actions)").fetchall()}
        if "cart_revision" not in columns:
            connection.execute("ALTER TABLE order_actions ADD COLUMN cart_revision TEXT NOT NULL DEFAULT ''")


def confirm_order(path: Path, token: str, action_id: str, cart_revision: str) -> Order:
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        previous = connection.execute("SELECT result_json, cart_revision FROM order_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action_id)).fetchone()
        if previous is not None:
            if previous[1] != cart_revision:
                raise CartError("Action ID was already used for a different request.")
            return cast(Order, json.loads(previous[0]))
        if connection.execute("SELECT 1 FROM cart_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action_id)).fetchone() is not None:
            raise CartError("Action ID was already used for a different request.")
        cart: Cart = read_cart(connection, session_hash)
        if cart["revision"] != cart_revision:
            raise CartError("Your cart or availability changed. Refresh your cart and review it before confirming.")
        if not cart["items"]:
            raise CartError("Your cart is empty. Add an item before confirming.")
        if not cart["can_checkout"]:
            raise CartError("An item is sold out. Remove it before confirming.")
        order: Order = {"order_id": secrets.token_urlsafe(12), "status": "confirmed", "items": cart["items"], "total_minor": cart["total_minor"], "currency": cart["currency"]}
        result_json: str = json.dumps(order, ensure_ascii=False)
        connection.execute("INSERT INTO orders (id, session_hash, result_json, created_at) VALUES (?, ?, ?, ?)", (order["order_id"], session_hash, result_json, int(time.time())))
        connection.execute("INSERT INTO order_actions (session_hash, action_id, order_id, cart_revision, result_json) VALUES (?, ?, ?, ?, ?)", (session_hash, action_id, order["order_id"], cart_revision, result_json))
        connection.execute("DELETE FROM cart_items WHERE session_hash = ?", (session_hash,))
        return order
