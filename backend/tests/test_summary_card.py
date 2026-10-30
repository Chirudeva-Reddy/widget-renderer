import json
import unittest

from app.chat import ModelReply, SummaryCardStream, bind_summary_card


class SummaryCardTests(unittest.TestCase):
    def test_display_only_card_is_rendered(self) -> None:
        card = bind_summary_card(json.dumps({"type": "Card", "children": [{"type": "Title", "value": "Your cart"}, {"type": "Row", "children": [{"type": "Text", "value": "Hummus x2"}]}]}))
        self.assertEqual(card, {"kind": "card", "children": [{"kind": "title", "value": "Your cart"}, {"kind": "row", "children": [{"kind": "text", "value": "Hummus x2"}]}]})

    def test_interactive_or_invalid_cards_become_a_visible_problem(self) -> None:
        problem = {"kind": "card", "children": [{"kind": "problem", "message": "The assistant's summary could not be displayed."}]}
        nested_button = {"type": "Card", "children": [{"type": "Row", "children": [{"type": "Button", "label": "Order", "onClickAction": {"type": "order.confirm"}}]}]}
        for source in (json.dumps(nested_button), json.dumps({"type": "ListView", "children": []}), "{not json"):
            self.assertEqual(bind_summary_card(source), problem)

    def test_absent_card_renders_nothing_and_field_is_required(self) -> None:
        self.assertIsNone(bind_summary_card(None))
        self.assertIn("summary_card", ModelReply.model_json_schema()["required"])


    def test_stream_emits_only_complete_components_in_order(self) -> None:
        card = {"type": "Card", "children": [{"type": "Title", "value": "سلتك \"الحالية\" 🍽"}, {"type": "Button", "label": "Order"}, {"type": "Text", "value": "حمص x2\nAED 36.00"}]}
        reply = json.dumps({"text": "إليك \"ملخص\"", "suggestion": None, "show_menu": False, "summary_card": json.dumps(card, ensure_ascii=False)}, ensure_ascii=False)
        events: list[tuple[str, object, int]] = []
        stream = SummaryCardStream(lambda event, data: events.append((event, data, len(prefix))))
        for end in range(len(reply) + 1):
            prefix = reply[:end]
            stream.feed(prefix)
        self.assertEqual([(event, data) for event, data, _ in events], [
            ("card", {"text": "إليك \"ملخص\""}),
            ("component", {"index": 0, "node": {"kind": "title", "value": "سلتك \"الحالية\" 🍽"}}),
            ("component", {"index": 2, "node": {"kind": "text", "value": "حمص x2\nAED 36.00"}}),
        ])
        self.assertLess(events[1][2], len(reply) - 10)


if __name__ == "__main__":
    unittest.main()
