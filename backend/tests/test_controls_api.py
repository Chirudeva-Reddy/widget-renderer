import unittest
from typing import Any

import test_chart_api


class ControlApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        test_chart_api.ChartApiTests.setUpClass()
        cls.port = test_chart_api.ChartApiTests.port

    @classmethod
    def tearDownClass(cls) -> None:
        test_chart_api.ChartApiTests.tearDownClass()

    def validate(self, component: dict[str, Any]) -> dict[str, Any]:
        return test_chart_api.ChartApiTests.validate(self, component)

    def test_form_controls_are_safe_preview_data(self) -> None:
        form = {"type": "Form", "children": [
            {"type": "Input", "name": "quantity", "inputType": "number", "defaultValue": "2", "required": True},
            {"type": "Select", "name": "portion", "options": [{"value": "small", "label": "Small"}, {"value": "large", "label": "Large", "disabled": True}], "defaultValue": "small"},
            {"type": "Button", "label": "Add", "onClickAction": {"type": "order.confirm"}},
        ]}
        result = self.validate(form)
        self.assertEqual(result["status"], "partial")
        node = result["preview"]["children"][1]
        self.assertEqual(node["kind"], "form")
        self.assertEqual([child["kind"] for child in node["children"]], ["input", "select", "button"])
        self.assertNotIn("onClickAction", node["children"][2])
        self.assertEqual(result["issues"][0]["code"], "unsupported_property")

    def test_invalid_controls_and_duplicate_form_fields(self) -> None:
        for control in (
            {"type": "Input", "name": "quantity", "inputType": "number", "defaultValue": "100"},
            {"type": "Select", "name": "portion", "options": [{"value": "a", "label": "A"}, {"value": "a", "label": "Again"}]},
        ):
            with self.subTest(control=control):
                result = self.validate(control)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(result["preview"]["children"][1]["kind"], "problem")
        field = {"type": "Input", "name": "quantity", "inputType": "number"}
        result = self.validate({"type": "Form", "children": [field, field]})
        self.assertEqual(result["preview"]["children"][1]["kind"], "problem")
        self.assertEqual(result["issues"][0]["code"], "duplicate_field_name")
        nested = self.validate({"type": "Form", "children": [field, {"type": "Box", "children": [field, {"type": "Spacer"}]}]})
        self.assertEqual(nested["preview"]["children"][1]["kind"], "problem")
        self.assertEqual(nested["issues"][0]["code"], "duplicate_field_name")


if __name__ == "__main__":
    unittest.main()
