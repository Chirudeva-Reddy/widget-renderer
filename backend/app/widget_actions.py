import json
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

from app.cart import Cart, Order, confirm_session_order, read_cart, record_completed_action, require_session, set_session_quantity
from app.confirmation_widget import CheckoutView, build_confirmation_widget, read_confirmation_view
from app.menu import MenuResponse, read_menu
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


class ItemAction(TypedDict):
    widget_id: str
    revision: int
    action_id: str
    type: str
    item_id: str
    position: int


class WidgetActionError(ValueError):
    pass


class GenericBinding(TypedDict):
    key: str
    type: Literal["cart.add", "cart.remove", "cart.set_quantity"]
    item_id: str
    position: int
    enabled: bool
    label: str
    quantities: NotRequired[list[int]]


class GenericWidget(TypedDict):
    widget_id: str
    revision: int
    menu_revision: int
    cart_revision: str
    bindings: list[GenericBinding]


def bind_generic_actions(tree: dict[str, object], menu: MenuResponse, cart: Cart, locale: Literal["en", "ar"]) -> list[GenericBinding]:
    """Bind keyed buttons only to known, currently permitted menu actions."""
    bindings: list[GenericBinding] = []
    seen: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            if value.get("type") in ("Button", "Form", "Select") and isinstance(value.get("key"), str) and str(value["key"]).startswith("action:"):
                key = value.get("key")
                if not isinstance(key, str) or key in seen:
                    raise WidgetActionError("Widget buttons require unique action bindings.")
                parts: list[str] = key.split(":", 2)
                if len(parts) != 3 or parts[0] != "action" or parts[1] not in ("cart.add", "cart.remove", "cart.set_quantity"):
                    raise WidgetActionError("Widget button has an unsupported action binding.")
                item = next((item for item in menu["items"] if item["id"] == parts[2]), None)
                if item is None:
                    raise WidgetActionError("Widget button refers to an unknown item.")
                quantity: int = next((entry["quantity"] for entry in cart["items"] if entry["id"] == item["id"]), 0)
                kind = cast(Literal["cart.add", "cart.remove", "cart.set_quantity"], parts[1])
                label: str = ("إضافة" if kind == "cart.add" else "إزالة") if locale == "ar" else ("Add" if kind == "cart.add" else "Remove")
                bindings.append({"key": key, "type": kind, "item_id": item["id"], "position": item["position"], "enabled": item["available"] and quantity < 99 if kind == "cart.add" else quantity > 0, "label": f"{label} {item['name'][locale]}"})
                if kind == "cart.set_quantity":
                    fields = value.get("children", []) if value.get("type") == "Form" else [value]
                    quantity_fields = [field for field in fields if isinstance(field, dict) and field.get("type") in ("Input", "Select")]
                    if len(quantity_fields) != 1 or quantity_fields[0].get("name") != "quantity" or quantity_fields[0].get("disabled", False):
                        raise WidgetActionError("Quantity actions require one enabled quantity field.")
                    field = quantity_fields[0]
                    allowed: list[int] = list(range(100))
                    if field.get("type") == "Select":
                        options = field.get("options", [])
                        if not isinstance(options, list) or any(not isinstance(option, dict) or not str(option.get("value", "")).isascii() or not str(option.get("value", "")).isdigit() or int(str(option["value"])) > 99 for option in options):
                            raise WidgetActionError("Quantity options must be integers between 0 and 99.")
                        allowed = [int(str(option["value"])) for option in options if not option.get("disabled", False)]
                    bindings[-1]["quantities"] = allowed
                    bindings[-1]["enabled"] = bool(allowed)
                    bindings[-1]["label"] = "تطبيق الكمية" if locale == "ar" else "Apply quantity"
                bindings[-1]["enabled"] = bindings[-1]["enabled"] and not value.get("disabled", False)
                seen.add(key)
            for child in value.values():
                visit(child)

    visit(tree)
    return bindings


class LocaleAction(TypedDict):
    widget_id: str
    revision: int
    action_id: str
    type: Literal["locale.set"]
    lang: Literal["en", "ar"]


def set_widget_locale(path: Path, token: str, action: LocaleAction) -> dict[str, str]:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        request: str = json.dumps(action, sort_keys=True)
        prior = connection.execute("SELECT request_json, result_json FROM widget_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"])).fetchone()
        if prior is not None:
            if prior[0] != request:
                raise WidgetActionError("Action ID was already used for a different request.")
            return cast(dict[str, str], json.loads(prior[1]))
        if connection.execute("SELECT 1 FROM cart_actions WHERE session_hash = ? AND action_id = ? UNION ALL SELECT 1 FROM order_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"], session_hash, action["action_id"])).fetchone() is not None:
            raise WidgetActionError("Action ID was already used for a different request.")
        row = connection.execute("SELECT r.revision, r.envelope_json FROM widgets w JOIN widget_revisions r ON r.widget_id = w.id WHERE w.id = ? AND w.session_hash = ? ORDER BY r.revision DESC LIMIT 1", (action["widget_id"], session_hash)).fetchone()
        if row is None or row[0] != action["revision"]:
            raise WidgetActionError("Widget is unknown or out of date. Refresh the menu and try again.")
        envelope: WidgetEnvelope = cast(WidgetEnvelope, json.loads(row[1]))
        if read_menu(connection)["revision"] != envelope["menu"]["revision"] or read_cart(connection, session_hash)["revision"] != envelope["cart_revision"]:
            raise WidgetActionError("Widget is out of date. Refresh the menu and try again.")
        result: dict[str, str] = {"lang": action["lang"]}
        connection.execute("INSERT INTO widget_actions VALUES (?, ?, ?, ?)", (session_hash, action["action_id"], request, json.dumps(result)))
        record_completed_action(connection, session_hash, action["action_id"], "locale.set", read_cart(connection, session_hash)["revision"])
        return result


def initialize_widget_actions(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS checkout_views (id TEXT PRIMARY KEY, session_hash TEXT NOT NULL, cart_revision TEXT NOT NULL, cart_json TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0)")
        columns: set[str] = {row[1] for row in connection.execute("PRAGMA table_info(checkout_views)").fetchall()}
        if "envelope_json" not in columns:
            connection.execute("ALTER TABLE checkout_views ADD COLUMN envelope_json TEXT")
        connection.execute("CREATE TABLE IF NOT EXISTS confirmation_acknowledgements (widget_id TEXT NOT NULL, locale TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(widget_id, locale))")
        acknowledgement_columns: set[str] = {row[1] for row in connection.execute("PRAGMA table_info(confirmation_acknowledgements)")}
        if "rendered_json" not in acknowledgement_columns:
            connection.execute("ALTER TABLE confirmation_acknowledgements ADD COLUMN rendered_json TEXT")
        connection.execute("CREATE TABLE IF NOT EXISTS widget_actions (session_hash TEXT NOT NULL, action_id TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(session_hash, action_id))")
        connection.execute("CREATE TABLE IF NOT EXISTS generic_widgets (id TEXT PRIMARY KEY, session_hash TEXT NOT NULL, revision INTEGER NOT NULL, menu_revision INTEGER NOT NULL, cart_revision TEXT NOT NULL, bindings_json TEXT NOT NULL)")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(generic_widgets)")}
        if "payload_json" not in columns:
            connection.execute("ALTER TABLE generic_widgets ADD COLUMN payload_json TEXT")
        if "rendered_json" not in columns:
            connection.execute("ALTER TABLE generic_widgets ADD COLUMN rendered_json TEXT")
        if "role" not in columns:
            connection.execute("ALTER TABLE generic_widgets ADD COLUMN role TEXT")


def apply_widget_quantity(path: Path, token: str, action: QuantityAction | ItemAction) -> Cart:
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
        cart: Cart = read_cart(connection, session_hash)
        if row is None:
            generic = connection.execute("SELECT revision, menu_revision, cart_revision, bindings_json FROM generic_widgets WHERE id = ? AND session_hash = ?", (action["widget_id"], session_hash)).fetchone()
            if generic is None or generic[0] != action["revision"] or generic[1] != read_menu(connection)["revision"] or generic[2] != cart["revision"]:
                raise WidgetActionError("Widget is unknown or out of date. Refresh the widget and try again.")
            bindings: list[GenericBinding] = json.loads(generic[3])
            if not any(binding["type"] == action["type"] and binding["item_id"] == action["item_id"] and binding["position"] == action["position"] and binding["enabled"] for binding in bindings):
                raise WidgetActionError("The action is not enabled for this widget.")
            current: int = next((item["quantity"] for item in cart["items"] if item["id"] == action["item_id"]), 0)
            quantity: int = action["quantity"] if "quantity" in action else current + 1 if action["type"] == "cart.add" else 0
            if "cart_revision" in action and action["cart_revision"] != generic[2]:
                raise WidgetActionError("The cart revision does not match this widget.")
            if action["type"] == "cart.set_quantity" and not any(binding["type"] == action["type"] and binding["item_id"] == action["item_id"] and quantity in binding.get("quantities", []) for binding in bindings):
                raise WidgetActionError("Quantity is not enabled for this widget.")
            result: Cart = set_session_quantity(connection, session_hash, action["action_id"], action["item_id"], quantity, generic[2])
            connection.execute("INSERT INTO widget_actions (session_hash, action_id, request_json, result_json) VALUES (?, ?, ?, ?)", (session_hash, action["action_id"], request_json, json.dumps(result, ensure_ascii=False)))
            connection.execute("UPDATE completed_actions SET kind = ? WHERE session_hash = ? AND action_id = ?", (action["type"], session_hash, action["action_id"]))
            return result
        if row[0] != action["revision"]:
            raise WidgetActionError("Widget is unknown or out of date. Refresh the menu and try again.")
        envelope: WidgetEnvelope = cast(WidgetEnvelope, json.loads(row[1]))
        if read_menu(connection)["revision"] != envelope["menu"]["revision"] or cart["revision"] != envelope["cart_revision"] or ("cart_revision" in action and action["cart_revision"] != envelope["cart_revision"]):
            raise WidgetActionError("Widget is out of date. Refresh the menu and try again.")
        current: int = next((item["quantity"] for item in cart["items"] if item["id"] == action["item_id"]), 0)
        if action["type"] == "cart.remove" and current == 0:
            raise WidgetActionError("The selected item is not in the cart.")
        quantity: int = action["quantity"] if "quantity" in action else current + 1 if action["type"] == "cart.add" else 0
        if not any(binding["item_id"] == action["item_id"] and binding["position"] == action["position"] and binding["minimum"] <= quantity <= binding["maximum"] for binding in envelope["actions"]["quantities"]):
            raise WidgetActionError("The selected item does not match this widget. Refresh the menu and try again.")
        result: Cart = set_session_quantity(connection, session_hash, action["action_id"], action["item_id"], quantity, envelope["cart_revision"])
        connection.execute("INSERT INTO widget_actions (session_hash, action_id, request_json, result_json) VALUES (?, ?, ?, ?)", (session_hash, action["action_id"], request_json, json.dumps(result, ensure_ascii=False)))
        if action["type"] != "cart.set_quantity":
            connection.execute("UPDATE completed_actions SET kind = ? WHERE session_hash = ? AND action_id = ?", (action["type"], session_hash, action["action_id"]))
        return result


class CheckoutAction(TypedDict):
    widget_id: str
    revision: int
    action_id: str
    type: str
    cart_revision: str


def start_checkout(path: Path, token: str, action: CheckoutAction) -> CheckoutView:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        request: str = json.dumps(action, sort_keys=True)
        prior = connection.execute("SELECT request_json, result_json FROM widget_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"])).fetchone()
        if prior is not None:
            if prior[0] != request:
                raise WidgetActionError("Action ID was already used for a different request.")
            return cast(CheckoutView, json.loads(prior[1]))
        if connection.execute("SELECT 1 FROM cart_actions WHERE session_hash = ? AND action_id = ? UNION ALL SELECT 1 FROM order_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"], session_hash, action["action_id"])).fetchone() is not None:
            raise WidgetActionError("Action ID was already used for a different request.")
        row = connection.execute("SELECT r.revision, r.envelope_json FROM widgets w JOIN widget_revisions r ON r.widget_id = w.id WHERE w.id = ? AND w.session_hash = ? ORDER BY r.revision DESC LIMIT 1", (action["widget_id"], session_hash)).fetchone()
        if row is None or row[0] != action["revision"]:
            raise WidgetActionError("Widget is unknown or out of date. Refresh the menu and try again.")
        envelope: WidgetEnvelope = cast(WidgetEnvelope, json.loads(row[1]))
        cart: Cart = read_cart(connection, session_hash)
        if read_menu(connection)["revision"] != envelope["menu"]["revision"] or cart["revision"] != envelope["cart_revision"] or cart["revision"] != action["cart_revision"]:
            raise WidgetActionError("Widget is out of date. Refresh the menu and try again.")
        if not envelope["actions"]["checkout"]:
            raise WidgetActionError("Your cart is empty. Add an item before reviewing.")
        view: CheckoutView = {"kind": "widget", "role": "confirmation", "widget_id": secrets.token_urlsafe(24), "revision": 1, "actions": [{"type": "order.edit", "enabled": True}, {"type": "order.confirm", "enabled": cart["can_checkout"]}], "cart_revision": cart["revision"], "cart": cart, "payload": {"en": build_confirmation_widget(cart, "en"), "ar": build_confirmation_widget(cart, "ar")}}
        connection.execute("INSERT INTO checkout_views (id, session_hash, cart_revision, cart_json, envelope_json) VALUES (?, ?, ?, ?, ?)", (view["widget_id"], session_hash, cart["revision"], json.dumps(cart, ensure_ascii=False), json.dumps(view, ensure_ascii=False)))
        connection.execute("INSERT INTO widget_actions VALUES (?, ?, ?, ?)", (session_hash, action["action_id"], request, json.dumps(view, ensure_ascii=False)))
        record_completed_action(connection, session_hash, action["action_id"], "checkout.start", cart["revision"])
        return view


def confirm_widget_order(path: Path, token: str, action: CheckoutAction) -> Order:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        request: str = json.dumps(action, sort_keys=True)
        prior = connection.execute("SELECT request_json, result_json FROM widget_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"])).fetchone()
        if prior is not None:
            if prior[0] != request:
                raise WidgetActionError("Action ID was already used for a different request.")
            return cast(Order, json.loads(prior[1]))
        row = connection.execute("SELECT cart_revision, consumed FROM checkout_views WHERE id = ? AND session_hash = ?", (action["widget_id"], session_hash)).fetchone()
        if row is None or action["revision"] != 1 or row[0] != action["cart_revision"] or row[1] != 0:
            raise WidgetActionError("The reviewed order is unknown or does not match. Review your cart again.")
        if connection.execute("SELECT 1 FROM cart_actions WHERE session_hash = ? AND action_id = ? UNION ALL SELECT 1 FROM order_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"], session_hash, action["action_id"])).fetchone() is not None:
            raise WidgetActionError("Action ID was already used for a different request.")
        view: CheckoutView = read_confirmation_view(connection, session_hash, {"widget_id": action["widget_id"], "revision": action["revision"]})
        if not any(binding["type"] == "order.confirm" and binding["enabled"] for binding in view["actions"]):
            raise WidgetActionError("This confirmation control was disabled. Review your cart again.")
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
                raise WidgetActionError("Action ID was already used for a different request.")
            return cast(dict[str, bool], json.loads(prior[1]))
        if connection.execute("SELECT 1 FROM cart_actions WHERE session_hash = ? AND action_id = ? UNION ALL SELECT 1 FROM order_actions WHERE session_hash = ? AND action_id = ?", (session_hash, action["action_id"], session_hash, action["action_id"])).fetchone() is not None:
            raise WidgetActionError("Action ID was already used for a different request.")
        row = connection.execute("SELECT cart_revision FROM checkout_views WHERE id = ? AND session_hash = ?", (action["widget_id"], session_hash)).fetchone()
        if row is None or action["revision"] != 1 or row[0] != action["cart_revision"]:
            raise WidgetActionError("The reviewed order is unknown. Review your cart again.")
        connection.execute("UPDATE checkout_views SET consumed = 1 WHERE id = ? AND session_hash = ?", (action["widget_id"], session_hash))
        result: dict[str, bool] = {"edited": True}
        connection.execute("INSERT INTO widget_actions VALUES (?, ?, ?, ?)", (session_hash, action["action_id"], request, json.dumps(result)))
        record_completed_action(connection, session_hash, action["action_id"], "order.edit", read_cart(connection, session_hash)["revision"])
        return result
