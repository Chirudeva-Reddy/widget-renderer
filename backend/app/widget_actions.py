import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TypedDict, cast

from app.cart import Cart, CartError, read_cart, require_session, set_session_quantity
from app.menu import read_menu
from app.widgets import WidgetEnvelope


class QuantityAction(TypedDict):
    widget_id: str
    revision: int
    action_id: str
    type: str
    item_id: str
    position: int
    quantity: int
    cart_revision: str


class WidgetActionError(ValueError):
    pass


def initialize_widget_actions(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS widget_actions (session_hash TEXT NOT NULL, action_id TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(session_hash, action_id))")


def apply_widget_quantity(path: Path, token: str, action: QuantityAction) -> Cart:
    """Verify the issued menu and apply its quantity action atomically."""
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        request_json: str = json.dumps(action, sort_keys=True, ensure_ascii=False)
        previous: tuple[str, str] | None = connection.execute("SELECT request_json, result_json FROM widget_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"])).fetchone()
        if previous is not None:
            if previous[0] != request_json:
                raise WidgetActionError("Action ID was already used for a different request.")
            return cast(Cart, json.loads(previous[1]))
        if connection.execute("SELECT 1 FROM cart_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"])).fetchone() is not None:
            raise WidgetActionError("Action ID was already used for a different request.")
        row: tuple[int, str] | None = connection.execute("SELECT r.revision, r.envelope_json FROM widgets w JOIN widget_revisions r ON r.widget_id = w.id WHERE w.id = ? AND w.session_hash = ? ORDER BY r.revision DESC LIMIT 1", (action["widget_id"], session_hash)).fetchone()
        if row is None or row[0] != action["revision"]:
            raise WidgetActionError("Widget is unknown or out of date. Refresh the menu and try again.")
        envelope: WidgetEnvelope = cast(WidgetEnvelope, json.loads(row[1]))
        if read_menu(connection)["revision"] != envelope["menu"]["revision"] or read_cart(connection, session_hash)["revision"] != envelope["cart_revision"] or action["cart_revision"] != envelope["cart_revision"]:
            raise WidgetActionError("Widget is out of date. Refresh the menu and try again.")
        if not any(item["id"] == action["item_id"] and item["position"] == action["position"] for item in envelope["menu"]["items"]):
            raise WidgetActionError("The selected item does not match this widget. Refresh the menu and try again.")
        result: Cart = set_session_quantity(connection, session_hash, action["action_id"], action["item_id"], action["quantity"], action["cart_revision"])
        connection.execute("INSERT INTO widget_actions (session_hash, action_id, request_json, result_json) VALUES (?, ?, ?, ?)", (session_hash, action["action_id"], request_json, json.dumps(result, ensure_ascii=False)))
        return result
