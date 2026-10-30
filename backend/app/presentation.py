import re
from typing import Literal, NotRequired, TypedDict, cast


class Appearance(TypedDict):
    locale: NotRequired[Literal["en", "ar"]]
    width: NotRequired[int | str]
    height: NotRequired[int | str]
    minWidth: NotRequired[int]
    paddingInline: NotRequired[int]
    paddingBlock: NotRequired[int]
    borderWidth: NotRequired[int]
    borderColor: NotRequired[Literal["subtle", "default", "strong"]]
    theme: NotRequired[Literal["light", "dark"]]
    size: NotRequired[Literal["sm", "md", "lg", "full"]]
    variant: NotRequired[Literal["solid", "soft", "outline", "ghost"]]
    primary: NotRequired[bool]
    uniform: NotRequired[bool]
    block: NotRequired[bool]
    flush: NotRequired[bool]
    color: NotRequired[Literal["subtle", "default", "strong"]]
    limit: NotRequired[int]


def bounded_integer(value: object, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum


def valid_action(value: object) -> bool:
    if not isinstance(value, dict) or set(value) - {"type", "payload", "handler", "loadingBehavior"}:
        return False
    if value.get("handler", "server") != "server" or value.get("loadingBehavior", "self") not in ("self", "container", "none"):
        return False
    payload: object = value.get("payload")
    if not isinstance(payload, dict):
        return False
    kind: object = value.get("type")
    if kind in ("cart.add", "cart.remove"):
        return set(payload) == {"id", "position"} and isinstance(payload["id"], str) and 0 < len(payload["id"]) <= 128 and bounded_integer(payload["position"], 100) and payload["position"] > 0
    if kind == "locale.set":
        return set(payload) == {"lang"} and payload["lang"] in ("en", "ar")
    if kind == "checkout.start":
        return not payload
    if kind in ("order.edit", "order.confirm"):
        return set(payload) == {"order_id"} and isinstance(payload["order_id"], str) and 0 < len(payload["order_id"]) <= 128
    return False


def prepare_presentation(source: dict[str, object], path: str) -> tuple[dict[str, object], dict[str, Appearance]]:
    """Translate supported Studio presentation data without evaluating template code or granting action authority."""
    node: dict[str, object] = dict(source)
    appearance: dict[str, object] = {}
    component: object = node.get("type")
    if component == "Icon" and node.get("name") in ("check-circle", "info", "warning"):
        name: str = str(node.pop("name"))
        node["type"] = "Text"
        node["value"] = {"check-circle": "✓", "info": "ⓘ", "warning": "⚠"}[name]
        component = "Text"
    if component in ("Card", "ListView"):
        if node.get("lang") in ("en", "ar"):
            appearance["locale"] = node.pop("lang")
        if node.get("theme") in ("dark", "light"):
            appearance["theme"] = node.pop("theme")
        if node.get("size") in ("sm", "md", "lg", "full"):
            appearance["size"] = node.pop("size")
        if component == "ListView" and bounded_integer(node.get("limit"), 100) and node["limit"] > 0:
            appearance["limit"] = node.pop("limit")
        for control in ("confirm", "cancel"):
            value: object = node.get(control)
            if isinstance(value, dict) and set(value) == {"label", "action"} and isinstance(value["label"], str) and 0 < len(value["label"]) <= 256 and valid_action(value["action"]):
                children: object = node.get("children")
                if isinstance(children, list):
                    node["children"] = [*children, {"type": "Button", "label": value["label"], "onClickAction": value["action"]}]
                    node.pop(control)
    if component == "Box" and "children" not in node:
        node["children"] = []
    if component in ("Row", "Col", "Box"):
        padding: object = node.get("padding")
        if isinstance(padding, dict) and set(padding) <= {"x", "y"} and padding and all(bounded_integer(value, 8) for value in padding.values()):
            appearance["paddingInline"] = int(padding.get("x", 0)) * 4
            appearance["paddingBlock"] = int(padding.get("y", 0)) * 4
            node.pop("padding")
        if component == "Box":
            if bounded_integer(node.get("size"), 256):
                appearance["width"] = appearance["height"] = node.pop("size")
            for prop in ("width", "height", "minWidth"):
                value = node.get(prop)
                if bounded_integer(value, 1024) or prop != "minWidth" and isinstance(value, str) and re.fullmatch(r"(?:100|[0-9]{1,2})%", value):
                    appearance[prop] = node.pop(prop)
            border: object = node.get("border")
            if isinstance(border, dict) and set(border) == {"size", "color"} and bounded_integer(border["size"], 8) and border["color"] in ("subtle", "default", "strong"):
                appearance["borderWidth"] = border["size"]
                appearance["borderColor"] = border["color"]
                node.pop("border")
    if component in ("Button", "Badge"):
        if node.get("size") in ("sm", "md", "lg"):
            appearance["size"] = node.pop("size")
        if component == "Button":
            if node.get("variant") in ("solid", "soft", "outline", "ghost"):
                appearance["variant"] = node.pop("variant")
            if node.get("style") in ("primary", "secondary"):
                appearance["primary"] = node.pop("style") == "primary"
            for prop in ("uniform", "block"):
                if isinstance(node.get(prop), bool):
                    appearance[prop] = node.pop(prop)
            if valid_action(node.get("onClickAction")):
                node.pop("onClickAction")
    if component == "Divider":
        if node.get("color") in ("subtle", "default", "strong"):
            appearance["color"] = node.pop("color")
        if isinstance(node.get("flush"), bool):
            appearance["flush"] = node.pop("flush")
    appearances: dict[str, Appearance] = {path: cast(Appearance, appearance)} if appearance else {}
    children = node.get("children")
    if isinstance(children, list):
        converted: list[object] = []
        for index, child in enumerate(children):
            if isinstance(child, dict):
                prepared, nested = prepare_presentation(child, f"{path}.children[{index}]")
                converted.append(prepared)
                appearances.update(nested)
            else:
                converted.append(child)
        node["children"] = converted
    return node, appearances


def attach_presentation(node: dict[str, object], appearances: dict[str, Appearance], path: str) -> dict[str, object]:
    result: dict[str, object] = dict(node)
    if path in appearances:
        result["appearance"] = appearances[path]
    children: object = node.get("children")
    if isinstance(children, list):
        result["children"] = [attach_presentation(child, appearances, f"{path}.children[{index}]") for index, child in enumerate(children)]
    if node.get("kind") == "table":
        result["rows"] = [{**row, "cells": [{**cell, "children": [attach_presentation(child, appearances, f"{path}.children[{row_index}].children[{cell_index}].children[{index}]") for index, child in enumerate(cell["children"])]} for cell_index, cell in enumerate(row["cells"])]} for row_index, row in enumerate(node["rows"])]
    return result
