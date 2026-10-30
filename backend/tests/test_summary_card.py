import json
import unittest

from app.chat import ModelReply, ProviderError, bind_summary_card, model_schema, reconcile_price_bindings
from pydantic import ValidationError
from app.widget_actions import WidgetActionError, bind_generic_actions
from app.generic_views import validate_draft_identities
from app.validator import validate_source


class SummaryCardTests(unittest.TestCase):
    def test_display_only_card_is_rendered(self) -> None:
        card = bind_summary_card(json.dumps({"type": "Card", "children": [{"type": "Title", "value": "Your cart"}, {"type": "Row", "children": [{"type": "Text", "value": "Hummus x2"}]}]}))
        self.assertEqual(card, {"kind": "card", "children": [{"kind": "title", "value": "Your cart"}, {"kind": "row", "children": [{"kind": "text", "value": "Hummus x2"}]}]})

    def test_chatkit_style_tokens_are_kept_and_raw_styles_dropped(self) -> None:
        card = bind_summary_card(json.dumps({"type": "Card", "children": [
            {"type": "Text", "value": "Tabbouleh", "color": "tertiary", "size": "sm", "lineThrough": True},
            {"type": "Badge", "label": "Sold out", "color": "danger", "variant": "solid"},
            {"type": "Box", "background": "surface-secondary", "radius": "md", "children": [{"type": "Title", "value": "AED 56.00", "size": "lg", "color": "#ff0000"}]},
            {"type": "Text", "value": "x", "italic": 1, "background": "red"},
        ]}))
        self.assertEqual(card, {"kind": "card", "children": [
            {"kind": "text", "value": "Tabbouleh", "color": "tertiary", "size": "sm", "lineThrough": True},
            {"kind": "badge", "label": "Sold out", "color": "danger", "variant": "solid"},
            {"kind": "box", "children": [{"kind": "title", "value": "AED 56.00", "size": "lg"}], "background": "surface-secondary", "radius": "md"},
            {"kind": "text", "value": "x"},
        ]})

    def test_interactive_or_invalid_cards_become_a_visible_problem(self) -> None:
        problem = {"kind": "card", "children": [{"kind": "problem", "message": "The assistant's summary could not be displayed."}]}
        nested_button = {"type": "Card", "children": [{"type": "Row", "children": [{"type": "Button", "label": "Order", "onClickAction": {"type": "order.confirm"}}]}]}
        for source in (json.dumps(nested_button), json.dumps({"type": "ListView", "children": []}), "{not json"):
            self.assertEqual(bind_summary_card(source), problem)

    def test_absent_card_renders_nothing_and_field_is_required(self) -> None:
        self.assertIsNone(bind_summary_card(None))
        self.assertEqual(set(ModelReply.model_json_schema()["required"]), {"text", "intents", "widgets"})

    def test_structured_model_intents_have_strict_payloads(self) -> None:
        reply = ModelReply.model_validate({"text": None, "intents": [{"type": "menu.show", "payload": {}}, {"type": "cart.set_quantity", "payload": {"id": "hummus", "quantity": 2}}], "widgets": []})
        self.assertEqual(reply.intents[1].payload.quantity, 2)
        self.assertEqual(set(model_schema()["required"]), {"text", "intents", "widgets"})
        self.assertEqual(model_schema()["properties"]["widgets"]["items"]["properties"]["target_role"]["enum"], ["summary", "diagnostic"])
        for intent in ({"type": "order.confirm", "payload": {}}, {"type": "cart.set_quantity", "payload": {"id": "hummus", "quantity": -1}}, {"type": "menu.show", "payload": {"extra": True}}):
            with self.subTest(intent=intent), self.assertRaises(ValidationError):
                ModelReply.model_validate({"text": "x", "intents": [intent], "widgets": []})

    def test_price_binding_uses_authoritative_price_and_rejects_ambiguity(self) -> None:
        menu = {"revision": 1, "items": [{"id": "hummus", "position": 1, "name": {"en": "Hummus", "ar": "حمص"}, "price_minor": 1850, "currency": "AED", "available": True}]}
        tree = {"type": "Card", "children": [{"type": "Text", "key": "price:hummus", "value": "AED 1.00"}]}
        result, warnings = reconcile_price_bindings(tree, menu)
        self.assertEqual(result["children"][0]["value"], "AED 18.50")
        self.assertEqual(tree["children"][0]["value"], "AED 1.00")
        self.assertEqual(warnings, ["price_reconciled"])
        for children in ([{"type": "Text", "key": "price:unknown", "value": "1"}], [tree["children"][0], tree["children"][0]]):
            with self.subTest(children=children), self.assertRaises(ProviderError):
                reconcile_price_bindings({"type": "Card", "children": children}, menu)

    def test_generic_button_binding_uses_authoritative_action_and_label(self) -> None:
        menu = {"revision": 1, "items": [{"id": "hummus", "position": 1, "name": {"en": "Hummus", "ar": "حمص"}, "price_minor": 1850, "currency": "AED", "available": True}]}
        cart = {"items": [], "total_minor": 0, "currency": "AED", "can_checkout": False, "revision": "a" * 64}
        button = {"type": "Button", "key": "action:cart.add:hummus", "label": "Ignore this model label"}
        binding = bind_generic_actions({"type": "Card", "children": [button]}, menu, cart, "en")
        self.assertEqual(binding, [{"key": "action:cart.add:hummus", "type": "cart.add", "item_id": "hummus", "position": 1, "enabled": True, "label": "Add Hummus"}])
        form = {"type": "Form", "key": "action:cart.set_quantity:hummus", "children": [{"type": "Input", "name": "quantity", "inputType": "number", "defaultValue": "2"}, {"type": "Button", "label": "Apply"}]}
        self.assertEqual(bind_generic_actions({"type": "Card", "children": [form]}, menu, cart, "en")[0]["quantities"], list(range(100)))
        validate_draft_identities(validate_source(json.dumps({"type": "Card", "children": [form]}))["preview"])
        with self.assertRaises(WidgetActionError):
            validate_draft_identities(validate_source(json.dumps({"type": "Card", "children": [{**form, "key": None}]}))["preview"])

        select = {"type": "Select", "key": "action:cart.set_quantity:hummus", "name": "quantity", "options": [{"value": "0", "label": "Remove"}, {"value": "2", "label": "Two", "disabled": True}]}
        self.assertEqual(bind_generic_actions({"type": "Card", "children": [select]}, menu, cart, "en")[0]["quantities"], [0])
        with self.assertRaises(WidgetActionError):
            bind_generic_actions({"type": "Card", "children": [{**select, "options": [{"value": "2.5", "label": "Invalid"}]}]}, menu, cart, "en")
        for children in ([button, button], [{**button, "key": "action:order.confirm:hummus"}], [{**button, "key": "action:cart.add:unknown"}]):
            with self.subTest(children=children), self.assertRaises(WidgetActionError):
                bind_generic_actions({"type": "Card", "children": children}, menu, cart, "en")




if __name__ == "__main__":
    unittest.main()
