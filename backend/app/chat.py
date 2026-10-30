import asyncio
import json
import logging
import os
import secrets
import sqlite3
from contextlib import closing
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypedDict, cast

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.cart import CompletedAction, read_completed_actions, require_session
from app.confirmation_widget import ConfirmationContext, ConfirmationReference, ConfirmationViewError, read_confirmation_context, read_confirmation_view, validate_confirmation_rendered
from app.events import Snapshot, read_session_snapshot
from app.menu import MenuResponse
from app.menu_views import MenuViewError, get_menu_view, read_menu_view
from app.menu_widget import build_menu_tree, build_menu_widget
from app.validator import ContainerNode, Node, validate_source
from app.widgets import WidgetEnvelope, WidgetError, validate_rendered_view
from app.generic_views import GenericReference, bind_generic_turn, read_generic_views, validate_draft_identities
from app.widget_actions import GenericWidget, WidgetActionError, bind_generic_actions


logger: logging.Logger = logging.getLogger(__name__)


class EmptyIntentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QuantityIntentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=0, le=99)


class LocaleIntentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    lang: Literal["en", "ar"]


class MenuIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["menu.show"]
    payload: EmptyIntentPayload


class QuantityIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["cart.set_quantity"]
    payload: QuantityIntentPayload


class LocaleIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["locale.set"]
    payload: LocaleIntentPayload


class CheckoutIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["checkout.start"]
    payload: EmptyIntentPayload


class WidgetProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target_role: Literal["summary", "diagnostic"]
    target_widget_id: str | None = Field(max_length=128)
    payload: dict[str, object]


class ModelReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str | None = Field(max_length=1200)
    intents: list[MenuIntent | QuantityIntent | LocaleIntent | CheckoutIntent] = Field(max_length=4)
    widgets: list[WidgetProposal] = Field(max_length=2)


def model_schema() -> dict[str, object]:
    def shape(properties: dict[str, object]) -> dict[str, object]:
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    def tag(value: str) -> dict[str, object]:
        return {"type": "string", "enum": [value]}

    leaf: list[dict[str, object]] = [shape({"type": tag(kind), "value": {"type": "string"}}) for kind in ("Text", "Title", "Caption")]
    leaf += [shape({"type": tag(kind), "key": {"type": "string"}, "value": {"type": "string"}}) for kind in ("Text", "Title", "Caption")]
    leaf += [shape({"type": tag("Badge"), "label": {"type": "string"}})]
    leaf += [shape({"type": tag("Button"), "label": {"type": "string"}, "key": {"type": "string"}}), shape({"type": tag("Button"), "label": {"type": "string"}})]
    leaf += [shape({"type": tag("Input"), "name": {"type": "string"}, "inputType": tag("number"), "defaultValue": {"type": "string"}}), shape({"type": tag("Select"), "key": {"type": "string"}, "name": {"type": "string"}, "defaultValue": {"type": "string"}, "options": {"type": "array", "items": shape({"value": {"type": "string"}, "label": {"type": "string"}})}})]
    leaf += [shape({"type": tag(kind)}) for kind in ("Spacer", "Divider")]
    containers: list[dict[str, object]] = [shape({"type": tag(kind), "children": {"type": "array", "items": {"$ref": "#/$defs/node"}}}) for kind in ("Card", "ListView", "ListViewItem", "Row", "Col", "Box", "Form")]
    containers += [shape({"type": tag("Form"), "key": {"type": "string"}, "children": {"type": "array", "items": {"$ref": "#/$defs/node"}}})]
    intents: list[dict[str, object]] = [shape({"type": tag("menu.show"), "payload": shape({})}), shape({"type": tag("cart.set_quantity"), "payload": shape({"id": {"type": "string"}, "quantity": {"type": "integer"}})}), shape({"type": tag("locale.set"), "payload": shape({"lang": {"type": "string", "enum": ["en", "ar"]}})}), shape({"type": tag("checkout.start"), "payload": shape({})})]
    widget: dict[str, object] = shape({"target_role": {"type": "string", "enum": ["summary", "diagnostic"]}, "target_widget_id": {"anyOf": [{"type": "string"}, {"type": "null"}]}, "payload": {"anyOf": containers[:1]}})
    schema: dict[str, object] = shape({"text": {"anyOf": [{"type": "string"}, {"type": "null"}]}, "intents": {"type": "array", "items": {"anyOf": intents}}, "widgets": {"type": "array", "items": widget}})
    schema["$defs"] = {"node": {"anyOf": leaf + containers[3:6] + containers[7:]}}
    return schema


class QuantityProposal(TypedDict):
    item_id: str
    quantity: int


class QuantityReference(QuantityProposal):
    source: Literal["completed_action", "assistant_proposal"]


class ChatReply(TypedDict):
    message_id: str
    text: str
    suggestion: QuantityProposal | None
    suggestions: list[QuantityProposal]
    menu_revision: int
    cart_revision: str
    widget: ContainerNode | None
    locale: Literal["en", "ar"]
    messages: list["ApplicationMessage"]
    widget_previews: list[ContainerNode]
    widget_authors: list[Literal["backend", "model", "unknown"]]
    widget_controls: list[GenericWidget | None]
    proposed_actions: list["ProposedAction"]
    widget_author: Literal["backend", "model", "unknown"] | None
    warnings: list[str]


class ProposedAction(TypedDict):
    type: Literal["locale.set", "checkout.start"]
    lang: Literal["en", "ar"] | None


class ApplicationMessage(TypedDict):
    kind: Literal["text", "widget", "widget_update"]
    message_id: str
    widget_id: str | None
    revision: int | None
    payload: dict[str, object]


class ChatError(ValueError):
    pass


class ProviderError(RuntimeError):
    pass


def initialize_chat(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS chat_turns (session_hash TEXT NOT NULL, message_id TEXT NOT NULL, text TEXT NOT NULL, menu_revision INTEGER NOT NULL, status TEXT NOT NULL, result_json TEXT, locale TEXT NOT NULL DEFAULT 'en', PRIMARY KEY (session_hash, message_id))")
        columns: set[str] = {row[1] for row in connection.execute("PRAGMA table_info(chat_turns)").fetchall()}
        if "action_sequence" not in columns:
            connection.execute("ALTER TABLE chat_turns ADD COLUMN action_sequence INTEGER")
            connection.execute("UPDATE chat_turns SET action_sequence = -1 WHERE status = 'complete'")
        if "confirmation_view" not in columns:
            connection.execute("ALTER TABLE chat_turns ADD COLUMN confirmation_view TEXT")
        if "widget_view" not in columns:
            connection.execute("ALTER TABLE chat_turns ADD COLUMN widget_view TEXT")
        if "rendered_view_id" not in columns:
            connection.execute("ALTER TABLE chat_turns ADD COLUMN rendered_view_id TEXT")
        if "locale" not in columns:
            connection.execute("ALTER TABLE chat_turns ADD COLUMN locale TEXT NOT NULL DEFAULT 'en'")

    with closing(sqlite3.connect(path)) as connection, connection:
        columns: set[str] = {row[1] for row in connection.execute("PRAGMA table_info(chat_turns)")}
        if "generic_views_json" not in columns:
            connection.execute("ALTER TABLE chat_turns ADD COLUMN generic_views_json TEXT")


def read_widget_view(connection: sqlite3.Connection, session_hash: str, reference: dict[str, object], locale: Literal["en", "ar"], menu_revision: int, rendered_view_id: str | None) -> WidgetEnvelope:
    row: tuple[str] | None = connection.execute("SELECT r.envelope_json FROM widgets w JOIN widget_revisions r ON r.widget_id = w.id WHERE w.id = ? AND w.session_hash = ? AND w.locale = ? AND r.revision = ?", (reference["widget_id"], session_hash, locale, reference["revision"])).fetchone()
    if row is None:
        raise ChatError("The displayed widget could not be verified. Refresh the menu and try again.")
    envelope: WidgetEnvelope = cast(WidgetEnvelope, json.loads(row[0]))
    if envelope["menu_view_id"] != rendered_view_id or envelope["menu"]["revision"] != menu_revision:
        raise ChatError("The displayed widget does not match the menu view. Refresh the menu and try again.")
    rendered = reference.get("rendered")
    if rendered is not None:
        try:
            validate_rendered_view(envelope, cast(dict[str, object], rendered))
        except WidgetError as error:
            raise ChatError(str(error)) from error
    return envelope


def get_widget_view(path: Path, token: str, reference: dict[str, str | int], locale: Literal["en", "ar"], menu_revision: int, rendered_view_id: str | None) -> WidgetEnvelope:
    with sqlite3.connect(path) as connection:
        return read_widget_view(connection, require_session(connection, token), reference, locale, menu_revision, rendered_view_id)


def begin_turn(path: Path, token: str, message_id: str, text: str, menu_revision: int, locale: Literal["en", "ar"], rendered_view_id: str | None, widget_view: dict[str, str | int] | None, confirmation_view: ConfirmationReference | None) -> ChatReply | None:
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        read_menu_view(connection, session_hash, rendered_view_id, menu_revision, locale)
        if widget_view is not None:
            read_widget_view(connection, session_hash, widget_view, locale, menu_revision, rendered_view_id)
        if confirmation_view is not None:
            confirmation = read_confirmation_view(connection, session_hash, confirmation_view)
            rendered_confirmation = confirmation_view.get("rendered")
            if rendered_confirmation is not None:
                validate_confirmation_rendered(confirmation, cast(dict[str, object], rendered_confirmation), locale)
        confirmation_json: str | None = None if confirmation_view is None else json.dumps(confirmation_view, sort_keys=True)
        widget_json: str | None = None if widget_view is None else json.dumps(widget_view, sort_keys=True)
        existing = connection.execute("SELECT text, menu_revision, status, result_json, locale, rendered_view_id, widget_view, confirmation_view FROM chat_turns WHERE session_hash = ? AND message_id = ?", (session_hash, message_id)).fetchone()
        if existing is not None:
            if existing[0] != text or existing[1] != menu_revision or existing[4] != locale or existing[5] != rendered_view_id or existing[6] != widget_json or existing[7] != confirmation_json:
                raise ChatError("Message ID was already used for a different request.")
            if existing[2] == "complete":
                stored: dict[str, object] = json.loads(existing[3])
                changed: bool = False
                if "message_id" not in stored:
                    stored["message_id"] = secrets.token_urlsafe(24)
                    changed = True
                if "messages" not in stored:
                    stored["messages"] = [{"kind": "text", "message_id": stored["message_id"], "widget_id": None, "revision": None, "payload": {"text": stored["text"]}}]
                    changed = True
                if "proposed_actions" not in stored:
                    stored["proposed_actions"] = []
                    changed = True
                if "widget_author" not in stored:
                    stored["widget_author"] = "unknown" if stored.get("widget") is not None else None
                    changed = True
                if "warnings" not in stored:
                    stored["warnings"] = []
                    changed = True
                if "suggestions" not in stored:
                    stored["suggestions"] = [] if stored.get("suggestion") is None else [stored["suggestion"]]
                    changed = True
                if "widget_previews" not in stored:
                    stored_messages = cast(list[dict[str, object]], stored["messages"])
                    stored["widget_previews"] = [stored["widget"]] if stored.get("widget") is not None and any(message.get("kind") in ("widget", "widget_update") for message in stored_messages) else []
                    changed = True
                if "widget_authors" not in stored:
                    stored["widget_authors"] = [stored["widget_author"] or "unknown"] * len(cast(list[object], stored["widget_previews"]))
                    changed = True
                if "widget_controls" not in stored:
                    stored["widget_controls"] = [None] * len(cast(list[object], stored["widget_previews"]))
                    changed = True
                if changed:
                    connection.execute("UPDATE chat_turns SET result_json = ? WHERE session_hash = ? AND message_id = ?", (json.dumps(stored, ensure_ascii=False), session_hash, message_id))
                return cast(ChatReply, stored)
            raise ChatError("This message is already being processed or failed. Send a new message to retry.")
        connection.execute("INSERT INTO chat_turns (session_hash, message_id, text, menu_revision, status, locale, rendered_view_id, widget_view, confirmation_view) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)", (session_hash, message_id, text, menu_revision, locale, rendered_view_id, widget_json, confirmation_json))
        return None


def finish_turn(path: Path, token: str, message_id: str, reply: ChatReply, action_sequence: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        for widget in reply.get("widget_controls", []):
            if widget is not None:
                message = next(message for message in reply["messages"] if message["widget_id"] == widget["widget_id"])
                previous = connection.execute("SELECT revision, session_hash FROM generic_widgets WHERE id = ?", (widget["widget_id"],)).fetchone()
                if previous is not None and (previous[1] != session_hash or previous[0] != widget["revision"] - 1):
                    raise ChatError("The widget changed during this turn. Retry with a new message.")
                connection.execute("INSERT INTO generic_widgets (id, session_hash, revision, menu_revision, cart_revision, bindings_json, payload_json, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, menu_revision=excluded.menu_revision, cart_revision=excluded.cart_revision, bindings_json=excluded.bindings_json, payload_json=excluded.payload_json, rendered_json=NULL", (widget["widget_id"], session_hash, widget["revision"], widget["menu_revision"], widget["cart_revision"], json.dumps(widget["bindings"], ensure_ascii=False), json.dumps(message["payload"], ensure_ascii=False), "summary"))
        connection.execute("UPDATE chat_turns SET status = 'complete', result_json = ?, action_sequence = ? WHERE session_hash = ? AND message_id = ?", (json.dumps(reply, ensure_ascii=False), action_sequence, session_hash, message_id))


def fail_turn(path: Path, token: str, message_id: str) -> None:
    with sqlite3.connect(path) as connection:
        session_hash: str = require_session(connection, token)
        connection.execute("UPDATE chat_turns SET status = 'failed' WHERE session_hash = ? AND message_id = ?", (session_hash, message_id))


def provider_settings() -> tuple[str, str]:
    settings = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    key: str = os.environ.get("OPEN_ROUTE_API_KEY") or settings.get("OPEN_ROUTE_API_KEY") or ""
    model: str = os.environ.get("OPENROUTER_MODEL") or settings.get("OPENROUTER_MODEL") or "openai/gpt-4.1-mini"
    if not key:
        raise ProviderError("OpenRouter is not configured on the backend.")
    return key, model


class ProviderMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class HistoricalReply(TypedDict):
    reply: ChatReply
    completed_actions_through_sequence: int | None


def read_session_history(connection: sqlite3.Connection, session_hash: str) -> list[ProviderMessage]:
    rows: list[tuple[str, str, int | None]] = connection.execute("SELECT text, result_json, action_sequence FROM chat_turns WHERE session_hash = ? AND status = 'complete' ORDER BY rowid DESC LIMIT 20", (session_hash,)).fetchall()
    messages: list[ProviderMessage] = []
    for text, result_json, action_sequence in reversed(rows):
        historical_reply: HistoricalReply = {"reply": cast(ChatReply, json.loads(result_json)), "completed_actions_through_sequence": action_sequence}
        messages.extend([{"role": "user", "content": text}, {"role": "assistant", "content": json.dumps(historical_reply, ensure_ascii=False)}])
    return messages


def read_history(path: Path, token: str) -> list[ProviderMessage]:
    """Return the latest 20 completed turns in conversation order for this session."""
    with sqlite3.connect(path) as connection:
        session_hash: str = require_session(connection, token)
        return read_session_history(connection, session_hash)


def provider_request(text: str, context: str, locale: Literal["en", "ar"], history: list[ProviderMessage]) -> tuple[str, dict[str, object]]:
    key, model = provider_settings()
    prompt: str = (f"You are a restaurant assistant. Respond in {'English' if locale == 'en' else 'Arabic'} only, regardless of the language in the menu data. The menu and cart are authoritative. "
        "Return JSON with exactly text, intents and widgets. Use a menu.show intent with an empty payload whenever the customer asks for the menu. Use a cart.set_quantity intent with payload {id, quantity} only when the customer explicitly requests a quantity change. "
        "model_widgets contains only browser-acknowledged displayed generic widgets. Its rendered.fields values are the actual local drafts, not saved quantities. Use those drafts when asked what the customer sees, and do not claim they executed. Only completed_actions supplied by the backend prove a past control action completed. You may acknowledge those actions, but new suggestions still require the customer to apply them; never claim a new proposal has executed. "
        "quantity_reference is the backend-resolved item for implicit requests such as make that three. For such an implicit follow-up, use its item_id when present, not a different dish from history or the current cart. "
        "An explicit dish name in the current message takes precedence; ordinal references use displayed_menu as specified below. If no reference exists and the target is unclear, ask for clarification. "
        "A quantity_reference with source assistant_proposal identifies a conversational proposal, not an executed action. Only completed_actions prove execution. "
        "When the user explicitly requests a quantity and its target is known, return the suggestion directly; the Apply control already requires approval, so do not ask a redundant confirmation question. "
        "An order.confirm action contains an immutable receipt: use its stored items, prices, total and order ID even when the current cart is empty. Never recalculate a confirmed receipt using current menu prices, or claim a confirmed order was edited. "
        "Never suggest increasing a sold-out item. Resolve ordinal references ONLY using displayed_menu positions, never current_menu or a historical assistant message. If displayed_menu is null, ask for clarification on ordinal references. The current_menu and cart determine current availability, not the meaning of a displayed position. "
        "displayed_confirmation is the issued review card, locale, acknowledgement status and current validity. It is a review, never proof of a confirmed order. Its saved items and total describe that snapshot; active false means it is stale or consumed. Only completed_actions prove an order was confirmed. "
        "displayed_widget is the server-issued snapshot backing the displayed menu; its cart contains saved quantities. rendered_view, when present, reports the browser's displayed input values, disabled state and issue codes; these are context, not authorization or proof that a draft was saved. When asked what quantity is displayed in an input, use the matching rendered_view row's quantity, not the saved cart quantity; explain when the displayed value is an unapplied draft. current_menu and cart describe current saved state. "
        "Count every displayed dish row, including sold-out dishes. Ask a clarification if ambiguous. Never invent prices or dishes. For a dish price in a widget, use a Text node with key price:<dish id>; the backend replaces its value with the authoritative price. "
        "Creating, refreshing, translating or redesigning a widget, including changing its input defaultValue or options, is a presentation request. For those requests, emit a widgets proposal and no cart, locale or checkout intents unless the customer separately requests a change to their saved order or session. Never claim a widget was updated without emitting that widget proposal. Preserve existing field names and keys when changing presentation. "
        "widgets is empty unless a compact visual summary helps. A summary proposal has target_role summary, target_widget_id null, and a widget tree payload rooted at Card. To update a model_widgets entry, set target_widget_id to its issued ID; never target menu or confirmation widgets. Do not combine a widget with a menu.show intent. "
        "The root is {\"type\":\"Card\",\"children\":[...]}. Allowed children: "
        "Title, Text and Caption as {\"type\":\"Text\",\"value\":\"...\"} with optional weight normal, medium, semibold or bold; Badge as {\"type\":\"Badge\",\"label\":\"...\"}; Divider and Spacer as {\"type\":\"Divider\"}; "
        "Row, Col and Box as {\"type\":\"Row\",\"gap\":2,\"children\":[...]} where gap is an optional integer 0 to 8 on Row and Col only; Table as {\"type\":\"Table\",\"children\":[{\"type\":\"Table.Row\",\"header\":true,\"children\":[{\"type\":\"Table.Cell\",\"align\":\"end\",\"children\":[...]}]}]}. "
        "Text values are strings, containers always have a children array, and sibling key values, if used, must be unique. Style only with these ChatKit token props, never CSS, hex colours or other values: on Text, Title and Caption, color is prose, primary, emphasis, secondary, tertiary, success, warning or danger, and textAlign is start, center or end; Text size is xs, sm, md, lg or xl, Title size is sm, md, lg, xl or 2xl, Caption size is sm, md or lg, and Text may set italic or lineThrough true; Badge color is secondary, success, danger, warning, info or discovery and variant is solid, soft or outline; Row, Col and Box may set background surface, surface-secondary, surface-tertiary, surface-elevated or surface-elevated-secondary, radius sm, md, lg or xl, and padding, align (start, center, end) and justify (start, center, end, between). Use colour for meaning: success for available or confirmed, danger for sold out or problems, warning for attention, secondary or tertiary for supporting details such as unit prices. A Button may use key action:cart.add:<dish id> or action:cart.remove:<dish id>; these controls require an explicit user click and are checked by the backend. Quantity Form uses key action:cart.set_quantity:<dish id>, children containing one Input with name quantity, inputType number, defaultValue string, and a Button. Select uses the same action key, name quantity, defaultValue string, and options with string value and label. Select changes submit directly; Form submits explicitly. No Image, links, scripts, HTML or markdown. "
        "Controls only propose cart changes until the customer activates them; a model widget cannot place an order. Write every label in the reply language, using the supplied localized dish names. Copy prices, quantities, totals and order IDs exactly from current_menu, cart or an order.confirm receipt, "
        "formatting price_minor as major units with its currency; omit any figure you were not given. Never present a card as a confirmed order unless it restates an order.confirm receipt. Keep it small: at most 30 components. Use only the component types and properties permitted by the response schema. "
        "Example: {\"type\":\"Card\",\"children\":[{\"type\":\"Row\",\"align\":\"center\",\"children\":[{\"type\":\"Title\",\"value\":\"Your cart\",\"size\":\"md\"},{\"type\":\"Badge\",\"label\":\"2 items\",\"color\":\"info\"}]},{\"type\":\"Divider\"},{\"type\":\"Row\",\"align\":\"center\",\"children\":[{\"type\":\"Col\",\"children\":[{\"type\":\"Text\",\"value\":\"Hummus\",\"weight\":\"semibold\"},{\"type\":\"Caption\",\"value\":\"2 \\u00d7 AED 18.00\",\"color\":\"secondary\"}]},{\"type\":\"Text\",\"value\":\"AED 36.00\",\"weight\":\"semibold\"}]},{\"type\":\"Row\",\"align\":\"center\",\"children\":[{\"type\":\"Col\",\"children\":[{\"type\":\"Text\",\"value\":\"Tabbouleh\",\"weight\":\"semibold\",\"lineThrough\":true,\"color\":\"tertiary\"},{\"type\":\"Caption\",\"value\":\"1 \\u00d7 AED 20.00\",\"color\":\"secondary\"}]},{\"type\":\"Badge\",\"label\":\"Sold out\",\"color\":\"danger\"}]},{\"type\":\"Box\",\"background\":\"surface-secondary\",\"radius\":\"md\",\"padding\":3,\"children\":[{\"type\":\"Row\",\"justify\":\"between\",\"children\":[{\"type\":\"Text\",\"value\":\"Selected items total\",\"color\":\"secondary\"},{\"type\":\"Text\",\"value\":\"AED 56.00\",\"weight\":\"bold\",\"size\":\"lg\"}]}]}]}.")
    return key, {"model": model, "messages": [{"role": "system", "content": prompt}, *history, {"role": "user", "content": f"Displayed and current restaurant data: {context}\nCustomer message: {text}"}], "response_format": {"type": "json_schema", "json_schema": {"name": "restaurant_reply", "strict": True, "schema": model_schema()}}, "provider": {"require_parameters": True}, "max_tokens": 2048}


async def ask_provider(text: str, context: str, locale: Literal["en", "ar"], history: list[ProviderMessage]) -> ModelReply:
    key, body = provider_request(text, context, locale, history)
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(2):
            try:
                response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body)
                response.raise_for_status()
                content: str = response.json()["choices"][0]["message"]["content"]
                return ModelReply.model_validate_json(content)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                logger.warning("OpenRouter request failed", extra={"attempt": attempt + 1, "error_type": type(error).__name__})
                if attempt == 1:
                    raise ProviderError("OpenRouter could not be reached. Please try again.") from error
                await asyncio.sleep(0.5)
            except httpx.HTTPStatusError as error:
                status: int = error.response.status_code
                logger.warning("OpenRouter rejected request", extra={"status_code": status, "attempt": attempt + 1})
                if status in (429, 500, 502, 503, 504) and attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                raise ProviderError("OpenRouter could not process the request. Check the backend configuration.") from error
            except (KeyError, IndexError, TypeError, ValueError, ValidationError) as error:
                raise ProviderError("OpenRouter returned an invalid response. Please try again.") from error
    raise ProviderError("OpenRouter request did not complete.")


Emit = Callable[[str, object], None]
async def stream_provider(text: str, context: str, locale: Literal["en", "ar"], history: list[ProviderMessage]) -> ModelReply:
    key, body = provider_request(text, context, locale, history)
    content: str = ""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client, client.stream("POST", "https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={**body, "stream": True}) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                chunk = json.loads(line[6:])
                if "error" in chunk:
                    raise ProviderError("OpenRouter stopped while generating the reply. Please try again.")
                for choice in chunk.get("choices", []):
                    content += choice.get("delta", {}).get("content") or ""
        return ModelReply.model_validate_json(content)
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as error:
        logger.warning("OpenRouter stream failed", extra={"error_type": type(error).__name__})
        raise ProviderError("The connection to OpenRouter was interrupted. Please try again.") from error
    except httpx.HTTPStatusError as error:
        logger.warning("OpenRouter rejected request", extra={"status_code": error.response.status_code})
        raise ProviderError("OpenRouter could not process the request. Check the backend configuration.") from error
    except (KeyError, IndexError, TypeError, ValueError, ValidationError) as error:
        raise ProviderError("OpenRouter returned an invalid response. Please try again.") from error


def interactive(node: Node) -> bool:
    if node["kind"] in ("button", "input", "select", "form"):
        return True
    if node["kind"] == "table":
        return any(interactive(child) for row in node["rows"] for cell in row["cells"] for child in cell["children"])
    return "children" in node and any(interactive(child) for child in node["children"])


def display_card(source: str) -> ContainerNode | None:
    preview: ContainerNode | None = validate_source(source)["preview"]
    return None if preview is None or preview["kind"] != "card" or interactive(preview) else preview


def unsupported_generic_control(node: Node) -> bool:
    if node["kind"] in ("input", "select", "form"):
        return True
    if node["kind"] == "table":
        return any(unsupported_generic_control(child) for row in node["rows"] for cell in row["cells"] for child in cell["children"])
    return "children" in node and any(unsupported_generic_control(child) for child in node["children"])


def bind_summary_card(source: str | None) -> ContainerNode | None:
    """Accept only a validated, display-only Card; anything else becomes a visible problem instead of a widget."""
    if source is None:
        return None
    preview: ContainerNode | None = display_card(source)
    if preview is None:
        logger.warning("Rejected assistant summary card")
        return {"kind": "card", "children": [{"kind": "problem", "message": "The assistant's summary could not be displayed."}]}
    return preview


def reconcile_price_bindings(tree: dict[str, object], menu: MenuResponse) -> tuple[dict[str, object], list[str]]:
    """Replace explicitly bound price nodes from the authoritative menu."""
    prices: dict[str, str] = {f"price:{item['id']}": f"{item['currency']} {item['price_minor'] // 100}.{item['price_minor'] % 100:02d}" for item in menu["items"]}
    seen: set[str] = set()
    warnings: list[str] = []

    def visit(value: object) -> object:
        if isinstance(value, list):
            return [visit(child) for child in value]
        if not isinstance(value, dict):
            return value
        node: dict[str, object] = {key: visit(child) for key, child in value.items()}
        key = node.get("key")
        if isinstance(key, str) and key.startswith("price:"):
            if key not in prices or key in seen or node.get("type") not in ("Text", "Title", "Caption"):
                raise ProviderError("The assistant proposed an unknown or ambiguous price binding.")
            seen.add(key)
            if node.get("value") != prices[key]:
                warnings.append("price_reconciled")
            node["value"] = prices[key]
        return node

    return cast(dict[str, object], visit(tree)), warnings


class ActionContext(TypedDict):
    displayed_confirmation: ConfirmationContext | None
    snapshot: Snapshot
    completed_actions: list[CompletedAction]
    actions_not_seen_in_latest_reply: list[CompletedAction] | None
    latest_assistant_proposal: QuantityProposal | None
    quantity_reference: QuantityReference | None
    history: list[ProviderMessage]


def resolve_quantity_reference(unseen: list[CompletedAction] | None, proposal: QuantityProposal | None) -> QuantityReference | None:
    if unseen is None:
        return None
    relevant: list[CompletedAction] = [action for action in unseen if action["type"] not in ("checkout.start", "order.edit", "locale.set")]
    if relevant:
        latest: CompletedAction = relevant[-1]
        if latest["type"] in ("cart.set_quantity", "cart.add", "cart.remove"):
            return {"item_id": latest["item_id"], "quantity": latest["quantity"], "source": "completed_action"}
        return None
    if proposal is None:
        return None
    return {"item_id": proposal["item_id"], "quantity": proposal["quantity"], "source": "assistant_proposal"}


def read_action_context(path: Path, token: str, confirmation_view: ConfirmationReference | None, locale: Literal["en", "ar"]) -> ActionContext:
    """Read action history and restaurant state at the same transaction boundary."""
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        actions: list[CompletedAction] = read_completed_actions(connection, session_hash)
        history: list[ProviderMessage] = read_session_history(connection, session_hash)
        latest: HistoricalReply | None = cast(HistoricalReply, json.loads(history[-1]["content"])) if history else None
        known_sequence: int | None = 0 if latest is None else latest["completed_actions_through_sequence"]
        unseen: list[CompletedAction] | None = None if known_sequence is None else [action for action in actions if action["sequence"] > known_sequence]
        if known_sequence == -1 and not unseen:
            unseen = None
        proposal: QuantityProposal | None = None if latest is None else latest["reply"]["suggestion"]
        return {"displayed_confirmation": None if confirmation_view is None else read_confirmation_context(connection, session_hash, confirmation_view, locale), "snapshot": read_session_snapshot(connection, session_hash), "completed_actions": actions, "actions_not_seen_in_latest_reply": unseen, "latest_assistant_proposal": proposal, "quantity_reference": resolve_quantity_reference(unseen, proposal), "history": history}


async def respond(path: Path, token: str, message_id: str, text: str, menu_revision: int, locale: Literal["en", "ar"], rendered_view_id: str | None, confirmation_view: ConfirmationReference | None, emit: Emit | None, widget_view: dict[str, str | int] | None, generic_views: list[GenericReference]) -> ChatReply:
    prior: ChatReply | None = await asyncio.to_thread(begin_turn, path, token, message_id, text, menu_revision, locale, rendered_view_id, widget_view, confirmation_view)
    try:
        await asyncio.to_thread(bind_generic_turn, path, token, message_id, generic_views)
    except WidgetActionError as error:
        raise ChatError(str(error)) from error
    if prior is not None:
        return prior
    if emit is not None:
        emit("start", {"message_id": message_id})
    try:
        action_context: ActionContext = await asyncio.to_thread(read_action_context, path, token, confirmation_view, locale)
        snapshot: Snapshot = action_context["snapshot"]
        displayed_menu: MenuResponse | None = await asyncio.to_thread(get_menu_view, path, token, rendered_view_id, menu_revision, locale)
        localized_menu = [{"id": item["id"], "position": item["position"], "name": item["name"][locale], "price_minor": item["price_minor"], "currency": item["currency"], "available": item["available"]} for item in snapshot["menu"]["items"]]
        localized_cart = [{"id": item["id"], "name": item["name_en"] if locale == "en" else item["name_ar"], "quantity": item["quantity"], "available": item["available"]} for item in snapshot["cart"]["items"]]
        displayed_items: list[dict[str, str | int | bool]] | None = None if displayed_menu is None else [{"id": item["id"], "position": item["position"], "name": item["name"][locale], "available": item["available"]} for item in displayed_menu["items"]]
        displayed_widget: WidgetEnvelope | None = None if widget_view is None else await asyncio.to_thread(get_widget_view, path, token, widget_view, locale, menu_revision, rendered_view_id)
        history: list[ProviderMessage] = action_context["history"]
        context: str = json.dumps({"displayed_confirmation": action_context["displayed_confirmation"], "rendered_confirmation": None if confirmation_view is None else confirmation_view.get("rendered"), "displayed_menu": displayed_items, "displayed_widget": displayed_widget, "rendered_view": None if widget_view is None else widget_view.get("rendered"), "current_menu": localized_menu, "cart": localized_cart, "completed_actions": action_context["completed_actions"], "quantity_reference": action_context["quantity_reference"]}, ensure_ascii=False)
        model_widgets = await asyncio.to_thread(read_generic_views, path, token, generic_views)
        context = json.dumps({"restaurant": json.loads(context), "model_widgets": model_widgets}, ensure_ascii=False)
        reply: ModelReply = await (ask_provider(text, context, locale, history) if emit is None else stream_provider(text, context, locale, history))
        quantities: list[QuantityIntent] = [intent for intent in reply.intents if isinstance(intent, QuantityIntent)]
        show_menu: bool = any(isinstance(intent, MenuIntent) for intent in reply.intents)
        suggestions: list[QuantityProposal] = []
        for intent in quantities:
            proposed = intent.payload
            item = next((item for item in snapshot["menu"]["items"] if item["id"] == proposed.id), None)
            if item is None:
                raise ProviderError("The assistant suggested an unknown menu item. Please try again.")
            if any(previous["item_id"] == item["id"] for previous in suggestions):
                raise ProviderError("The assistant proposed conflicting quantities for the same item.")
            current: int = next((entry["quantity"] for entry in snapshot["cart"]["items"] if entry["id"] == item["id"]), 0)
            if not item["available"] and proposed.quantity > current:
                raise ProviderError("The assistant suggested an unavailable item. Please try again.")
            suggestions.append({"item_id": item["id"], "quantity": proposed.quantity})
        suggestion: QuantityProposal | None = suggestions[0] if len(suggestions) == 1 else None
        proposed_actions: list[ProposedAction] = [{"type": "locale.set", "lang": intent.payload.lang} if isinstance(intent, LocaleIntent) else {"type": "checkout.start", "lang": None} for intent in reply.intents if isinstance(intent, (LocaleIntent, CheckoutIntent))]
        response_text: str = reply.text or ""
        response_id: str = secrets.token_urlsafe(24)
        messages: list[ApplicationMessage] = [{"kind": "text", "message_id": response_id, "widget_id": None, "revision": None, "payload": {"text": response_text}}]
        previews: list[ContainerNode] = []
        authors: list[Literal["backend", "model", "unknown"]] = []
        controls: list[GenericWidget | None] = []
        warnings: list[str] = []
        if show_menu:
            issued: WidgetEnvelope = snapshot["widgets"][locale]
            previous_revision: int = int(widget_view["revision"]) if widget_view is not None and widget_view["widget_id"] == issued["widget_id"] else 0
            if previous_revision != issued["revision"]:
                messages.append({"kind": "widget_update" if previous_revision else "widget", "message_id": issued["widget_id"], "widget_id": issued["widget_id"], "revision": issued["revision"], "payload": build_menu_tree(snapshot["menu"], locale)})
                previews.append(build_menu_widget(snapshot["menu"], locale))
                authors.append("backend")
                controls.append(None)
        for proposal in reply.widgets:
            if proposal.target_role not in ("summary", "diagnostic"):
                raise ProviderError("The proposed widget is not bound to an authorized display target.")
            raw_source: str = json.dumps(proposal.payload, ensure_ascii=False)
            if validate_source(raw_source)["status"] != "valid":
                raise ProviderError("The assistant proposed an invalid widget.")
            tree, price_warnings = reconcile_price_bindings(proposal.payload, snapshot["menu"])
            tree = {**tree, "lang": locale}
            warnings.extend(price_warnings)
            preview: ContainerNode | None = validate_source(json.dumps(tree, ensure_ascii=False))["preview"]
            if preview is None or preview["kind"] != "card":
                raise ProviderError("The assistant proposed an unsupported widget.")
            try:
                validate_draft_identities(preview)
                bindings = bind_generic_actions(tree, snapshot["menu"], snapshot["cart"], locale)
            except WidgetActionError as error:
                raise ProviderError(str(error)) from error
            widget_id: str = proposal.target_widget_id or secrets.token_urlsafe(24)
            revision: int = 1
            if proposal.target_widget_id is not None:
                displayed = next((widget for widget in model_widgets if widget["widget_id"] == widget_id), None)
                if displayed is None:
                    raise ProviderError("The proposed update does not target an acknowledged displayed widget.")
                with closing(sqlite3.connect(path)) as connection:
                    owner: str = require_session(connection, token)
                    prior = connection.execute("SELECT revision FROM generic_widgets WHERE id = ? AND session_hash = ?", (widget_id, owner)).fetchone()
                if prior is None or prior[0] != displayed["revision"]:
                    raise ProviderError("The proposed update is no longer at its acknowledged displayed revision.")
                revision = prior[0] + 1
            if any(control is not None and control["widget_id"] == widget_id for control in controls):
                raise ProviderError("Duplicate updates for the same widget are not permitted.")
            generic: GenericWidget = {"widget_id": widget_id, "revision": revision, "menu_revision": snapshot["menu"]["revision"], "cart_revision": snapshot["cart"]["revision"], "bindings": bindings}
            messages.append({"kind": "widget_update" if proposal.target_widget_id else "widget", "message_id": secrets.token_urlsafe(24), "widget_id": widget_id, "revision": revision, "payload": tree})
            previews.append(preview)
            authors.append("model")
            controls.append(generic)
        result: ChatReply = {"message_id": response_id, "text": response_text, "suggestion": suggestion, "suggestions": suggestions, "menu_revision": snapshot["menu"]["revision"], "cart_revision": snapshot["cart"]["revision"], "widget": previews[0] if previews else None, "widget_previews": previews, "widget_authors": authors, "widget_controls": controls, "locale": locale, "messages": messages, "proposed_actions": proposed_actions, "widget_author": authors[0] if authors else None, "warnings": warnings}
        action_sequence: int = action_context["completed_actions"][-1]["sequence"] if action_context["completed_actions"] else 0
        await asyncio.to_thread(finish_turn, path, token, message_id, result, action_sequence)
        return result
    except (ChatError, ProviderError, MenuViewError, ConfirmationViewError, WidgetActionError, asyncio.CancelledError):
        await asyncio.to_thread(fail_turn, path, token, message_id)
        raise
