import json
from typing import Literal

from app.menu import MenuResponse
from app.validator import ContainerNode, validate_source


def build_menu_widget(menu: MenuResponse, locale: Literal["en", "ar"]) -> ContainerNode:
    items: list[dict[str, object]] = []
    for item in menu["items"]:
        status: str = ("Available" if item["available"] else "Sold out") if locale == "en" else ("متوفر" if item["available"] else "نفد")
        price: str = f"AED {item['price_minor'] // 100}.{item['price_minor'] % 100:02d}"
        items.append({"type": "ListViewItem", "key": item["id"], "children": [
            {"type": "Row", "children": [
                {"type": "Box", "children": [{"type": "Title", "value": str(item["position"])}]},
                {"type": "Col", "children": [{"type": "Title", "value": item["name"][locale]}, {"type": "Caption", "value": price}]},
                {"type": "Spacer"},
            ]},
            {"type": "Badge", "label": status},
        ]})
    tree: dict[str, object] = {"type": "ListView", "children": items}
    result = validate_source(json.dumps(tree, ensure_ascii=False))
    if result["status"] != "valid" or result["preview"] is None:
        raise ValueError("The backend-built menu widget failed validation.")
    return result["preview"]
