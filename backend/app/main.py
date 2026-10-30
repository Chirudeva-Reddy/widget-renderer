import asyncio
import json
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Annotated, Literal, TypedDict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field

from app.cart import CartError, SessionError, confirm_order, create_session, get_cart, initialize_cart, initialize_orders, set_quantity
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.generic_views import GenericReference, acknowledge_generic, read_generic_state
from app.events import issue_menu_widget, read_snapshot
from app.confirmation_widget import ConfirmationViewError, acknowledge_confirmation
from app.widgets import WidgetError, acknowledge_widget, initialize_widgets
from app.widget_actions import WidgetActionError, apply_widget_quantity, confirm_widget_order, edit_widget_order, initialize_widget_actions, set_widget_locale, start_checkout
from app.menu_views import MenuViewError, initialize_menu_views
from app.chat import ChatError, ProviderError, initialize_chat, respond

from app.menu import DATABASE_PATH, ItemNotFoundError, MenuResponse, get_menu, initialize_menu, restock_item, sell_out_item
from app.validator import InvalidSource, ValidationResult, unique_object, validate_source

@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    initialize_menu(DATABASE_PATH)
    initialize_cart(DATABASE_PATH)
    initialize_orders(DATABASE_PATH)
    initialize_chat(DATABASE_PATH)
    initialize_menu_views(DATABASE_PATH)
    initialize_widgets(DATABASE_PATH)
    initialize_widget_actions(DATABASE_PATH)
    yield


app: FastAPI = FastAPI(lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def request_validation_error(request: Request, error: RequestValidationError) -> Response:
    """Return JSON-safe diagnostics without echoing untrusted request values."""
    issues: list[dict[str, object]] = [{"type": issue["type"], "loc": issue["loc"], "msg": issue["msg"]} for issue in error.errors()]
    return Response(status_code=422, media_type="application/json", content=json.dumps({"code": "invalid_request", "message": "Request validation failed. Check the reported fields.", "detail": issues}, ensure_ascii=True))


class HealthResponse(TypedDict):
    status: Literal["ok"]


@app.get("/api/health")
async def health() -> HealthResponse:
    return {"status": "ok"}


@app.get("/api/menu")
def menu() -> MenuResponse:
    return get_menu(DATABASE_PATH)



class CartQuantityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: str = Field(min_length=1, max_length=128)
    item_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=0, le=99)
    cart_revision: str = Field(min_length=64, max_length=64)


@app.post("/api/session", response_model=None)
def session(request: Request) -> JSONResponse:
    if not is_local_demo_request(request, "session"):
        return error_response(403, "invalid_origin", "Session creation requires the local application.")
    token: str = request.cookies.get("restaurant_session", "")
    if token:
        try:
            return JSONResponse(content=get_cart(DATABASE_PATH, token))
        except SessionError:
            token = ""
    token = create_session(DATABASE_PATH)
    response: JSONResponse = JSONResponse(content=get_cart(DATABASE_PATH, token))
    response.set_cookie("restaurant_session", token, httponly=True, samesite="strict", secure=False, max_age=86400, path="/")
    return response


@app.get("/api/cart", response_model=None)
def cart(request: Request) -> JSONResponse:
    try:
        return JSONResponse(content=get_cart(DATABASE_PATH, request.cookies.get("restaurant_session", "")))
    except SessionError:
        return error_response(401, "session_required", "Start a session to access your cart.")


@app.post("/api/cart/quantity", response_model=None)
def cart_quantity(payload: CartQuantityRequest, request: Request) -> JSONResponse:
    if not is_local_demo_request(request, "cart"):
        return error_response(403, "invalid_origin", "Cart changes require the local application.")
    try:
        return JSONResponse(content=set_quantity(DATABASE_PATH, request.cookies.get("restaurant_session", ""), payload.action_id, payload.item_id, payload.quantity, payload.cart_revision))
    except SessionError:
        return error_response(401, "session_required", "Start a session to access your cart.")
    except CartError as error:
        return error_response(409, "cart_conflict", str(error))


class ConfirmOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: str = Field(min_length=1, max_length=128)
    cart_revision: str = Field(min_length=64, max_length=64)


@app.post("/api/orders/confirm", response_model=None)
def order_confirm(payload: ConfirmOrderRequest, request: Request) -> JSONResponse:
    if not is_local_demo_request(request, "confirm"):
        return error_response(403, "invalid_origin", "Order confirmation requires the local application.")
    try:
        return JSONResponse(content=confirm_order(DATABASE_PATH, request.cookies.get("restaurant_session", ""), payload.action_id, payload.cart_revision))
    except SessionError:
        return error_response(401, "session_required", "Start a session to confirm your order.")
    except CartError as error:
        return error_response(409, "order_conflict", str(error))



class RenderedControls(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input: bool
    decrease: bool
    increase: bool
    apply: bool
    remove: bool


class RenderedRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str = Field(min_length=1, max_length=128)
    position: int = Field(ge=1)
    sold_out: bool
    placeholder: bool
    quantity: str = Field(max_length=100)
    draft: bool
    edit_revision: str | None = Field(min_length=64, max_length=64)
    changed_revision: str | None = Field(min_length=64, max_length=64)
    disabled: bool
    controls: RenderedControls
    issues: list[Literal["invalid_quantity", "stale_cart", "sold_out"]] = Field(max_length=3)


class RenderedView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    locale: Literal["en", "ar"]
    rows: list[RenderedRow] = Field(max_length=100)
    checkout_disabled: bool


class ConfirmationRenderedRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=1, le=99)
    sold_out: bool


class ConfirmationRenderedView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    locale: Literal["en", "ar"]
    rows: list[ConfirmationRenderedRow] = Field(max_length=100)
    edit_disabled: bool
    confirm_disabled: bool
    issues: list[Literal["stale", "drafts", "sold_out", "disconnected"]] = Field(max_length=4)


class WidgetViewReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    widget_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    rendered: RenderedView


class ConfirmationViewReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    widget_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    rendered: ConfirmationRenderedView


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    generic_views: list[GenericReference] = Field(default_factory=list, max_length=100)
    client_message_id: str = Field(min_length=1, max_length=128)
    rendered_view_id: str | None = Field(min_length=1, max_length=128)
    widget_view: WidgetViewReference | None = None
    confirmation_view: ConfirmationViewReference | None = None
    text: str = Field(min_length=1, max_length=2000)
    menu_revision: int = Field(ge=1)
    locale: Literal["en", "ar"]


@app.post("/api/chat", response_model=None)
async def chat(payload: ChatRequest, request: Request) -> JSONResponse:
    if not is_local_demo_request(request, "chat"):
        return error_response(403, "invalid_origin", "Chat requires the local application.")
    if payload.rendered_view_id is not None and payload.widget_view is None:
        return error_response(422, "rendered_view_required", "Include the displayed widget snapshot with the menu view.")
    try:
        reply = await respond(DATABASE_PATH, request.cookies.get("restaurant_session", ""), payload.client_message_id, payload.text, payload.menu_revision, payload.locale, payload.rendered_view_id, None if payload.confirmation_view is None else payload.confirmation_view.model_dump(), None, None if payload.widget_view is None else payload.widget_view.model_dump(), payload.generic_views)
        return JSONResponse(content=reply)
    except SessionError:
        return error_response(401, "session_required", "Start a session to use chat.")
    except (ChatError, MenuViewError, ConfirmationViewError, WidgetActionError) as error:
        return error_response(409, "chat_conflict", str(error))
    except ProviderError as error:
        return error_response(502, "provider_error", str(error))

def sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream", response_model=None)
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse | JSONResponse:
    if not is_local_demo_request(request, "chat"):
        return error_response(403, "invalid_origin", "Chat requires the local application.")
    if payload.rendered_view_id is not None and payload.widget_view is None:
        return error_response(422, "rendered_view_required", "Include the displayed widget snapshot with the menu view.")
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    task = asyncio.create_task(respond(DATABASE_PATH, request.cookies.get("restaurant_session", ""), payload.client_message_id, payload.text, payload.menu_revision, payload.locale, payload.rendered_view_id, None if payload.confirmation_view is None else payload.confirmation_view.model_dump(), lambda event, data: queue.put_nowait((event, data)), None if payload.widget_view is None else payload.widget_view.model_dump(), payload.generic_views))
    started = asyncio.create_task(queue.get())
    await asyncio.wait({task, started}, return_when=asyncio.FIRST_COMPLETED)
    first: list[tuple[str, object]] = [started.result()] if started.done() else []
    if not first:
        started.cancel()
        try:
            task.result()
        except SessionError:
            return error_response(401, "session_required", "Start a session to use chat.")
        except (ChatError, MenuViewError, ConfirmationViewError, WidgetActionError) as error:
            return error_response(409, "chat_conflict", str(error))
        except ProviderError as error:
            return error_response(502, "provider_error", str(error))

    async def stream() -> AsyncIterator[str]:
        try:
            for event, data in first:
                yield sse(event, data)
            while True:
                waiting = asyncio.create_task(queue.get())
                await asyncio.wait({task, waiting}, return_when=asyncio.FIRST_COMPLETED)
                if waiting.done():
                    yield sse(*waiting.result())
                    continue
                waiting.cancel()
                while not queue.empty():
                    yield sse(*queue.get_nowait())
                try:
                    yield sse("final", task.result())
                except (ChatError, ProviderError, MenuViewError, ConfirmationViewError, WidgetActionError, SessionError) as error:
                    yield sse("error", {"message": str(error)})
                return
        finally:
            task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


@app.get("/api/state", response_model=None)
def state(request: Request) -> JSONResponse:
    """Return the owning session's authoritative snapshot without caching it."""
    try:
        return JSONResponse(content=read_snapshot(DATABASE_PATH, request.cookies.get("restaurant_session", "")), headers={"Cache-Control": "no-store"})
    except SessionError:
        return error_response(401, "session_required", "Start a session to synchronize widgets.")


@app.get("/api/events", response_model=None)
async def events(request: Request) -> StreamingResponse | JSONResponse:
    """Stream full current snapshots; event IDs identify state rather than a replay cursor."""
    token: str = request.cookies.get("restaurant_session", "")
    try:
        initial = await asyncio.to_thread(read_snapshot, DATABASE_PATH, token)
    except SessionError:
        return error_response(401, "session_required", "Start a session to receive updates.")

    async def stream() -> AsyncIterator[str]:
        snapshot = initial
        while True:
            yield f"id: {snapshot['state_revision']}\nevent: snapshot\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            await asyncio.sleep(1)
            try:
                snapshot = await asyncio.to_thread(read_snapshot, DATABASE_PATH, token)
            except SessionError:
                yield 'event: session_expired\ndata: {}\n\n'
                return

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

@app.post("/api/demo/menu/{item_id}/sell-out", response_model=None)
def sell_out(item_id: str, request: Request) -> MenuResponse | JSONResponse:
    if not is_local_demo_request(request, "sell-out"):
        return error_response(403, "demo_only", "This control is available only in the local demo.")
    try:
        return sell_out_item(DATABASE_PATH, item_id)
    except ItemNotFoundError:
        return error_response(404, "item_not_found", "Menu item not found.")


@app.post("/api/demo/menu/{item_id}/restock", response_model=None)
def restock(item_id: str, request: Request) -> MenuResponse | JSONResponse:
    if not is_local_demo_request(request, "restock"):
        return error_response(403, "demo_only", "This control is available only in the local demo.")
    try:
        return restock_item(DATABASE_PATH, item_id)
    except ItemNotFoundError:
        return error_response(404, "item_not_found", "Menu item not found.")


def is_local_demo_request(request: Request, action: str) -> bool:
    host: str = request.url.hostname or ""
    origin: str = request.headers.get("origin", "")
    return (request.client is not None and request.client.host in ("127.0.0.1", "::1") and host in ("127.0.0.1", "localhost", "::1") and origin in ("http://127.0.0.1:5173", "http://localhost:5173") and request.headers.get("x-demo-action") == action)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


class WidgetQuantityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str = Field(min_length=1, max_length=128)
    position: int = Field(ge=1)
    quantity: int = Field(ge=0, le=99)
    cart_revision: str = Field(min_length=64, max_length=64)


class WidgetQuantityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    widget_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    action_id: str = Field(min_length=1, max_length=128)
    type: Literal["cart.set_quantity"]
    payload: WidgetQuantityPayload


class WidgetCheckoutPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cart_revision: str = Field(min_length=64, max_length=64)


class WidgetItemPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=128)
    position: int = Field(ge=1)


class WidgetItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    widget_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    action_id: str = Field(min_length=1, max_length=128)
    type: Literal["cart.add", "cart.remove"]
    payload: WidgetItemPayload


class WidgetLocalePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    lang: Literal["en", "ar"]


class WidgetLocaleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    widget_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    action_id: str = Field(min_length=1, max_length=128)
    type: Literal["locale.set"]
    payload: WidgetLocalePayload


class WidgetCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    widget_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    action_id: str = Field(min_length=1, max_length=128)
    type: Literal["checkout.start", "order.confirm", "order.edit"]
    payload: WidgetCheckoutPayload


@app.post("/api/actions", response_model=None)
def widget_action(payload: WidgetQuantityRequest | WidgetCheckoutRequest | WidgetItemRequest | WidgetLocaleRequest, request: Request) -> JSONResponse:
    if not is_local_demo_request(request, "widget-action"):
        return error_response(403, "invalid_origin", "Widget actions require the local application.")
    action = {"widget_id": payload.widget_id, "revision": payload.revision, "action_id": payload.action_id, "type": payload.type, **payload.payload.model_dump()}
    if isinstance(payload, WidgetItemRequest):
        action["item_id"] = action.pop("id")
    try:
        token: str = request.cookies.get("restaurant_session", "")
        if payload.type == "locale.set":
            return JSONResponse(content=set_widget_locale(DATABASE_PATH, token, action))
        if payload.type in ("cart.set_quantity", "cart.add", "cart.remove"):
            return JSONResponse(content=apply_widget_quantity(DATABASE_PATH, token, action))
        if payload.type == "checkout.start":
            return JSONResponse(content=start_checkout(DATABASE_PATH, token, action))
        if payload.type == "order.confirm":
            return JSONResponse(content=confirm_widget_order(DATABASE_PATH, token, action))
        return JSONResponse(content=edit_widget_order(DATABASE_PATH, token, action))
    except SessionError:
        return error_response(401, "session_required", "Start a session to use widget actions.")
    except (WidgetActionError, CartError, ConfirmationViewError) as error:
        return error_response(409, "widget_action_conflict", str(error))


class WidgetAcknowledgementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1)
    rendered: RenderedView


class ConfirmationAcknowledgementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1)
    locale: Literal["en", "ar"]
    rendered: ConfirmationRenderedView


class GenericStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    widget_ids: list[Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]] = Field(max_length=100)


@app.post("/api/widgets/generic-state", response_model=None)
def generic_state(payload: GenericStateRequest, request: Request) -> JSONResponse:
    if not is_local_demo_request(request, "widget-rendered"):
        return error_response(403, "invalid_origin", "Widget synchronization requires the local application.")
    if len(set(payload.widget_ids)) != len(payload.widget_ids) or any(not 1 <= len(widget_id) <= 128 for widget_id in payload.widget_ids):
        return error_response(422, "invalid_widgets", "Generic widget IDs must be bounded and unique.")
    try:
        return JSONResponse(content=read_generic_state(DATABASE_PATH, request.cookies.get("restaurant_session", ""), payload.widget_ids))
    except SessionError:
        return error_response(401, "session_required", "Start a session to synchronize widgets.")
    except WidgetActionError as error:
        return error_response(409, "widget_conflict", str(error))


@app.post("/api/widgets/{widget_id}/generic-rendered", response_model=None)
def generic_rendered(widget_id: str, payload: GenericReference, request: Request) -> JSONResponse:
    if not is_local_demo_request(request, "widget-rendered"):
        return error_response(403, "invalid_origin", "Widget acknowledgements require the local application.")
    if widget_id != payload.widget_id:
        return error_response(409, "widget_conflict", "Generic widget identity does not match its acknowledgement.")
    try:
        return JSONResponse(content=acknowledge_generic(DATABASE_PATH, request.cookies.get("restaurant_session", ""), payload))
    except SessionError:
        return error_response(401, "session_required", "Start a session to acknowledge widgets.")
    except WidgetActionError as error:
        return error_response(409, "widget_conflict", str(error))


@app.post("/api/widgets/{widget_id}/confirmation-rendered", response_model=None)
def confirmation_rendered(widget_id: str, payload: ConfirmationAcknowledgementRequest, request: Request) -> JSONResponse:
    if not is_local_demo_request(request, "widget-rendered"):
        return error_response(403, "invalid_origin", "Widget acknowledgements require the local application.")
    try:
        return JSONResponse(content=acknowledge_confirmation(DATABASE_PATH, request.cookies.get("restaurant_session", ""), {"widget_id": widget_id, "revision": payload.revision}, payload.locale, payload.rendered.model_dump()))
    except SessionError:
        return error_response(401, "session_required", "Start a session to acknowledge widgets.")
    except ConfirmationViewError as error:
        return error_response(409, "widget_conflict", str(error))


@app.get("/api/widgets/menu/{locale}", response_model=None)
def widget_menu(locale: Literal["en", "ar"], request: Request) -> JSONResponse:
    try:
        return JSONResponse(content=issue_menu_widget(DATABASE_PATH, request.cookies.get("restaurant_session", ""), locale))
    except SessionError:
        return error_response(401, "session_required", "Start a session to access widgets.")


@app.post("/api/widgets/{widget_id}/rendered", response_model=None)
def widget_rendered(widget_id: str, payload: WidgetAcknowledgementRequest, request: Request) -> JSONResponse:
    if not is_local_demo_request(request, "widget-rendered"):
        return error_response(403, "invalid_origin", "Widget acknowledgements require the local application.")
    try:
        return JSONResponse(content=acknowledge_widget(DATABASE_PATH, request.cookies.get("restaurant_session", ""), widget_id, payload.revision, payload.rendered.model_dump()))
    except SessionError:
        return error_response(401, "session_required", "Start a session to acknowledge widgets.")
    except WidgetError as error:
        return error_response(409, "widget_conflict", str(error))


@app.post("/api/payloads/validate")
async def validate_payload(request: Request) -> JSONResponse:
    content_type: str = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return error_response(415, "unsupported_media_type", "Content type must be application/json.")
    body: bytearray = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 262144:
            return error_response(413, "body_limit", "Request body exceeds the size limit.")
        body.extend(chunk)
    try:
        envelope: object = json.loads(body, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError, InvalidSource, RecursionError):
        return error_response(422, "invalid_envelope", "Request must contain a valid JSON object.")
    if not isinstance(envelope, dict) or set(envelope) != {"source"} or not isinstance(envelope["source"], str):
        return error_response(422, "invalid_envelope", "Request must contain only a string source field.")
    source: str = envelope["source"]
    try:
        source.encode("utf-8")
    except UnicodeEncodeError:
        return error_response(422, "invalid_unicode", "Source contains invalid Unicode.")
    try:
        result: ValidationResult = validate_source(source)
    except UnicodeEncodeError:
        return error_response(422, "invalid_unicode", "Source contains invalid Unicode.")
    return JSONResponse(content=result)
