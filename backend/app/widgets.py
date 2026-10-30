import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, TypedDict, cast

from app.cart import Cart, require_session
from app.menu import MenuResponse
from app.validator import ContainerNode


class WidgetError(ValueError):
    pass


class QuantityBinding(TypedDict):
    item_id: str
    position: int
    minimum: int
    maximum: int


class MenuActions(TypedDict):
    quantities: list[QuantityBinding]
    checkout: bool


class WidgetEnvelope(TypedDict):
    kind: Literal["widget"]
    actions: MenuActions
    widget_id: str
    revision: int
    locale: Literal["en", "ar"]
    payload: ContainerNode
    menu_view_id: str
    cart_revision: str
    menu: MenuResponse
    cart: Cart


def initialize_widgets(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS widgets (id TEXT PRIMARY KEY, session_hash TEXT NOT NULL, locale TEXT NOT NULL, UNIQUE(session_hash, locale))")
        connection.execute("CREATE TABLE IF NOT EXISTS widget_revisions (widget_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, envelope_json TEXT NOT NULL, PRIMARY KEY(widget_id, revision))")
        connection.execute("CREATE TABLE IF NOT EXISTS session_snapshots (session_hash TEXT PRIMARY KEY, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS widget_acknowledgements (widget_id TEXT PRIMARY KEY, revision INTEGER NOT NULL)")
        columns: set[str] = {row[1] for row in connection.execute("PRAGMA table_info(widget_acknowledgements)")}
        if "rendered_json" not in columns:
            connection.execute("ALTER TABLE widget_acknowledgements ADD COLUMN rendered_json TEXT")


def validate_rendered_view(envelope: WidgetEnvelope, rendered: dict[str, object]) -> None:
    if rendered.get("locale") != envelope["locale"] or not isinstance(rendered.get("rows"), list):
        raise WidgetError("Rendered view does not match the issued widget.")
    rows: list[dict[str, object]] = cast(list[dict[str, object]], rendered["rows"])
    items = envelope["menu"]["items"]
    if len(rows) != len(items):
        raise WidgetError("Rendered view does not match the issued rows.")
    for row, item in zip(rows, items, strict=True):
        if row["item_id"] != item["id"] or row["position"] != item["position"] or row["sold_out"] != (not item["available"]) or row["placeholder"]:
            raise WidgetError("Rendered view does not match the issued rows.")
        quantity: int = next((entry["quantity"] for entry in envelope["cart"]["items"] if entry["id"] == item["id"]), 0)
        maximum: int = 99 if item["available"] else quantity
        value: str = cast(str, row["quantity"])
        valid: bool = re.fullmatch(r"[0-9]{1,2}", value) is not None and int(value) <= maximum
        issues: list[str] = cast(list[str], row["issues"])
        controls: dict[str, bool] = cast(dict[str, bool], row["controls"])
        disabled: bool = cast(bool, row["disabled"])
        draft: bool = cast(bool, row["draft"])
        stale: bool = "stale_cart" in issues
        edit_revision: str | None = cast(str | None, row["edit_revision"])
        changed_revision: str | None = cast(str | None, row["changed_revision"])
        expected = {"input": disabled, "decrease": disabled or stale or draft or quantity == 0, "increase": disabled or stale or draft or not item["available"] or quantity >= 99, "apply": disabled or stale or not valid or not draft, "remove": disabled or stale or quantity == 0}
        if len(issues) != len(set(issues)) or ("invalid_quantity" in issues) == valid or ("sold_out" in issues) != (not item["available"]) or draft != (edit_revision is not None) or (changed_revision is not None and (edit_revision is None or changed_revision == edit_revision)) or stale != (edit_revision is not None and (edit_revision != envelope["cart_revision"] or changed_revision is not None)) or (not draft and value != str(quantity)) or controls != expected:
            raise WidgetError("Rendered controls or issues do not match the issued widget.")
    if rows and any(row["disabled"] != rows[0]["disabled"] for row in rows):
        raise WidgetError("Rendered rows disagree on whether the menu is disabled.")
    if rendered["checkout_disabled"] != (bool(rows and rows[0]["disabled"]) or not envelope["cart"]["items"] or any(row["draft"] for row in rows)):
        raise WidgetError("Rendered checkout control does not match the menu.")


def issue_widget(connection: sqlite3.Connection, session_hash: str, locale: Literal["en", "ar"], menu: MenuResponse, cart: Cart, payload: ContainerNode, view_id: str) -> WidgetEnvelope:
    """Issue or reuse an immutable widget revision within the caller transaction."""
    row: tuple[str] | None = connection.execute("SELECT id FROM widgets WHERE session_hash = ? AND locale = ?", (session_hash, locale)).fetchone()
    widget_id: str = row[0] if row is not None else secrets.token_urlsafe(24)
    if row is None:
        connection.execute("INSERT INTO widgets (id, session_hash, locale) VALUES (?, ?, ?)", (widget_id, session_hash, locale))
    cart_revision: str = cart["revision"]
    actions: MenuActions = {"quantities": [{"item_id": item["id"], "position": item["position"], "minimum": 0, "maximum": 99 if item["available"] else next((entry["quantity"] for entry in cart["items"] if entry["id"] == item["id"]), 0)} for item in menu["items"]], "checkout": bool(cart["items"])}
    fingerprint: str = hashlib.sha256(json.dumps({"actions": actions, "payload": payload, "menu_view_id": view_id, "cart_revision": cart_revision, "menu": menu, "cart": cart}, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    latest: tuple[int, str, str] | None = connection.execute("SELECT revision, fingerprint, envelope_json FROM widget_revisions WHERE widget_id = ? ORDER BY revision DESC LIMIT 1", (widget_id,)).fetchone()
    if latest is not None and latest[1] == fingerprint:
        return cast(WidgetEnvelope, json.loads(latest[2]))
    revision: int = 1 if latest is None else latest[0] + 1
    envelope: WidgetEnvelope = {"kind": "widget", "actions": actions, "widget_id": widget_id, "revision": revision, "locale": locale, "payload": payload, "menu_view_id": view_id, "cart_revision": cart_revision, "menu": menu, "cart": cart}
    connection.execute("INSERT INTO widget_revisions (widget_id, revision, fingerprint, envelope_json) VALUES (?, ?, ?, ?)", (widget_id, revision, fingerprint, json.dumps(envelope, ensure_ascii=False)))
    return envelope

def acknowledge_widget(path: Path, token: str, widget_id: str, revision: int, rendered: dict[str, object]) -> WidgetEnvelope:
    """Accept an issued revision and retain the highest acknowledged revision."""
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        row: tuple[str] | None = connection.execute("SELECT r.envelope_json FROM widgets w JOIN widget_revisions r ON r.widget_id = w.id WHERE w.id = ? AND w.session_hash = ? AND r.revision = ?", (widget_id, session_hash, revision)).fetchone()
        if row is None:
            raise WidgetError("Widget revision was not issued to this session. Refresh the widget and try again.")
        envelope: WidgetEnvelope = cast(WidgetEnvelope, json.loads(row[0]))
        validate_rendered_view(envelope, rendered)
        connection.execute("INSERT INTO widget_acknowledgements (widget_id, revision, rendered_json) VALUES (?, ?, ?) ON CONFLICT(widget_id) DO UPDATE SET revision = excluded.revision, rendered_json = excluded.rendered_json WHERE excluded.revision >= widget_acknowledgements.revision", (widget_id, revision, json.dumps(rendered, ensure_ascii=False)))
        return envelope
