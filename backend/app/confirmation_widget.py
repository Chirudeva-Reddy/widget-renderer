import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, TypedDict, cast

from app.cart import Cart, read_cart, require_session
from app.validator import ContainerNode, validate_source


class ConfirmationViewError(ValueError):
    pass


class ConfirmationPayloads(TypedDict):
    en: ContainerNode
    ar: ContainerNode


class ConfirmationActionBinding(TypedDict):
    type: Literal["order.confirm", "order.edit"]
    enabled: bool


class CheckoutView(TypedDict):
    kind: Literal["widget"]
    role: Literal["confirmation"]
    payload: ConfirmationPayloads
    actions: list[ConfirmationActionBinding]
    cart_revision: str
    widget_id: str
    revision: int
    cart: Cart


class ConfirmationReference(TypedDict):
    widget_id: str
    revision: int


def validate_confirmation_rendered(view: CheckoutView, rendered: dict[str, object], locale: Literal["en", "ar"]) -> None:
    rows = rendered.get("rows")
    if rendered.get("locale") != locale or not isinstance(rows, list) or len(rows) != len(view["cart"]["items"]):
        raise ConfirmationViewError("Rendered confirmation does not match the issued review.")
    for row, item in zip(rows, view["cart"]["items"], strict=True):
        if not isinstance(row, dict) or row.get("item_id") != item["id"] or row.get("quantity") != item["quantity"] or row.get("sold_out") != (not item["available"]):
            raise ConfirmationViewError("Rendered confirmation does not match the issued review.")
    issues = cast(list[str], rendered["issues"])
    if len(set(issues)) != len(issues):
        raise ConfirmationViewError("Rendered confirmation has duplicate issues.")
    edit_enabled: bool = any(action["type"] == "order.edit" and action["enabled"] for action in view["actions"])
    confirm_enabled: bool = any(action["type"] == "order.confirm" and action["enabled"] for action in view["actions"])
    if rendered["edit_disabled"] != ("disconnected" in issues or not edit_enabled):
        raise ConfirmationViewError("Rendered edit control does not match the reported state.")
    if rendered["confirm_disabled"] != (bool(issues) or not view["cart"]["can_checkout"] or not confirm_enabled):
        raise ConfirmationViewError("Rendered confirmation enables an unavailable control.")


def read_confirmation_view(connection: sqlite3.Connection, session_hash: str, reference: ConfirmationReference) -> CheckoutView:
    """Resolve only a confirmation envelope issued to this session."""
    row: tuple[str | None] | None = connection.execute("SELECT envelope_json FROM checkout_views WHERE id = ? AND session_hash = ?", (reference["widget_id"], session_hash)).fetchone()
    if row is None or row[0] is None or reference["revision"] != 1:
        raise ConfirmationViewError("Confirmation revision was not issued to this session. Review your cart again.")
    return cast(CheckoutView, json.loads(row[0]))


def acknowledge_confirmation(path: Path, token: str, reference: ConfirmationReference, locale: Literal["en", "ar"], rendered: dict[str, object]) -> CheckoutView:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        view: CheckoutView = read_confirmation_view(connection, session_hash, reference)
        validate_confirmation_rendered(view, rendered, locale)
        connection.execute("INSERT INTO confirmation_acknowledgements (widget_id, locale, revision, rendered_json) VALUES (?, ?, ?, ?) ON CONFLICT(widget_id, locale) DO UPDATE SET revision = excluded.revision, rendered_json = excluded.rendered_json WHERE excluded.revision >= confirmation_acknowledgements.revision", (reference["widget_id"], locale, reference["revision"], json.dumps(rendered, ensure_ascii=False)))
        return view


class ConfirmationContext(TypedDict):
    widget: CheckoutView
    active: bool
    acknowledged: bool
    locale: Literal["en", "ar"]


def read_confirmation_context(connection: sqlite3.Connection, session_hash: str, reference: ConfirmationReference, locale: Literal["en", "ar"]) -> ConfirmationContext:
    view: CheckoutView = read_confirmation_view(connection, session_hash, reference)
    consumed: tuple[int] = connection.execute("SELECT consumed FROM checkout_views WHERE id = ? AND session_hash = ?", (reference["widget_id"], session_hash)).fetchone()
    acknowledged: bool = connection.execute("SELECT 1 FROM confirmation_acknowledgements WHERE widget_id = ? AND locale = ? AND revision = ?", (reference["widget_id"], locale, reference["revision"])).fetchone() is not None
    return {"widget": view, "active": consumed[0] == 0 and read_cart(connection, session_hash)["revision"] == view["cart_revision"], "acknowledged": acknowledged, "locale": locale}


def build_confirmation_widget(cart: Cart, locale: Literal["en", "ar"]) -> ContainerNode:
    """Build a validated, read-only review from authoritative saved selections."""
    arabic: bool = locale == "ar"
    children: list[dict[str, object]] = [{"type": "Title", "value": "راجع طلبك" if arabic else "Review your order"}]
    for item in cart["items"]:
        total_minor: int = item["quantity"] * item["price_minor"]
        children.append({"type": "Col", "key": item["id"], "children": [
            {"type": "Text", "value": item["name_ar"] if arabic else item["name_en"]},
            {"type": "Caption", "value": f"{item['quantity']} × AED {item['price_minor'] // 100}.{item['price_minor'] % 100:02d}"},
            {"type": "Text", "value": f"AED {total_minor // 100}.{total_minor % 100:02d}"},
            *([] if item["available"] else [{"type": "Badge", "label": "نفد" if arabic else "Sold out"}]),
        ]})
    total: int = cart["total_minor"]
    label: str = "إجمالي الأصناف المختارة" if arabic else "Selected items total"
    children.append({"type": "Text", "value": f"{label}: AED {total // 100}.{total % 100:02d}"})
    result = validate_source(json.dumps({"type": "Card", "children": children}, ensure_ascii=False))
    if result["status"] != "valid" or result["preview"] is None:
        raise ValueError("The backend-built confirmation widget failed validation.")
    return result["preview"]
