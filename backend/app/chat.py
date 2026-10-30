import asyncio
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Literal, TypedDict, cast

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.cart import require_session
from app.events import read_snapshot
from app.menu import MenuResponse
from app.menu_views import MenuViewError, get_menu_view, read_menu_view
from app.menu_widget import build_menu_widget
from app.validator import ContainerNode


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


class ChatReply(TypedDict):
    text: str
    suggestion: dict[str, str | int] | None
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
        if "rendered_view_id" not in columns:
            connection.execute("ALTER TABLE chat_turns ADD COLUMN rendered_view_id TEXT")
        if "locale" not in columns:
            connection.execute("ALTER TABLE chat_turns ADD COLUMN locale TEXT NOT NULL DEFAULT 'en'")


def begin_turn(path: Path, token: str, message_id: str, text: str, menu_revision: int, locale: Literal["en", "ar"], rendered_view_id: str | None) -> ChatReply | None:
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        session_hash: str = require_session(connection, token)
        read_menu_view(connection, session_hash, rendered_view_id, menu_revision, locale)
        existing = connection.execute("SELECT text, menu_revision, status, result_json, locale, rendered_view_id FROM chat_turns WHERE session_hash = ? AND message_id = ?", (session_hash, message_id)).fetchone()
        if existing is not None:
            if existing[0] != text or existing[1] != menu_revision or existing[4] != locale or existing[5] != rendered_view_id:
                raise ChatError("Message ID was already used for a different request.")
            if existing[2] == "complete":
                return cast(ChatReply, json.loads(existing[3]))
            raise ChatError("This message is already being processed or failed. Send a new message to retry.")
        connection.execute("INSERT INTO chat_turns (session_hash, message_id, text, menu_revision, status, locale, rendered_view_id) VALUES (?, ?, ?, ?, 'pending', ?, ?)", (session_hash, message_id, text, menu_revision, locale, rendered_view_id))
        return None


def finish_turn(path: Path, token: str, message_id: str, reply: ChatReply) -> None:
    with sqlite3.connect(path) as connection:
        session_hash: str = require_session(connection, token)
        connection.execute("UPDATE chat_turns SET status = 'complete', result_json = ? WHERE session_hash = ? AND message_id = ?", (json.dumps(reply, ensure_ascii=False), session_hash, message_id))


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


def read_history(path: Path, token: str) -> list[ProviderMessage]:
    """Return the latest 20 completed turns in conversation order for this session."""
    with sqlite3.connect(path) as connection:
        session_hash: str = require_session(connection, token)
        rows = connection.execute("SELECT text, result_json FROM chat_turns WHERE session_hash = ? AND status = 'complete' ORDER BY rowid DESC LIMIT 20", (session_hash,)).fetchall()
        messages: list[ProviderMessage] = []
        for text, result_json in reversed(rows):
            messages.extend([{"role": "user", "content": text}, {"role": "assistant", "content": result_json}])
        return messages


async def ask_provider(text: str, context: str, locale: Literal["en", "ar"], history: list[ProviderMessage]) -> ModelReply:
    key, model = provider_settings()
    prompt: str = (f"You are a restaurant assistant. Respond in {'English' if locale == 'en' else 'Arabic'} only, regardless of the language in the menu data. The menu and cart are authoritative. "
        "Return JSON with text, suggestion and show_menu. Set show_menu true whenever the customer asks to see the menu or available dishes; the app will display the menu, so keep the text brief. suggestion is null unless the customer explicitly asks to change "
        "a dish quantity. Otherwise use {item_id, quantity} with a supplied dish ID and the desired total quantity. "
        "Never claim a change or order was completed; suggestions require the customer to apply them. "
        "Never suggest increasing a sold-out item. Resolve ordinal references ONLY using displayed_menu positions, never current_menu or a historical assistant message. If displayed_menu is null, ask for clarification on ordinal references. The current_menu and cart determine current availability, not the meaning of a displayed position. "
        "Count every displayed dish row, including sold-out dishes. Ask a clarification if ambiguous. Never invent prices or dishes.")
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(2):
            try:
                response = await client.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={"model": model, "messages": [{"role": "system", "content": prompt}, *history, {"role": "user", "content": f"Displayed and current restaurant data: {context}\nCustomer message: {text}"}], "response_format": {"type": "json_schema", "json_schema": {"name": "restaurant_reply", "strict": True, "schema": ModelReply.model_json_schema()}}, "provider": {"require_parameters": True}, "max_tokens": 400})
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


async def respond(path: Path, token: str, message_id: str, text: str, menu_revision: int, locale: Literal["en", "ar"], rendered_view_id: str | None) -> ChatReply:
    prior: ChatReply | None = await asyncio.to_thread(begin_turn, path, token, message_id, text, menu_revision, locale, rendered_view_id)
    if prior is not None:
        return prior
    try:
        snapshot = await asyncio.to_thread(read_snapshot, path, token)
        displayed_menu: MenuResponse | None = await asyncio.to_thread(get_menu_view, path, token, rendered_view_id, menu_revision, locale)
        localized_menu = [{"id": item["id"], "position": item["position"], "name": item["name"][locale], "price_minor": item["price_minor"], "currency": item["currency"], "available": item["available"]} for item in snapshot["menu"]["items"]]
        localized_cart = [{"id": item["id"], "name": item["name_en"] if locale == "en" else item["name_ar"], "quantity": item["quantity"], "available": item["available"]} for item in snapshot["cart"]["items"]]
        displayed_items: list[dict[str, str | int | bool]] | None = None if displayed_menu is None else [{"id": item["id"], "position": item["position"], "name": item["name"][locale], "available": item["available"]} for item in displayed_menu["items"]]
        history: list[ProviderMessage] = await asyncio.to_thread(read_history, path, token)
        reply: ModelReply = await ask_provider(text, json.dumps({"displayed_menu": displayed_items, "current_menu": localized_menu, "cart": localized_cart}, ensure_ascii=False), locale, history)
        suggestion: dict[str, str | int] | None = None
        if reply.suggestion is not None:
            item = next((item for item in snapshot["menu"]["items"] if item["id"] == reply.suggestion.item_id), None)
            if item is None:
                raise ProviderError("The assistant suggested an unknown menu item. Please try again.")
            current: int = next((entry["quantity"] for entry in snapshot["cart"]["items"] if entry["id"] == item["id"]), 0)
            if not item["available"] and reply.suggestion.quantity > current:
                raise ProviderError("The assistant suggested an unavailable item. Please try again.")
            suggestion = {"item_id": item["id"], "quantity": reply.suggestion.quantity}
        result: ChatReply = {"text": reply.text, "suggestion": suggestion, "menu_revision": snapshot["menu"]["revision"], "cart_revision": snapshot["cart"]["revision"], "widget": build_menu_widget(snapshot["menu"], locale) if reply.show_menu else None, "locale": locale}
        await asyncio.to_thread(finish_turn, path, token, message_id, result)
        return result
    except (ChatError, ProviderError, MenuViewError):
        await asyncio.to_thread(fail_turn, path, token, message_id)
        raise
