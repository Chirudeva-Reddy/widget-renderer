import asyncio
import json
import logging
import os
import re
import sqlite3
from contextlib import closing
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypedDict, cast

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.cart import CompletedAction, read_completed_actions, require_session
from app.confirmation_widget import ConfirmationContext, ConfirmationReference, ConfirmationViewError, read_confirmation_context, read_confirmation_view
from app.events import Snapshot, read_session_snapshot
from app.menu import MenuResponse
from app.menu_views import MenuViewError, get_menu_view, read_menu_view
from app.menu_widget import build_menu_widget
from app.validator import ContainerNode, Node, validate_source
from app.widgets import WidgetEnvelope


logger: logging.Logger = logging.getLogger(__name__)


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=0, le=99)


class ModelReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=1200)
    suggestion: Suggestion | None
    show_menu: bool
    # ponytail: widget JSON travels as a string because strict response schemas cannot express the recursive tree; validate_source parses it.
    summary_card: str | None = Field(max_length=8000)


class QuantityProposal(TypedDict):
    item_id: str
    quantity: int


class QuantityReference(QuantityProposal):
    source: Literal["completed_action", "assistant_proposal"]


class ChatReply(TypedDict):
    text: str
    suggestion: QuantityProposal | None
    menu_revision: int
    cart_revision: str
    widget: ContainerNode | None
    locale: Literal["en", "ar"]


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


def read_widget_view(connection: sqlite3.Connection, session_hash: str, reference: dict[str, str | int], locale: Literal["en", "ar"], menu_revision: int, rendered_view_id: str | None) -> WidgetEnvelope:
    row: tuple[str] | None = connection.execute("SELECT r.envelope_json FROM widgets w JOIN widget_revisions r ON r.widget_id = w.id WHERE w.id = ? AND w.session_hash = ? AND w.locale = ? AND r.revision = ?", (reference["widget_id"], session_hash, locale, reference["revision"])).fetchone()
    if row is None:
        raise ChatError("The displayed widget could not be verified. Refresh the menu and try again.")
    envelope: WidgetEnvelope = cast(WidgetEnvelope, json.loads(row[0]))
    if envelope["menu_view_id"] != rendered_view_id or envelope["menu"]["revision"] != menu_revision:
        raise ChatError("The displayed widget does not match the menu view. Refresh the menu and try again.")
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
            read_confirmation_view(connection, session_hash, confirmation_view)
        confirmation_json: str | None = None if confirmation_view is None else json.dumps(confirmation_view, sort_keys=True)
        widget_json: str | None = None if widget_view is None else json.dumps(widget_view, sort_keys=True)
        existing = connection.execute("SELECT text, menu_revision, status, result_json, locale, rendered_view_id, widget_view, confirmation_view FROM chat_turns WHERE session_hash = ? AND message_id = ?", (session_hash, message_id)).fetchone()
        if existing is not None:
            if existing[0] != text or existing[1] != menu_revision or existing[4] != locale or existing[5] != rendered_view_id or existing[6] != widget_json or existing[7] != confirmation_json:
                raise ChatError("Message ID was already used for a different request.")
            if existing[2] == "complete":
                return cast(ChatReply, json.loads(existing[3]))
            raise ChatError("This message is already being processed or failed. Send a new message to retry.")
        connection.execute("INSERT INTO chat_turns (session_hash, message_id, text, menu_revision, status, locale, rendered_view_id, widget_view, confirmation_view) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)", (session_hash, message_id, text, menu_revision, locale, rendered_view_id, widget_json, confirmation_json))
        return None


def finish_turn(path: Path, token: str, message_id: str, reply: ChatReply, action_sequence: int) -> None:
    with sqlite3.connect(path) as connection:
        session_hash: str = require_session(connection, token)
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
        "Return JSON with text, suggestion and show_menu. Set show_menu true whenever the customer asks to see the menu or available dishes; the app will display the menu, so keep the text brief. suggestion is null unless the customer explicitly asks to change "
        "a dish quantity. Otherwise use {item_id, quantity} with a supplied dish ID and the desired total quantity. "
        "Only completed_actions supplied by the backend prove a past control action completed. You may acknowledge those actions, but new suggestions still require the customer to apply them; never claim a new proposal has executed. "
        "quantity_reference is the backend-resolved item for implicit requests such as make that three. For such an implicit follow-up, use its item_id when present, not a different dish from history or the current cart. "
        "An explicit dish name in the current message takes precedence; ordinal references use displayed_menu as specified below. If no reference exists and the target is unclear, ask for clarification. "
        "A quantity_reference with source assistant_proposal identifies a conversational proposal, not an executed action. Only completed_actions prove execution. "
        "When the user explicitly requests a quantity and its target is known, return the suggestion directly; the Apply control already requires approval, so do not ask a redundant confirmation question. "
        "An order.confirm action contains an immutable receipt: use its stored items, prices, total and order ID even when the current cart is empty. Never recalculate a confirmed receipt using current menu prices, or claim a confirmed order was edited. "
        "Never suggest increasing a sold-out item. Resolve ordinal references ONLY using displayed_menu positions, never current_menu or a historical assistant message. If displayed_menu is null, ask for clarification on ordinal references. The current_menu and cart determine current availability, not the meaning of a displayed position. "
        "displayed_confirmation is the issued review card, locale, acknowledgement status and current validity. It is a review, never proof of a confirmed order. Its saved items and total describe that snapshot; active false means it is stale or consumed. Only completed_actions prove an order was confirmed. "
        "displayed_widget is the server-issued snapshot backing the displayed menu. Its cart contains saved quantities only; unsaved quantity inputs may differ and are not included. Never claim to know an unsaved or currently visible input value from this snapshot; ask the customer when needed. current_menu and cart describe current state. "
        "Count every displayed dish row, including sold-out dishes. Ask a clarification if ambiguous. Never invent prices or dishes. "
        "summary_card is null unless a compact visual summary genuinely helps, such as when the customer asks for a cart or order summary or a short comparison of dishes. Never set it together with show_menu. "
        "When set, summary_card is a JSON string (not an object) holding one read-only widget tree. The root is {\"type\":\"Card\",\"children\":[...]}. Allowed children: "
        "Title, Text and Caption as {\"type\":\"Text\",\"value\":\"...\"} with optional weight normal, medium, semibold or bold; Badge as {\"type\":\"Badge\",\"label\":\"...\"}; Divider and Spacer as {\"type\":\"Divider\"}; "
        "Row, Col and Box as {\"type\":\"Row\",\"gap\":2,\"children\":[...]} where gap is an optional integer 0 to 8 on Row and Col only; Table as {\"type\":\"Table\",\"children\":[{\"type\":\"Table.Row\",\"header\":true,\"children\":[{\"type\":\"Table.Cell\",\"align\":\"end\",\"children\":[...]}]}]}. "
        "Text values are strings, containers always have a children array, and sibling key values, if used, must be unique. Use no other components or properties: no Button, Input, Select, Form, links, scripts, HTML, markdown or styling. "
        "The card is display-only and cannot change the cart or place an order. Write every label in the reply language, using the supplied localized dish names. Copy prices, quantities, totals and order IDs exactly from current_menu, cart or an order.confirm receipt, "
        "formatting price_minor as major units with its currency; omit any figure you were not given. Never present a card as a confirmed order unless it restates an order.confirm receipt. Keep it small: at most 30 components. "
        "Example: {\"type\":\"Card\",\"children\":[{\"type\":\"Title\",\"value\":\"Your cart\"},{\"type\":\"Row\",\"children\":[{\"type\":\"Text\",\"value\":\"Hummus x2\"},{\"type\":\"Text\",\"value\":\"AED 36.00\",\"weight\":\"semibold\"}]}]}.")
    return key, {"model": model, "messages": [{"role": "system", "content": prompt}, *history, {"role": "user", "content": f"Displayed and current restaurant data: {context}\nCustomer message: {text}"}], "response_format": {"type": "json_schema", "json_schema": {"name": "restaurant_reply", "strict": True, "schema": ModelReply.model_json_schema()}}, "provider": {"require_parameters": True}, "max_tokens": 1500}


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
CARD_START: re.Pattern[str] = re.compile(r'"summary_card"\s*:\s*"')
TEXT_START: re.Pattern[str] = re.compile(r'"text"\s*:\s*"')
CARD_ROOT: re.Pattern[str] = re.compile(r'\s*\{\s*"type"\s*:\s*"Card"\s*,\s*"children"\s*:\s*\[')


def json_string_prefix(source: str, start: int) -> tuple[str, bool]:
    """Decode the complete part of a JSON string literal whose opening quote ends at start."""
    index: int = start
    while index < len(source):
        if source[index] == '"':
            return json.loads(source[start - 1:index + 1]), True
        if source[index] == "\\":
            width: int = 6 if source[index + 1:index + 2] == "u" else 2
            if index + width > len(source):
                break
            index += width
        else:
            index += 1
    safe: str = source[start:index]
    if re.search(r"\\u[dD][89abAB][0-9a-fA-F]{2}$", safe):
        safe = safe[:-6]
    return json.loads(f'"{safe}"'), False


class SummaryCardStream:
    """Emits each complete, validated top-level child of summary_card while the reply is still generating."""

    def __init__(self, emit: Emit) -> None:
        self.emit: Emit = emit
        self.sent: int = 0
        self.started: bool = False

    def feed(self, content: str) -> None:
        # ponytail: re-scans the whole buffer per chunk; O(n^2) but replies are capped at a few KB.
        # ponytail: only streams cards written as {"type":"Card","children":[...; other key orders still render on the final event.
        try:
            card = CARD_START.search(content)
            if card is None:
                return
            if not self.started:
                self.started = True
                text = TEXT_START.search(content, 0, card.start())
                decoded, closed = json_string_prefix(content, text.end()) if text else ("", False)
                self.emit("card", {"text": decoded if closed else None})
            source, _ = json_string_prefix(content, card.end())
            root = CARD_ROOT.match(source)
            if root is None:
                return
            decoder = json.JSONDecoder()
            position: int = root.end()
            index: int = 0
            while True:
                while position < len(source) and source[position] in " \t\r\n,":
                    position += 1
                if position >= len(source) or source[position] == "]":
                    return
                child, position = decoder.raw_decode(source, position)
                if index == self.sent:
                    self.sent += 1
                    node: ContainerNode | None = display_card(json.dumps({"type": "Card", "children": [child]}, ensure_ascii=False))
                    if node is not None:
                        self.emit("component", {"index": index, "node": node["children"][0]})
                index += 1
        except ValueError:
            return


async def stream_provider(text: str, context: str, locale: Literal["en", "ar"], history: list[ProviderMessage], emit: Emit) -> ModelReply:
    # ponytail: no retry once streaming starts, components may already be on screen.
    key, body = provider_request(text, context, locale, history)
    card = SummaryCardStream(emit)
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
                card.feed(content)
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


def bind_summary_card(source: str | None) -> ContainerNode | None:
    """Accept only a validated, display-only Card; anything else becomes a visible problem instead of a widget."""
    if source is None:
        return None
    preview: ContainerNode | None = display_card(source)
    if preview is None:
        logger.warning("Rejected assistant summary card")
        return {"kind": "card", "children": [{"kind": "problem", "message": "The assistant's summary could not be displayed."}]}
    return preview


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
    if unseen:
        latest: CompletedAction = unseen[-1]
        if latest["type"] == "cart.set_quantity":
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


async def respond(path: Path, token: str, message_id: str, text: str, menu_revision: int, locale: Literal["en", "ar"], rendered_view_id: str | None, confirmation_view: ConfirmationReference | None, emit: Emit | None = None, widget_view: dict[str, str | int] | None = None) -> ChatReply:
    prior: ChatReply | None = await asyncio.to_thread(begin_turn, path, token, message_id, text, menu_revision, locale, rendered_view_id, widget_view, confirmation_view)
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
        context: str = json.dumps({"displayed_confirmation": action_context["displayed_confirmation"], "displayed_menu": displayed_items, "displayed_widget": displayed_widget, "current_menu": localized_menu, "cart": localized_cart, "completed_actions": action_context["completed_actions"], "quantity_reference": action_context["quantity_reference"]}, ensure_ascii=False)
        reply: ModelReply = await (ask_provider(text, context, locale, history) if emit is None else stream_provider(text, context, locale, history, emit))
        suggestion: QuantityProposal | None = None
        if reply.suggestion is not None:
            item = next((item for item in snapshot["menu"]["items"] if item["id"] == reply.suggestion.item_id), None)
            if item is None:
                raise ProviderError("The assistant suggested an unknown menu item. Please try again.")
            current: int = next((entry["quantity"] for entry in snapshot["cart"]["items"] if entry["id"] == item["id"]), 0)
            if not item["available"] and reply.suggestion.quantity > current:
                raise ProviderError("The assistant suggested an unavailable item. Please try again.")
            suggestion = {"item_id": item["id"], "quantity": reply.suggestion.quantity}
        result: ChatReply = {"text": reply.text, "suggestion": suggestion, "menu_revision": snapshot["menu"]["revision"], "cart_revision": snapshot["cart"]["revision"], "widget": build_menu_widget(snapshot["menu"], locale) if reply.show_menu else bind_summary_card(reply.summary_card), "locale": locale}
        action_sequence: int = action_context["completed_actions"][-1]["sequence"] if action_context["completed_actions"] else 0
        await asyncio.to_thread(finish_turn, path, token, message_id, result, action_sequence)
        return result
    except (ChatError, ProviderError, MenuViewError, ConfirmationViewError, asyncio.CancelledError):
        await asyncio.to_thread(fail_turn, path, token, message_id)
        raise
