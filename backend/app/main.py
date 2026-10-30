import asyncio
import json
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Literal, TypedDict

from fastapi import FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field

from app.cart import CartError, SessionError, confirm_order, create_session, get_cart, initialize_cart, initialize_orders, set_quantity
from fastapi.responses import JSONResponse, StreamingResponse

from app.events import issue_menu_widget, read_snapshot
from app.widgets import WidgetError, acknowledge_widget, initialize_widgets
from app.widget_actions import WidgetActionError, apply_widget_quantity, initialize_widget_actions
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



class WidgetViewReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    widget_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    client_message_id: str = Field(min_length=1, max_length=128)
    rendered_view_id: str | None = Field(min_length=1, max_length=128)
    widget_view: WidgetViewReference | None = None
    text: str = Field(min_length=1, max_length=2000)
    menu_revision: int = Field(ge=1)
    locale: Literal["en", "ar"]


@app.post("/api/chat", response_model=None)
async def chat(payload: ChatRequest, request: Request) -> JSONResponse:
    if not is_local_demo_request(request, "chat"):
        return error_response(403, "invalid_origin", "Chat requires the local application.")
    try:
        reply = await respond(DATABASE_PATH, request.cookies.get("restaurant_session", ""), payload.client_message_id, payload.text, payload.menu_revision, payload.locale, payload.rendered_view_id, None, None if payload.widget_view is None else payload.widget_view.model_dump())
        return JSONResponse(content=reply)
    except SessionError:
        return error_response(401, "session_required", "Start a session to use chat.")
    except (ChatError, MenuViewError) as error:
        return error_response(409, "chat_conflict", str(error))
    except ProviderError as error:
        return error_response(502, "provider_error", str(error))

def sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stream", response_model=None)
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse | JSONResponse:
    if not is_local_demo_request(request, "chat"):
        return error_response(403, "invalid_origin", "Chat requires the local application.")
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    task = asyncio.create_task(respond(DATABASE_PATH, request.cookies.get("restaurant_session", ""), payload.client_message_id, payload.text, payload.menu_revision, payload.locale, payload.rendered_view_id, lambda event, data: queue.put_nowait((event, data)), None if payload.widget_view is None else payload.widget_view.model_dump()))
    started = asyncio.create_task(queue.get())
    await asyncio.wait({task, started}, return_when=asyncio.FIRST_COMPLETED)
    first: list[tuple[str, object]] = [started.result()] if started.done() else []
    if not first:
        started.cancel()
        try:
            task.result()
        except SessionError:
            return error_response(401, "session_required", "Start a session to use chat.")
        except (ChatError, MenuViewError) as error:
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
                except (ChatError, ProviderError, MenuViewError, SessionError) as error:
                    yield sse("error", {"message": str(error)})
                return
        finally:
            task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


@app.get("/api/events", response_model=None)
async def events(request: Request) -> StreamingResponse | JSONResponse:
    token: str = request.cookies.get("restaurant_session", "")
    try:
        initial = await asyncio.to_thread(read_snapshot, DATABASE_PATH, token)
    except SessionError:
        return error_response(401, "session_required", "Start a session to receive updates.")

    async def stream() -> AsyncIterator[str]:
        snapshot = initial
        while True:
            yield f"event: snapshot\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
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


@app.post("/api/actions", response_model=None)
def widget_action(payload: WidgetQuantityRequest, request: Request) -> JSONResponse:
    if not is_local_demo_request(request, "widget-action"):
        return error_response(403, "invalid_origin", "Widget actions require the local application.")
    action = {"widget_id": payload.widget_id, "revision": payload.revision, "action_id": payload.action_id, "type": payload.type, **payload.payload.model_dump()}
    try:
        return JSONResponse(content=apply_widget_quantity(DATABASE_PATH, request.cookies.get("restaurant_session", ""), action))
    except SessionError:
        return error_response(401, "session_required", "Start a session to use widget actions.")
    except (WidgetActionError, CartError) as error:
        return error_response(409, "widget_action_conflict", str(error))


class WidgetAcknowledgementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1)


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
        return JSONResponse(content=acknowledge_widget(DATABASE_PATH, request.cookies.get("restaurant_session", ""), widget_id, payload.revision))
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
