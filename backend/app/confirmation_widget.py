import json
from typing import Literal

from app.cart import Cart
from app.validator import ContainerNode, validate_source


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
