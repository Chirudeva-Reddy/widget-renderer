import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field

from app.cart import require_session
from app.validator import ContainerNode, Node, validate_source
from app.widget_actions import WidgetActionError


class GenericField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    index: int = Field(ge=0, le=999)
    name: str = Field(min_length=1, max_length=64)
    value: str = Field(max_length=256)
    disabled: bool
    unavailable: bool


class GenericRendered(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    locale: Literal["en", "ar"]
    fields: list[GenericField] = Field(max_length=100)


class GenericReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    widget_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    revision: int = Field(ge=1)
    rendered: GenericRendered


class GenericContext(TypedDict):
    widget_id: str
    revision: int
    payload: dict[str, object]
    rendered: dict[str, object]


def declared_fields(node: Node) -> list[dict[str, object]]:
    if node["kind"] in ("input", "select"):
        return [cast(dict[str, object], node)]
    if node["kind"] == "table":
        return [field for row in node["rows"] for cell in row["cells"] for child in cell["children"] for field in declared_fields(child)]
    if "children" in node:
        return [field for child in node["children"] for field in declared_fields(child)]
    return []


def validate_generic_rendered(preview: ContainerNode, rendered: GenericRendered) -> None:
    issued_locale: str | None = preview.get("appearance", {}).get("locale")
    if issued_locale is not None and rendered.locale != issued_locale:
        raise WidgetActionError("The generic widget acknowledgement does not match its issued display language.")
    fields: list[dict[str, object]] = declared_fields(preview)
    if len(fields) != len(rendered.fields):
        raise WidgetActionError("The generic widget field list does not match its issued tree.")
    for index, (declared, actual) in enumerate(zip(fields, rendered.fields, strict=True)):
        try:
            actual.value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise WidgetActionError("Generic widget drafts must contain valid Unicode.") from error
        unavailable: bool = declared["kind"] == "select" and actual.value != "" and not any(option["value"] == actual.value and not option["disabled"] for option in declared["options"])
        if actual.index != index or actual.name != declared["name"] or declared["disabled"] and not actual.disabled or actual.unavailable != unavailable:
            raise WidgetActionError("The generic widget field identity or state does not match its issued tree.")


def acknowledge_generic(path: Path, token: str, reference: GenericReference) -> dict[str, object]:
    """Store bounded local drafts as render context; acknowledgements never authorize cart mutations."""
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        owner: str = require_session(connection, token)
        row: tuple[int, str] | None = connection.execute("SELECT revision, payload_json FROM generic_widgets WHERE id = ? AND session_hash = ?", (reference.widget_id, owner)).fetchone()
        if row is None or row[0] != reference.revision or row[1] is None:
            raise WidgetActionError("Generic widget is unknown or has changed. Refresh the widget before sending this draft.")
        preview: ContainerNode | None = validate_source(row[1])["preview"]
        if preview is None:
            raise WidgetActionError("The issued generic widget cannot be acknowledged.")
        validate_generic_rendered(preview, reference.rendered)
        rendered: dict[str, object] = reference.rendered.model_dump()
        connection.execute("UPDATE generic_widgets SET rendered_json = ? WHERE id = ? AND session_hash = ?", (json.dumps(rendered, ensure_ascii=False, sort_keys=True), reference.widget_id, owner))
        return reference.model_dump()


def read_generic_views(path: Path, token: str, references: list[GenericReference]) -> list[GenericContext]:
    with closing(sqlite3.connect(path)) as connection:
        owner: str = require_session(connection, token)
        result: list[GenericContext] = []
        seen: set[str] = set()
        for reference in references:
            if reference.widget_id in seen:
                raise WidgetActionError("The displayed generic widget list contains a duplicate identity.")
            seen.add(reference.widget_id)
            row: tuple[int, str, str | None] | None = connection.execute("SELECT revision, payload_json, rendered_json FROM generic_widgets WHERE id = ? AND session_hash = ?", (reference.widget_id, owner)).fetchone()
            rendered: dict[str, object] = reference.rendered.model_dump()
            if row is None or row[0] != reference.revision or row[2] is None or json.loads(row[2]) != rendered:
                raise WidgetActionError("The displayed generic draft was not acknowledged at this revision. Retry sending the message.")
            result.append({"widget_id": reference.widget_id, "revision": row[0], "payload": json.loads(row[1]), "rendered": rendered})
        return result


def bind_generic_turn(path: Path, token: str, message_id: str, references: list[GenericReference]) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        owner: str = require_session(connection, token)
        request: str = json.dumps([reference.model_dump() for reference in references], ensure_ascii=False, sort_keys=True)
        row: tuple[str | None] | None = connection.execute("SELECT generic_views_json FROM chat_turns WHERE session_hash = ? AND message_id = ?", (owner, message_id)).fetchone()
        if row is None:
            raise WidgetActionError("The chat turn does not exist for this session.")
        if row[0] is not None and row[0] != request:
            raise WidgetActionError("Message ID was already used with different generic drafts.")
        connection.execute("UPDATE chat_turns SET generic_views_json = ? WHERE session_hash = ? AND message_id = ?", (request, owner, message_id))


class GenericState(TypedDict):
    widget: dict[str, object]
    preview: ContainerNode
    payload: dict[str, object]


def read_generic_state(path: Path, token: str, widget_ids: list[str]) -> list[GenericState]:
    with closing(sqlite3.connect(path)) as connection:
        owner: str = require_session(connection, token)
        result: list[GenericState] = []
        for widget_id in widget_ids:
            row = connection.execute("SELECT revision, menu_revision, cart_revision, bindings_json, payload_json FROM generic_widgets WHERE id = ? AND session_hash = ?", (widget_id, owner)).fetchone()
            if row is None or row[4] is None:
                raise WidgetActionError("The requested generic widget does not belong to this session.")
            validated = validate_source(row[4])
            if validated["status"] != "valid" or validated["preview"] is None:
                raise WidgetActionError("The issued generic widget failed validation during synchronization.")
            result.append({"widget": {"widget_id": widget_id, "revision": row[0], "menu_revision": row[1], "cart_revision": row[2], "bindings": json.loads(row[3])}, "preview": validated["preview"], "payload": json.loads(row[4])})
        return result


def validate_draft_identities(node: Node) -> None:
    """Require stable, unique identities for drafts in live model-authored widgets."""
    seen: set[str] = set()

    def visit(current: Node, scope: str | None) -> None:
        if current["kind"] == "form":
            if scope is not None:
                raise WidgetActionError("Model-authored forms cannot be nested.")
            scope = current.get("key")
            if scope is None and declared_fields(current):
                raise WidgetActionError("Model-authored forms with draft fields require a stable key.")
        if current["kind"] in ("input", "select"):
            identity: str = f"form:{scope}:{current['name']}" if scope is not None else f"field:{current.get('key', current['name'])}"
            if identity in seen:
                raise WidgetActionError("Model-authored draft fields require unique stable identities.")
            seen.add(identity)
        if current["kind"] == "table":
            for row in current["rows"]:
                for cell in row["cells"]:
                    for child in cell["children"]:
                        visit(child, scope)
        elif "children" in current:
            for child in current["children"]:
                visit(child, scope)

    visit(node, None)
    if len(seen) > 100:
        raise WidgetActionError("Model-authored widgets support at most 100 draft fields.")
