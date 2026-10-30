import json
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, TypedDict, cast

from app.cart import Cart, Order, confirm_session_order, read_cart, require_session, set_session_quantity
from app.confirmation_widget import CheckoutView, build_confirmation_widget, read_confirmation_view
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


class ActionIdConflict(WidgetActionError):
    pass


class StaleWidget(WidgetActionError):
    pass


class DisabledWidgetAction(WidgetActionError):
    pass


class LocaleAction(TypedDict):
    widget_id: str
    revision: int
    action_id: str
    type: Literal["locale.set"]
    lang: Literal["en", "ar"]


class LocaleResult(TypedDict):
    locale: Literal["en", "ar"]


def set_widget_locale(path: Path, token: str, action: LocaleAction) -> LocaleResult:
    """Persist an issued locale action and its retry result in one session transaction."""
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        request: str = json.dumps(action, sort_keys=True)
        prior: tuple[str, str] | None = connection.execute("SELECT request_json, result_json FROM widget_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"])).fetchone()
        if prior is not None:
            if prior[0] != request:
                raise ActionIdConflict("Action ID was already used for a different request.")
            return cast(LocaleResult, json.loads(prior[1]))
        if connection.execute("SELECT 1 FROM cart_actions WHERE session_hash = ? AND action_id = ? UNION ALL SELECT 1 FROM order_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"], session_hash, action["action_id"])).fetchone() is not None:
            raise ActionIdConflict("Action ID was already used for a different request.")
        row: tuple[int, str] | None = connection.execute("SELECT r.revision, r.envelope_json FROM widgets w JOIN widget_revisions r ON r.widget_id = w.id WHERE w.id = ? AND w.session_hash = ? ORDER BY r.revision DESC LIMIT 1", (action["widget_id"], session_hash)).fetchone()
        if row is None or row[0] != action["revision"]:
            raise StaleWidget("Widget is unknown or out of date. Resync before switching language.")
        envelope: WidgetEnvelope = cast(WidgetEnvelope, json.loads(row[1]))
        if read_menu(connection)["revision"] != envelope["menu"]["revision"] or read_cart(connection, session_hash)["revision"] != envelope["cart_revision"]:
            raise StaleWidget("Widget is out of date. Resync before switching language.")
        if "actions" not in envelope or "locales" not in envelope["actions"] or action["lang"] not in envelope["actions"]["locales"]:
            raise DisabledWidgetAction("This language was not offered by the displayed widget.")
        result: LocaleResult = {"locale": action["lang"]}
        connection.execute("INSERT INTO session_preferences (session_hash, locale) VALUES (?, ?) ON CONFLICT(session_hash) DO UPDATE SET locale = excluded.locale", (session_hash, action["lang"]))
        connection.execute("INSERT INTO widget_actions VALUES (?, ?, ?, ?)", (session_hash, action["action_id"], request, json.dumps(result)))
        return result


def initialize_widget_actions(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS checkout_views (id TEXT PRIMARY KEY, session_hash TEXT NOT NULL, cart_revision TEXT NOT NULL, cart_json TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0)")
        columns: set[str] = {row[1] for row in connection.execute("PRAGMA table_info(checkout_views)").fetchall()}
        if "envelope_json" not in columns:
            connection.execute("ALTER TABLE checkout_views ADD COLUMN envelope_json TEXT")
        connection.execute("CREATE TABLE IF NOT EXISTS confirmation_acknowledgements (widget_id TEXT NOT NULL, locale TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(widget_id, locale))")
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
                raise ActionIdConflict("Action ID was already used for a different request.")
            return cast(Cart, json.loads(previous[1]))
        if connection.execute("SELECT 1 FROM cart_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"])).fetchone() is not None:
            raise ActionIdConflict("Action ID was already used for a different request.")
        row: tuple[int, str] | None = connection.execute("SELECT r.revision, r.envelope_json FROM widgets w JOIN widget_revisions r ON r.widget_id = w.id WHERE w.id = ? AND w.session_hash = ? ORDER BY r.revision DESC LIMIT 1", (action["widget_id"], session_hash)).fetchone()
        if row is None or row[0] != action["revision"]:
            raise StaleWidget("Widget is unknown or out of date. Refresh the menu and try again.")
        envelope: WidgetEnvelope = cast(WidgetEnvelope, json.loads(row[1]))
        if read_menu(connection)["revision"] != envelope["menu"]["revision"] or read_cart(connection, session_hash)["revision"] != envelope["cart_revision"] or action["cart_revision"] != envelope["cart_revision"]:
            raise StaleWidget("Widget is out of date. Refresh the menu and try again.")
        if not any(binding["item_id"] == action["item_id"] and binding["position"] == action["position"] and binding["minimum"] <= action["quantity"] <= binding["maximum"] for binding in envelope["actions"]["quantities"]):
            raise DisabledWidgetAction("The selected item does not match this widget. Refresh the menu and try again.")
        result: Cart = set_session_quantity(connection, session_hash, action["action_id"], action["item_id"], action["quantity"], action["cart_revision"])
        connection.execute("INSERT INTO widget_actions (session_hash, action_id, request_json, result_json) VALUES (?, ?, ?, ?)", (session_hash, action["action_id"], request_json, json.dumps(result, ensure_ascii=False)))
        return result


class CheckoutAction(TypedDict):
    widget_id: str
    revision: int
    action_id: str
    type: str
    cart_revision: str


def start_checkout(path: Path, token: str, action: CheckoutAction) -> CheckoutView:
    """Issue one active review, replacing older reviews within the session transaction."""
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        request: str = json.dumps(action, sort_keys=True)
        prior = connection.execute("SELECT request_json, result_json FROM widget_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"])).fetchone()
        if prior is not None:
            if prior[0] != request:
                raise ActionIdConflict("Action ID was already used for a different request.")
            return cast(CheckoutView, json.loads(prior[1]))
        if connection.execute("SELECT 1 FROM cart_actions WHERE session_hash = ? AND action_id = ? UNION ALL SELECT 1 FROM order_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"], session_hash, action["action_id"])).fetchone() is not None:
            raise ActionIdConflict("Action ID was already used for a different request.")
        row = connection.execute("SELECT r.revision, r.envelope_json FROM widgets w JOIN widget_revisions r ON r.widget_id = w.id WHERE w.id = ? AND w.session_hash = ? ORDER BY r.revision DESC LIMIT 1", (action["widget_id"], session_hash)).fetchone()
        if row is None or row[0] != action["revision"]:
            raise StaleWidget("Widget is unknown or out of date. Refresh the menu and try again.")
        envelope: WidgetEnvelope = cast(WidgetEnvelope, json.loads(row[1]))
        cart: Cart = read_cart(connection, session_hash)
        if read_menu(connection)["revision"] != envelope["menu"]["revision"] or cart["revision"] != envelope["cart_revision"] or cart["revision"] != action["cart_revision"]:
            raise StaleWidget("Widget is out of date. Refresh the menu and try again.")
        if not envelope["actions"]["checkout"]:
            raise WidgetActionError("Your cart is empty. Add an item before reviewing.")
        connection.execute("UPDATE checkout_views SET consumed = 1 WHERE session_hash = ?", (session_hash,))
        widget_id: str = secrets.token_urlsafe(24)
        inserted: sqlite3.Cursor = connection.execute("INSERT INTO checkout_views (id, session_hash, cart_revision, cart_json) VALUES (?, ?, ?, ?)", (widget_id, session_hash, cart["revision"], json.dumps(cart, ensure_ascii=False)))
        sequence: int | None = inserted.lastrowid
        if sequence is None:
            raise RuntimeError("The new confirmation review has no database sequence.")
        view: CheckoutView = {"kind": "widget", "role": "confirmation", "widget_id": widget_id, "revision": 1, "sequence": sequence, "actions": [{"type": "order.edit", "enabled": True}, {"type": "order.confirm", "enabled": cart["can_checkout"]}], "cart_revision": cart["revision"], "cart": cart, "payload": {"en": build_confirmation_widget(cart, "en"), "ar": build_confirmation_widget(cart, "ar")}}
        connection.execute("UPDATE checkout_views SET envelope_json = ? WHERE id = ?", (json.dumps(view, ensure_ascii=False), view["widget_id"]))
        connection.execute("INSERT INTO widget_actions VALUES (?, ?, ?, ?)", (session_hash, action["action_id"], request, json.dumps(view, ensure_ascii=False)))
        return view


def confirm_widget_order(path: Path, token: str, action: CheckoutAction) -> Order:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        request: str = json.dumps(action, sort_keys=True)
        prior = connection.execute("SELECT request_json, result_json FROM widget_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"])).fetchone()
        if prior is not None:
            if prior[0] != request:
                raise ActionIdConflict("Action ID was already used for a different request.")
            return cast(Order, json.loads(prior[1]))
        row = connection.execute("SELECT cart_revision, consumed FROM checkout_views WHERE id = ? AND session_hash = ?", (action["widget_id"], session_hash)).fetchone()
        if row is None or action["revision"] != 1 or row[0] != action["cart_revision"] or row[1] != 0:
            raise StaleWidget("The reviewed order is unknown or does not match. Review your cart again.")
        if connection.execute("SELECT 1 FROM cart_actions WHERE session_hash = ? AND action_id = ? UNION ALL SELECT 1 FROM order_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"], session_hash, action["action_id"])).fetchone() is not None:
            raise ActionIdConflict("Action ID was already used for a different request.")
        view: CheckoutView = read_confirmation_view(connection, session_hash, {"widget_id": action["widget_id"], "revision": action["revision"]})
        if not any(binding["type"] == "order.confirm" and binding["enabled"] for binding in view["actions"]):
            raise DisabledWidgetAction("This confirmation control was disabled. Review your cart again.")
        order: Order = confirm_session_order(connection, session_hash, action["action_id"], action["cart_revision"])
        connection.execute("INSERT INTO widget_actions VALUES (?, ?, ?, ?)", (session_hash, action["action_id"], request, json.dumps(order, ensure_ascii=False)))
        return order


def edit_widget_order(path: Path, token: str, action: CheckoutAction) -> dict[str, bool]:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        request: str = json.dumps(action, sort_keys=True)
        prior = connection.execute("SELECT request_json, result_json FROM widget_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"])).fetchone()
        if prior is not None:
            if prior[0] != request:
                raise ActionIdConflict("Action ID was already used for a different request.")
            return cast(dict[str, bool], json.loads(prior[1]))
        if connection.execute("SELECT 1 FROM cart_actions WHERE session_hash = ? AND action_id = ? UNION ALL SELECT 1 FROM order_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"], session_hash, action["action_id"])).fetchone() is not None:
            raise ActionIdConflict("Action ID was already used for a different request.")
        row = connection.execute("SELECT cart_revision FROM checkout_views WHERE id = ? AND session_hash = ?", (action["widget_id"], session_hash)).fetchone()
        if row is None or action["revision"] != 1 or row[0] != action["cart_revision"]:
            raise StaleWidget("The reviewed order is unknown. Review your cart again.")
        connection.execute("UPDATE checkout_views SET consumed = 1 WHERE id = ? AND session_hash = ?", (action["widget_id"], session_hash))
        result: dict[str, bool] = {"edited": True}
        connection.execute("INSERT INTO widget_actions VALUES (?, ?, ?, ?)", (session_hash, action["action_id"], request, json.dumps(result)))
        return result
