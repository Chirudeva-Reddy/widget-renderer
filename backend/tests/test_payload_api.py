import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


class PayloadApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        database: str = str(Path(cls.directory.name) / "test.sqlite")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]
        cls.server = subprocess.Popen(
            [sys.executable, "-c", "from pathlib import Path; import sys; import uvicorn; import app.main; app.main.DATABASE_PATH = Path(sys.argv[1]); uvicorn.run(app.main.app, host='127.0.0.1', port=int(sys.argv[2]), log_level='warning')", database, str(cls.port)],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        for attempt in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError(f"Test server exited: {cls.server.stderr.read().decode()}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/api/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except urllib.error.URLError:
                time.sleep(0.05)
        cls.server.terminate()
        raise RuntimeError(f"Test server did not start on port {cls.port}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        cls.server.communicate(timeout=5)
        cls.directory.cleanup()

    def request(self, body: bytes, content_type: str) -> tuple[int, dict[str, Any]]:
        request: urllib.request.Request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/payloads/validate", data=body,
            headers={"Content-Type": content_type}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def validate(self, source: str) -> tuple[int, dict[str, Any]]:
        return self.request(json.dumps({"source": source}).encode(), "application/json")

    def restaurant_request(self, endpoint: str, payload: dict[str, Any], cookie: str, action: str) -> tuple[int, dict[str, Any], str]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/{endpoint}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Origin": "http://localhost:5173", "X-Demo-Action": action, "Cookie": cookie}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response), response.headers.get("Set-Cookie", "").split(";", 1)[0]
        except urllib.error.HTTPError as error:
            return error.code, json.load(error), ""

    def widget(self, locale: str, cookie: str) -> dict[str, Any]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/widgets/menu/{locale}", headers={"Cookie": cookie})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    def rendered_menu(self, widget: dict[str, Any]) -> dict[str, Any]:
        quantities = {item["id"]: item["quantity"] for item in widget["cart"]["items"]}
        rows = []
        for item in widget["menu"]["items"]:
            quantity = quantities.get(item["id"], 0)
            rows.append({"item_id": item["id"], "position": item["position"], "sold_out": not item["available"], "placeholder": False, "quantity": str(quantity), "draft": False, "edit_revision": None, "changed_revision": None, "disabled": False, "controls": {"input": False, "decrease": quantity == 0, "increase": not item["available"] or quantity == 99, "apply": True, "remove": quantity == 0}, "issues": [] if item["available"] else ["sold_out"]})
        return {"locale": widget["locale"], "rows": rows, "checkout_disabled": not widget["cart"]["items"]}

    def test_widget_revisions_are_owned_immutable_and_acknowledged(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other_cookie = self.restaurant_request("session", {}, "", "session")
        first = self.widget("en", cookie)
        self.assertEqual(first, self.widget("en", cookie))
        self.assertNotEqual(first["widget_id"], self.widget("ar", cookie)["widget_id"])
        self.assertNotEqual(first["widget_id"], self.widget("en", other_cookie)["widget_id"])
        endpoint = f"widgets/{first['widget_id']}/rendered"
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1, "rendered": self.rendered_menu(first)}, other_cookie, "widget-rendered")[0], 409)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1, "rendered": self.rendered_menu(first)}, cookie, "widget-rendered")[1], first)
        status, _, _ = self.restaurant_request("cart/quantity", {"action_id": "widget-test", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")
        self.assertEqual(status, 200)
        second = self.widget("en", cookie)
        self.assertEqual(second["widget_id"], first["widget_id"])
        self.assertEqual(second["revision"], first["revision"] + 1)
        self.assertEqual(first["cart"]["items"], [])
        self.assertEqual(second["cart"]["items"][0]["quantity"], 1)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": second["revision"], "rendered": self.rendered_menu(second)}, cookie, "widget-rendered")[1], second)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1, "rendered": self.rendered_menu(first)}, cookie, "widget-rendered")[1], first)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 999, "rendered": self.rendered_menu(first)}, cookie, "widget-rendered")[0], 409)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1}, cookie, "widget-rendered")[0], 422)
        with sqlite3.connect(Path(self.directory.name) / "test.sqlite") as connection:
            stored = connection.execute("SELECT envelope_json FROM widget_revisions WHERE widget_id = ? AND revision = 1", (first["widget_id"],)).fetchone()
            acknowledged = connection.execute("SELECT revision FROM widget_acknowledgements WHERE widget_id = ?", (first["widget_id"],)).fetchone()
        self.assertEqual(acknowledged[0], second["revision"])
        self.assertEqual(json.loads(stored[0]), first)

    def test_rendered_view_and_locale_action_are_scoped(self) -> None:
        _, _, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other = self.restaurant_request("session", {}, "", "session")
        widget = self.widget("en", cookie)
        rendered = self.rendered_menu(widget)
        endpoint = f"widgets/{widget['widget_id']}/rendered"
        self.assertEqual(self.restaurant_request(endpoint, {"revision": widget["revision"], "rendered": rendered}, cookie, "widget-rendered")[0], 200)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": widget["revision"], "rendered": rendered}, other, "widget-rendered")[0], 409)
        forged = {**rendered, "rows": [{**rendered["rows"][0], "position": 999}, *rendered["rows"][1:]]}
        self.assertEqual(self.restaurant_request(endpoint, {"revision": widget["revision"], "rendered": forged}, cookie, "widget-rendered")[0], 409)
        forged_control = {**rendered, "rows": [{**rendered["rows"][0], "controls": {**rendered["rows"][0]["controls"], "remove": False}}, *rendered["rows"][1:]]}
        self.assertEqual(self.restaurant_request(endpoint, {"revision": widget["revision"], "rendered": forged_control}, cookie, "widget-rendered")[0], 409)
        forged_revision = {**rendered, "rows": [{**rendered["rows"][0], "draft": True, "edit_revision": "0" * 64}, *rendered["rows"][1:]]}
        self.assertEqual(self.restaurant_request(endpoint, {"revision": widget["revision"], "rendered": forged_revision}, cookie, "widget-rendered")[0], 409)
        action = {"widget_id": widget["widget_id"], "revision": widget["revision"], "action_id": "locale-action", "type": "locale.set", "payload": {"lang": "ar"}}
        self.assertEqual(self.restaurant_request("actions", action, other, "widget-action")[0], 409)
        self.assertEqual(self.restaurant_request("actions", action, cookie, "widget-action")[1], {"lang": "ar"})
        self.assertEqual(self.restaurant_request("actions", action, cookie, "widget-action")[1], {"lang": "ar"})
        self.assertEqual(self.restaurant_request("actions", {**action, "payload": {"lang": "en"}}, cookie, "widget-action")[0], 409)
        self.assertEqual([entry["type"] for entry in self.action_context(cookie)["completed_actions"]], ["locale.set"])

    def test_chat_rejects_foreign_and_mismatched_widget_references(self) -> None:
        _, _, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other = self.restaurant_request("session", {}, "", "session")
        widget = self.widget("en", cookie)
        reference = {"widget_id": widget["widget_id"], "revision": widget["revision"], "rendered": self.rendered_menu(widget)}
        request = {"client_message_id": "widget-chat", "text": "Show the second item", "menu_revision": widget["menu"]["revision"], "locale": "en", "rendered_view_id": widget["menu_view_id"], "widget_view": reference}
        self.assertEqual(self.restaurant_request("chat", request, other, "chat")[0], 409)
        self.assertEqual(self.restaurant_request("chat", {**request, "widget_view": {**reference, "revision": 999}}, cookie, "chat")[0], 409)
        self.assertEqual(self.restaurant_request("chat", {**request, "rendered_view_id": None}, cookie, "chat")[0], 409)
        self.assertEqual(self.restaurant_request("chat", {**request, "locale": "ar"}, cookie, "chat")[0], 409)

    def test_widget_action_ownership_binding_staleness_and_retry(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other = self.restaurant_request("session", {}, "", "session")
        widget = self.widget("en", cookie)
        action = {"widget_id": widget["widget_id"], "revision": widget["revision"], "action_id": "widget-action", "type": "cart.set_quantity", "payload": {"item_id": "hummus", "position": 1, "quantity": 1, "cart_revision": cart["revision"]}}
        self.assertEqual(self.restaurant_request("actions", action, other, "widget-action")[0], 409)
        self.assertEqual(self.restaurant_request("actions", {**action, "payload": {**action["payload"], "position": 2}}, cookie, "widget-action")[0], 409)
        status, result, _ = self.restaurant_request("actions", action, cookie, "widget-action")
        self.assertEqual(status, 200)
        self.assertEqual(result["items"][0]["quantity"], 1)
        self.assertEqual(self.restaurant_request("actions", action, cookie, "widget-action")[1], result)
        self.assertEqual(self.restaurant_request("actions", {**action, "payload": {**action["payload"], "quantity": 2}}, cookie, "widget-action")[0], 409)
        self.assertEqual(self.restaurant_request("cart/quantity", {"action_id": "widget-action", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")[0], 409)
        self.assertEqual(self.restaurant_request("actions", {**action, "action_id": "stale"}, cookie, "widget-action")[0], 409)
        fresh = self.widget("en", cookie)
        updated = {**action, "widget_id": fresh["widget_id"], "revision": fresh["revision"], "action_id": "second", "payload": {**action["payload"], "quantity": 2, "cart_revision": fresh["cart_revision"]}}
        self.assertEqual(self.restaurant_request("actions", updated, cookie, "widget-action")[1]["items"][0]["quantity"], 2)
        self.assertEqual(len(self.action_context(cookie)["completed_actions"]), 2)

    def test_widget_add_remove_are_scoped_and_idempotent(self) -> None:
        _, _, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other = self.restaurant_request("session", {}, "", "session")
        widget = self.widget("en", cookie)
        add = {"widget_id": widget["widget_id"], "revision": widget["revision"], "action_id": "add-action", "type": "cart.add", "payload": {"id": "hummus", "position": 1}}
        self.assertEqual(self.restaurant_request("actions", {**add, "type": "cart.remove"}, cookie, "widget-action")[0], 409)
        self.assertEqual(self.restaurant_request("actions", add, other, "widget-action")[0], 409)
        self.assertEqual(self.restaurant_request("actions", {**add, "payload": {"id": "hummus", "position": 2}}, cookie, "widget-action")[0], 409)
        status, cart, _ = self.restaurant_request("actions", add, cookie, "widget-action")
        self.assertEqual((status, cart["items"][0]["quantity"]), (200, 1))
        self.assertEqual(self.restaurant_request("actions", add, cookie, "widget-action")[1], cart)
        self.assertEqual(self.restaurant_request("actions", {**add, "type": "cart.remove"}, cookie, "widget-action")[0], 409)
        widget = self.widget("en", cookie)
        remove = {**add, "widget_id": widget["widget_id"], "revision": widget["revision"], "action_id": "remove-action", "type": "cart.remove"}
        self.assertEqual(self.restaurant_request("actions", remove, cookie, "widget-action")[1]["items"], [])
        actions = self.action_context(cookie)["completed_actions"]
        self.assertEqual([action["type"] for action in actions], ["cart.add", "cart.remove"])
        self.assertEqual((actions[-1]["widget_id"], actions[-1]["revision"], actions[-1]["position"]), (widget["widget_id"], widget["revision"], 1))

    def test_generic_drafts_are_acknowledged_owned_and_revision_bound(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other = self.restaurant_request("session", {}, "", "session")
        widget = self.widget("en", cookie)
        tree = {"type": "Card", "children": [{"type": "Form", "key": "draft-form", "children": [{"type": "Input", "name": "quantity", "inputType": "number", "defaultValue": "2"}, {"type": "Select", "name": "portion", "defaultValue": "one", "options": [{"value": "one", "label": "One"}, {"value": "two", "label": "Two", "disabled": True}]}]}]}
        generic = {"widget_id": "draft-widget", "revision": 1, "menu_revision": widget["menu"]["revision"], "cart_revision": cart["revision"], "bindings": []}
        program = """import json, sys
from pathlib import Path
from app.chat import begin_turn, finish_turn
path, token, widget, tree = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3]), json.loads(sys.argv[4])
begin_turn(path, token, sys.argv[5], 'draft fixture', widget['menu_revision'], 'en', None, None, None)
finish_turn(path, token, sys.argv[5], {'widget_controls': [widget], 'suggestion': None, 'messages': [{'widget_id': widget['widget_id'], 'payload': tree}]}, 0)
"""
        arguments: list[str] = [sys.executable, "-c", program, str(Path(self.directory.name) / "test.sqlite"), cookie.split("=", 1)[1], json.dumps(generic), json.dumps(tree), "draft-issue"]
        subprocess.run(arguments, cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
        reference = {"widget_id": generic["widget_id"], "revision": 1, "rendered": {"locale": "en", "fields": [{"index": 0, "name": "quantity", "value": "", "disabled": False, "unavailable": False}, {"index": 1, "name": "portion", "value": "two", "disabled": False, "unavailable": True}]}}
        endpoint: str = "widgets/draft-widget/generic-rendered"
        self.assertEqual(self.restaurant_request(endpoint, reference, other, "widget-rendered")[0], 409)
        self.assertEqual(self.restaurant_request(endpoint, reference, cookie, "widget-rendered")[:2], (200, reference))
        self.assertEqual(self.restaurant_request(endpoint, {**reference, "revision": 2}, cookie, "widget-rendered")[0], 409)
        fields = reference["rendered"]["fields"]
        forged = {**reference, "rendered": {"locale": "en", "fields": [{**fields[0], "name": "forged"}, fields[1]]}}
        self.assertEqual(self.restaurant_request(endpoint, forged, cookie, "widget-rendered")[0], 409)
        with sqlite3.connect(Path(self.directory.name) / "test.sqlite") as connection:
            stored = json.loads(connection.execute("SELECT rendered_json FROM generic_widgets WHERE id = 'draft-widget'").fetchone()[0])
        self.assertEqual(stored, reference["rendered"])
        self.assertEqual(self.restaurant_request("widgets/generic-state", {"widget_ids": [generic["widget_id"]]}, other, "widget-rendered")[0], 409)
        status, state, _ = self.restaurant_request("widgets/generic-state", {"widget_ids": [generic["widget_id"]]}, cookie, "widget-rendered")
        self.assertEqual(self.restaurant_request("widgets/generic-state", {"widget_ids": ["\ud800"]}, cookie, "widget-rendered")[0], 422)
        self.assertEqual(status, 200)
        self.assertEqual(state[0]["widget"]["revision"], 1)
        self.assertEqual(state[0]["payload"], tree)
        bad_turn = {"client_message_id": "unacknowledged-generic", "text": "What is my draft?", "menu_revision": widget["menu"]["revision"], "locale": "en", "rendered_view_id": None, "generic_views": [{**reference, "rendered": {**reference["rendered"], "fields": [{**fields[0], "value": "99"}, fields[1]]}}]}
        self.assertEqual(self.restaurant_request("chat", bad_turn, cookie, "chat")[0], 409)

        generic["revision"] = 2
        arguments[5] = json.dumps(generic)
        arguments[-1] = "draft-update"
        subprocess.run(arguments, cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
        with sqlite3.connect(Path(self.directory.name) / "test.sqlite") as connection:
            self.assertIsNone(connection.execute("SELECT rendered_json FROM generic_widgets WHERE id = 'draft-widget'").fetchone()[0])
        self.assertEqual(self.restaurant_request(endpoint, reference, cookie, "widget-rendered")[0], 409)
        reference["revision"] = 2
        self.assertEqual(self.restaurant_request(endpoint, reference, cookie, "widget-rendered")[0], 200)

    def test_studio_reference_fixtures_are_valid_runtime_previews(self) -> None:
        directory: Path = Path(__file__).resolve().parents[2] / "fixtures" / "studio"
        for fixture in directory.glob("*.json"):
            with self.subTest(fixture=fixture.name):
                status, result = self.validate(fixture.read_text())
                self.assertEqual((status, result["status"], result["issues"]), (200, "valid", []))
        unsafe = {"type": "Card", "children": [{"type": "Box", "width": "url(https://example.com)", "children": []}]}
        self.assertEqual(self.validate(json.dumps(unsafe))[1]["status"], "partial")

    def test_generic_widget_actions_are_owned_bound_and_idempotent(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other = self.restaurant_request("session", {}, "", "session")
        widget = self.widget("en", cookie)
        generic = {"widget_id": "generic-test-widget", "revision": 1, "menu_revision": widget["menu"]["revision"], "cart_revision": cart["revision"], "bindings": [{"key": "action:cart.add:hummus", "type": "cart.add", "item_id": "hummus", "position": 1, "enabled": True, "label": "Add Hummus"}]}
        program = """import json, sys
from pathlib import Path
from app.chat import begin_turn, finish_turn
path, token, widget = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
begin_turn(path, token, sys.argv[4], 'show actions', widget['menu_revision'], 'en', None, None, None)
finish_turn(path, token, sys.argv[4], {'widget_controls': [widget], 'suggestion': None, 'messages': [{'widget_id': widget['widget_id'], 'payload': {'type': 'Card', 'children': []}}]}, 0)
"""
        subprocess.run([sys.executable, "-c", program, str(Path(self.directory.name) / "test.sqlite"), cookie.split("=", 1)[1], json.dumps(generic), "generic-issue"], cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
        action = {"widget_id": generic["widget_id"], "revision": 1, "action_id": "generic-add", "type": "cart.add", "payload": {"id": "hummus", "position": 1}}
        self.assertEqual(self.restaurant_request("actions", action, other, "widget-action")[0], 409)
        self.assertEqual(self.restaurant_request("actions", {**action, "type": "cart.remove"}, cookie, "widget-action")[0], 409)
        self.assertEqual(self.restaurant_request("actions", {**action, "payload": {"id": "falafel", "position": 2}}, cookie, "widget-action")[0], 409)
        status, result, _ = self.restaurant_request("actions", action, cookie, "widget-action")
        self.assertEqual((status, result["items"][0]["quantity"]), (200, 1))
        self.assertEqual(self.restaurant_request("actions", action, cookie, "widget-action")[1], result)
        self.assertEqual(self.restaurant_request("actions", {**action, "action_id": "generic-stale"}, cookie, "widget-action")[0], 409)
        self.assertEqual(self.restaurant_request("actions", {**action, "type": "cart.remove"}, cookie, "widget-action")[0], 409)
        event = self.action_context(cookie)["completed_actions"][-1]
        self.assertEqual((event["type"], event["widget_id"], event["position"]), ("cart.add", generic["widget_id"], 1))
        remove_widget = {**generic, "widget_id": "generic-remove-widget", "cart_revision": result["revision"], "bindings": [{"key": "action:cart.remove:hummus", "type": "cart.remove", "item_id": "hummus", "position": 1, "enabled": True, "label": "Remove Hummus"}]}
        subprocess.run([sys.executable, "-c", program, str(Path(self.directory.name) / "test.sqlite"), cookie.split("=", 1)[1], json.dumps(remove_widget), "generic-remove-issue"], cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
        remove = {**action, "widget_id": remove_widget["widget_id"], "action_id": "generic-remove", "type": "cart.remove"}
        removed = self.restaurant_request("actions", remove, cookie, "widget-action")[1]
        self.assertEqual(removed["items"], [])
        self.assertEqual(self.restaurant_request("actions", remove, cookie, "widget-action")[1], removed)
        _, fresh_cart, third = self.restaurant_request("session", {}, "", "session")
        fresh_widget = self.widget("en", third)
        concurrent_widget = {**generic, "widget_id": "generic-concurrent", "menu_revision": fresh_widget["menu"]["revision"], "cart_revision": fresh_cart["revision"]}
        subprocess.run([sys.executable, "-c", program, str(Path(self.directory.name) / "test.sqlite"), third.split("=", 1)[1], json.dumps(concurrent_widget), "generic-concurrent-issue"], cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
        attempts = [{**action, "widget_id": concurrent_widget["widget_id"], "action_id": action_id} for action_id in ("generic-concurrent-a", "generic-concurrent-b")]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda item: self.restaurant_request("actions", item, third, "widget-action"), attempts))
        self.assertEqual(sorted(result[0] for result in results), [200, 409])

    def test_widget_checkout_confirmation_and_retries(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other = self.restaurant_request("session", {}, "", "session")
        _, cart, _ = self.restaurant_request("cart/quantity", {"action_id": "checkout-add", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")
        widget = self.widget("en", cookie)
        start = {"widget_id": widget["widget_id"], "revision": widget["revision"], "action_id": "start-checkout", "type": "checkout.start", "payload": {"cart_revision": cart["revision"]}}
        self.assertEqual(self.restaurant_request("actions", start, other, "widget-action")[0], 409)
        status, view, _ = self.restaurant_request("actions", start, cookie, "widget-action")
        self.assertEqual((status, view["cart"]), (200, cart))
        self.assertEqual((view["kind"], view["role"], view["cart_revision"]), ("widget", "confirmation", cart["revision"]))
        self.assertEqual(set(view["payload"]), {"en", "ar"})
        for locale, name_field in (("en", "name_en"), ("ar", "name_ar")):
            card = view["payload"][locale]
            self.assertEqual(card["kind"], "card")
            self.assertEqual(card["children"][1]["key"], cart["items"][0]["id"])
            self.assertEqual(card["children"][1]["children"][0]["value"], cart["items"][0][name_field])
            self.assertIn("AED", card["children"][-1]["value"])
        self.assertEqual(self.restaurant_request("actions", start, cookie, "widget-action")[1], view)
        confirm = {"widget_id": view["widget_id"], "revision": view["revision"], "action_id": "confirm-checkout", "type": "order.confirm", "payload": {"cart_revision": cart["revision"]}}
        self.assertEqual(self.restaurant_request("actions", confirm, other, "widget-action")[0], 409)
        attempts = [confirm, {**confirm, "action_id": "another-confirm"}]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda item: self.restaurant_request("actions", item, cookie, "widget-action"), attempts))
        self.assertEqual(sorted(result[0] for result in results), [200, 409])
        winner = next(index for index, result in enumerate(results) if result[0] == 200)
        order = results[winner][1]
        self.assertEqual(self.restaurant_request("actions", attempts[winner], cookie, "widget-action")[1], order)
        self.assertEqual(self.restaurant_request("actions", {**attempts[winner], "payload": {"cart_revision": "0" * 64}}, cookie, "widget-action")[0], 409)
        self.assertEqual(len([action for action in self.action_context(cookie)["completed_actions"] if action["type"] == "order.confirm"]), 1)
        confirmation_action = self.action_context(cookie)["completed_actions"][-1]
        self.assertEqual((confirmation_action["widget_id"], confirmation_action["revision"]), (view["widget_id"], view["revision"]))
        _, new_cart, _ = self.restaurant_request("cart/quantity", {"action_id": "checkout-add-again", "item_id": "hummus", "quantity": 1, "cart_revision": self.snapshot(cookie)["cart"]["revision"]}, cookie, "cart")
        self.assertEqual(new_cart["revision"], cart["revision"])
        self.assertEqual(self.restaurant_request("actions", {**confirm, "action_id": "replay-old-review"}, cookie, "widget-action")[0], 409)

    def confirmation_context(self, cookie: str, view: dict[str, Any], locale: str) -> dict[str, Any]:
        reference = {"widget_id": view["widget_id"], "revision": view["revision"]}
        result = subprocess.run(
            [sys.executable, "-c", "import json; import sys; from pathlib import Path; from app.chat import read_action_context; print(json.dumps(read_action_context(Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3]), sys.argv[4])['displayed_confirmation']))", str(Path(self.directory.name) / "test.sqlite"), cookie.split("=", 1)[1], json.dumps(reference), locale],
            cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True,
        )
        return json.loads(result.stdout)

    def test_confirmation_bindings_acknowledgements_and_chat_context(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other = self.restaurant_request("session", {}, "", "session")
        empty = self.widget("en", cookie)
        self.assertFalse(empty["actions"]["checkout"])
        _, cart, _ = self.restaurant_request("cart/quantity", {"action_id": "context-add", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")
        menu = self.widget("en", cookie)
        self.assertTrue(menu["actions"]["checkout"])
        self.assertEqual(menu["actions"]["quantities"][0], {"item_id": "hummus", "position": 1, "minimum": 0, "maximum": 99})
        _, view, _ = self.restaurant_request("actions", {"widget_id": menu["widget_id"], "revision": menu["revision"], "action_id": "context-review", "type": "checkout.start", "payload": {"cart_revision": cart["revision"]}}, cookie, "widget-action")
        self.assertEqual(view["actions"], [{"type": "order.edit", "enabled": True}, {"type": "order.confirm", "enabled": True}])
        context = self.confirmation_context(cookie, view, "en")
        self.assertEqual(context, {"widget": view, "active": True, "acknowledged": False, "locale": "en"})
        endpoint = f"widgets/{view['widget_id']}/confirmation-rendered"
        rendered = {"locale": "en", "rows": [{"item_id": item["id"], "quantity": item["quantity"], "sold_out": not item["available"]} for item in view["cart"]["items"]], "edit_disabled": False, "confirm_disabled": False, "issues": []}
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1, "locale": "en", "rendered": rendered}, other, "widget-rendered")[0], 409)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1, "locale": "en", "rendered": {**rendered, "rows": [{**rendered["rows"][0], "quantity": 99}]}}, cookie, "widget-rendered")[0], 409)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1, "locale": "en", "rendered": rendered}, cookie, "widget-rendered")[0], 200)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1, "locale": "en", "rendered": {**rendered, "issues": ["stale"]}}, cookie, "widget-rendered")[0], 409)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1, "locale": "en", "rendered": rendered}, other, "widget-rendered")[0], 409)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 2, "locale": "en", "rendered": rendered}, cookie, "widget-rendered")[0], 409)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1, "locale": "xx"}, cookie, "widget-rendered")[0], 422)
        for locale in ("en", "en", "ar"):
            self.assertEqual(self.restaurant_request(endpoint, {"revision": 1, "locale": locale, "rendered": {**rendered, "locale": locale}}, cookie, "widget-rendered")[1], view)
        self.assertTrue(self.confirmation_context(cookie, view, "en")["acknowledged"])
        self.assertTrue(self.confirmation_context(cookie, view, "ar")["acknowledged"])
        reference = {"widget_id": view["widget_id"], "revision": view["revision"]}
        program = """import json, sys
from pathlib import Path
from app.chat import begin_turn, ChatError
path, token, reference = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
begin_turn(path, token, 'bound-confirmation', 'Review this', int(sys.argv[4]), 'en', None, None, reference)
try:
    begin_turn(path, token, 'bound-confirmation', 'Review this', int(sys.argv[4]), 'en', None, None, None)
except ChatError as error:
    assert 'different request' in str(error), str(error)
else:
    raise AssertionError('Message ID accepted a different confirmation reference')
"""
        subprocess.run([sys.executable, "-c", program, str(Path(self.directory.name) / "test.sqlite"), cookie.split("=", 1)[1], json.dumps(reference), str(menu["menu"]["revision"])], cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
        with sqlite3.connect(Path(self.directory.name) / "test.sqlite") as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM confirmation_acknowledgements WHERE widget_id = ?", (view["widget_id"],)).fetchone()[0], 2)
        foreign_request = {"text": "What am I reviewing?", "client_message_id": "foreign-confirmation", "menu_revision": menu["menu"]["revision"], "locale": "en", "rendered_view_id": None, "confirmation_view": {"widget_id": view["widget_id"], "revision": 1, "rendered": rendered}}
        for endpoint in ("chat", "chat/stream"):
            self.assertEqual(self.restaurant_request(endpoint, foreign_request, other, "chat")[0], 409)
            self.assertEqual(self.restaurant_request(endpoint, {**foreign_request, "confirmation_view": {"widget_id": view["widget_id"], "revision": 2, "rendered": rendered}}, cookie, "chat")[0], 409)
        self.assertEqual(self.restaurant_request("cart/quantity", {"action_id": "context-change", "item_id": "hummus", "quantity": 2, "cart_revision": cart["revision"]}, cookie, "cart")[0], 200)
        stale = self.confirmation_context(cookie, view, "ar")
        self.assertFalse(stale["active"])
        self.assertEqual(stale["widget"], view)

    def test_widget_checkout_blocks_sold_out_item(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        _, cart, _ = self.restaurant_request("cart/quantity", {"action_id": "stock-add", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")
        widget = self.widget("en", cookie)
        start = {"widget_id": widget["widget_id"], "revision": widget["revision"], "action_id": "stock-start", "type": "checkout.start", "payload": {"cart_revision": cart["revision"]}}
        _, view, _ = self.restaurant_request("actions", start, cookie, "widget-action")
        self.assertEqual(self.restaurant_request("demo/menu/hummus/sell-out", {}, cookie, "sell-out")[0], 200)
        try:
            confirm = {"widget_id": view["widget_id"], "revision": 1, "action_id": "stock-confirm", "type": "order.confirm", "payload": {"cart_revision": cart["revision"]}}
            self.assertEqual(self.restaurant_request("actions", confirm, cookie, "widget-action")[0], 409)
            self.assertFalse(self.snapshot(cookie)["cart"]["can_checkout"])
            current = self.snapshot(cookie)
            current_widget = current["widgets"]["en"]
            status, blocked, _ = self.restaurant_request("actions", {**start, "widget_id": current_widget["widget_id"], "revision": current_widget["revision"], "action_id": "stock-review-updated", "payload": {"cart_revision": current["cart"]["revision"]}}, cookie, "widget-action")
            self.assertEqual(status, 200)
            self.assertFalse(blocked["cart"]["can_checkout"])
            self.assertIn({"type": "order.confirm", "enabled": False}, blocked["actions"])
            disabled_status, disabled_error, _ = self.restaurant_request("actions", {"widget_id": blocked["widget_id"], "revision": 1, "action_id": "stock-disabled-confirm", "type": "order.confirm", "payload": {"cart_revision": blocked["cart_revision"]}}, cookie, "widget-action")
            self.assertEqual(disabled_status, 409)
            self.assertIn("disabled", disabled_error["message"])
            quantity_binding = next(binding for binding in current_widget["actions"]["quantities"] if binding["item_id"] == "hummus")
            self.assertEqual(quantity_binding["maximum"], 1)
            invalid_quantity = {"widget_id": current_widget["widget_id"], "revision": current_widget["revision"], "action_id": "stock-increase-disabled", "type": "cart.set_quantity", "payload": {"item_id": "hummus", "position": quantity_binding["position"], "quantity": 2, "cart_revision": current["cart"]["revision"]}}
            self.assertEqual(self.restaurant_request("actions", invalid_quantity, cookie, "widget-action")[0], 409)
            self.assertEqual(blocked["payload"]["en"]["children"][1]["children"][-1], {"kind": "badge", "label": "Sold out"})
            self.assertEqual(blocked["payload"]["ar"]["children"][1]["children"][-1], {"kind": "badge", "label": "نفد"})
            self.assertEqual(self.restaurant_request("actions", start, cookie, "widget-action")[1], view)
        finally:
            self.assertEqual(self.restaurant_request("demo/menu/hummus/restock", {}, cookie, "restock")[0], 200)

    def test_checkout_view_stays_invalid_after_cart_returns_and_edit(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        _, cart, _ = self.restaurant_request("cart/quantity", {"action_id": "revert-add", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")
        widget = self.widget("en", cookie)
        start = {"widget_id": widget["widget_id"], "revision": widget["revision"], "action_id": "revert-start", "type": "checkout.start", "payload": {"cart_revision": cart["revision"]}}
        _, view, _ = self.restaurant_request("actions", start, cookie, "widget-action")
        _, changed, _ = self.restaurant_request("cart/quantity", {"action_id": "revert-up", "item_id": "hummus", "quantity": 2, "cart_revision": cart["revision"]}, cookie, "cart")
        _, restored, _ = self.restaurant_request("cart/quantity", {"action_id": "revert-down", "item_id": "hummus", "quantity": 1, "cart_revision": changed["revision"]}, cookie, "cart")
        self.assertEqual(restored["revision"], cart["revision"])
        confirm = {"widget_id": view["widget_id"], "revision": 1, "action_id": "revert-confirm", "type": "order.confirm", "payload": {"cart_revision": cart["revision"]}}
        self.assertEqual(self.restaurant_request("actions", confirm, cookie, "widget-action")[0], 409)
        widget = self.widget("en", cookie)
        _, view, _ = self.restaurant_request("actions", {**start, "widget_id": widget["widget_id"], "revision": widget["revision"], "action_id": "edit-start"}, cookie, "widget-action")
        edit = {**confirm, "widget_id": view["widget_id"], "action_id": "edit-review", "type": "order.edit"}
        self.assertEqual(self.restaurant_request("actions", edit, cookie, "widget-action")[1], {"edited": True})
        self.assertEqual(self.restaurant_request("actions", edit, cookie, "widget-action")[1], {"edited": True})
        actions = self.action_context(cookie)["completed_actions"]
        self.assertEqual([action["type"] for action in actions].count("order.edit"), 1)
        self.assertEqual([action["type"] for action in actions].count("checkout.start"), 2)
        self.assertEqual(actions[-1]["widget_id"], view["widget_id"])
        self.assertEqual(self.restaurant_request("actions", {**confirm, "widget_id": view["widget_id"], "action_id": "edit-confirm"}, cookie, "widget-action")[0], 409)

    def test_widget_checkout_rejects_stale_cart(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        _, cart, _ = self.restaurant_request("cart/quantity", {"action_id": "stale-add", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")
        widget = self.widget("en", cookie)
        start = {"widget_id": widget["widget_id"], "revision": widget["revision"], "action_id": "stale-start", "type": "checkout.start", "payload": {"cart_revision": cart["revision"]}}
        _, view, _ = self.restaurant_request("actions", start, cookie, "widget-action")
        self.restaurant_request("cart/quantity", {"action_id": "stale-change", "item_id": "hummus", "quantity": 2, "cart_revision": cart["revision"]}, cookie, "cart")
        confirm = {"widget_id": view["widget_id"], "revision": 1, "action_id": "stale-confirm", "type": "order.confirm", "payload": {"cart_revision": cart["revision"]}}
        self.assertEqual(self.restaurant_request("actions", confirm, cookie, "widget-action")[0], 409)
        self.assertEqual(self.restaurant_request("actions", {**start, "action_id": "late-start"}, cookie, "widget-action")[0], 409)

    def test_concurrent_quantity_changes_reject_stale_cart(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/menu") as response:
            item_id: str = json.load(response)["items"][0]["id"]
        requests = [{"action_id": action_id, "item_id": item_id, "quantity": 1, "cart_revision": cart["revision"]} for action_id in ("tab-one", "tab-two")]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda payload: self.restaurant_request("cart/quantity", payload, cookie, "cart"), requests))
        self.assertEqual(sorted(result[0] for result in results), [200, 409])
        winner: int = next(index for index, result in enumerate(results) if result[0] == 200)
        updated = results[winner][1]
        self.assertEqual(self.restaurant_request("cart/quantity", requests[winner], cookie, "cart")[1], updated)
        reviewed = {**requests[1 - winner], "quantity": 2, "cart_revision": updated["revision"]}
        status, cart, _ = self.restaurant_request("cart/quantity", reviewed, cookie, "cart")
        self.assertEqual((status, cart["items"][0]["quantity"]), (200, 2))

    def test_confirmation_retry_recovers_result_after_cart_empties(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/menu") as response:
            item_id: str = json.load(response)["items"][0]["id"]
        _, cart, _ = self.restaurant_request("cart/quantity", {"action_id": "add", "item_id": item_id, "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")
        attempt = {"action_id": "confirm", "cart_revision": cart["revision"]}
        status, original, _ = self.restaurant_request("orders/confirm", attempt, cookie, "confirm")
        self.assertEqual(status, 200)
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/cart", headers={"Cookie": cookie})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(json.load(response)["items"], [])
        status, recovered, _ = self.restaurant_request("orders/confirm", attempt, cookie, "confirm")
        self.assertEqual((status, recovered), (200, original))

    def test_invalid_session_cookie_is_replaced(self) -> None:
        status, cart, cookie = self.restaurant_request("session", {}, "restaurant_session=expired", "session")
        self.assertEqual(status, 200)
        self.assertTrue(cookie.startswith("restaurant_session="))
        self.assertNotEqual(cookie, "restaurant_session=expired")
        self.assertEqual(cart["items"], [])

    def snapshot(self, cookie: str) -> dict[str, Any]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/events", headers={"Cookie": cookie})
        with urllib.request.urlopen(request, timeout=5) as response:
            for line in response:
                if line.startswith(b"data: "):
                    return json.loads(line[6:])
        raise RuntimeError("SSE returned no initial snapshot.")

    def state(self, cookie: str) -> dict[str, Any]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/state", headers={"Cookie": cookie})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            return json.load(response)

    def test_state_resync_is_scoped_ordered_and_matches_stream(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self.state("")
        self.assertEqual(missing.exception.code, 401)
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other = self.restaurant_request("session", {}, "", "session")
        first = self.state(cookie)
        other_first = self.state(other)
        self.assertEqual(first, self.state(cookie))
        self.assertEqual(first, self.snapshot(cookie))
        self.assertNotEqual(first["widgets"]["en"]["widget_id"], other_first["widgets"]["en"]["widget_id"])
        self.assertEqual(self.restaurant_request("cart/quantity", {"action_id": "resync-add", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")[0], 200)
        updated = self.state(cookie)
        self.assertGreater(updated["state_revision"], first["state_revision"])
        self.assertEqual(updated["cart"]["items"][0]["quantity"], 1)
        for index, locale in enumerate(("en", "ar")):
            before, after = first["updates"][index], updated["updates"][index]
            self.assertEqual(after["kind"], "widget_update")
            self.assertEqual((after["message_id"], after["widget_id"]), (before["message_id"], before["widget_id"]))
            self.assertGreater(after["revision"], before["revision"])
            self.assertEqual(after["revision"], updated["widgets"][locale]["revision"])
            self.assertEqual(self.validate(json.dumps(after["payload"]))[1]["preview"], updated["widgets"][locale]["payload"])
        self.assertEqual(other_first, self.state(other))
        self.assertEqual(updated, self.state(cookie))
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/events", headers={"Cookie": cookie, "Last-Event-ID": str(first["state_revision"])})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(next(response).decode().strip(), f"id: {updated['state_revision']}")
            self.assertEqual(next(response), b"event: snapshot\n")
            self.assertEqual(json.loads(next(response)[6:]), updated)

    def test_menu_views_are_stable_scoped_and_immutable(self) -> None:
        _, _, cookie = self.restaurant_request("session", {}, "", "session")
        initial = self.snapshot(cookie)
        self.assertEqual(initial["menu_view_ids"], self.snapshot(cookie)["menu_view_ids"])
        self.assertNotEqual(initial["menu_view_ids"]["en"], initial["menu_view_ids"]["ar"])
        _, _, other_cookie = self.restaurant_request("session", {}, "", "session")
        self.assertNotEqual(initial["menu_view_ids"]["en"], self.snapshot(other_cookie)["menu_view_ids"]["en"])
        item_id: str = initial["menu"]["items"][0]["id"]
        try:
            status, _, _ = self.restaurant_request(f"demo/menu/{item_id}/sell-out", {}, cookie, "sell-out")
            self.assertEqual(status, 200)
            updated = self.snapshot(cookie)
            self.assertNotEqual(initial["menu_view_ids"]["en"], updated["menu_view_ids"]["en"])
            with sqlite3.connect(Path(self.directory.name) / "test.sqlite") as connection:
                row = connection.execute("SELECT menu_json FROM menu_views WHERE id = ?", (initial["menu_view_ids"]["en"],)).fetchone()
            self.assertEqual(json.loads(row[0]), initial["menu"])
            self.assertFalse(updated["menu"]["items"][0]["available"])
        finally:
            self.assertEqual(self.restaurant_request(f"demo/menu/{item_id}/restock", {}, cookie, "restock")[0], 200)

    def test_browser_snapshot_contract_rejects_forged_and_invalid_updates(self) -> None:
        _, _, cookie = self.restaurant_request("session", {}, "", "session")
        snapshot = self.state(cookie)
        program = """import assert from 'node:assert/strict';
import { parseSnapshot, validateSnapshot } from './src/api.ts';
let source = '';
for await (const chunk of process.stdin) source += chunk;
const valid = parseSnapshot(source);
const originalFetch = globalThis.fetch;
globalThis.fetch = (url, options) => originalFetch(`http://127.0.0.1:${process.argv[1]}${url}`, options);
await validateSnapshot(valid);
const forged = structuredClone(valid);
forged.updates[0].widget_id = 'foreign';
assert.throws(() => parseSnapshot(JSON.stringify(forged)));
const old = structuredClone(valid);
old.updates[0].revision += 1;
assert.throws(() => parseSnapshot(JSON.stringify(old)));
const invalid = structuredClone(valid);
invalid.updates[0].payload.children[0].type = 'Unknown';
await assert.rejects(validateSnapshot(parseSnapshot(JSON.stringify(invalid))));
assert.throws(() => parseSnapshot('{'));
assert.equal(valid.updates[0].payload.children[0].type, 'ListViewItem');
"""
        subprocess.run(["node", "--experimental-strip-types", "--input-type=module", "-e", program, str(self.port)], cwd=Path(__file__).resolve().parents[2] / "frontend", input=json.dumps(snapshot), check=True, capture_output=True, text=True)

    def test_chat_rejects_unowned_or_mismatched_menu_views(self) -> None:
        _, _, cookie = self.restaurant_request("session", {}, "", "session")
        snapshot = self.snapshot(cookie)
        _, _, other_cookie = self.restaurant_request("session", {}, "", "session")
        foreign = self.snapshot(other_cookie)
        for index, (view_id, revision, locale) in enumerate([
            ("unknown-view", snapshot["menu"]["revision"], "en"),
            (foreign["menu_view_ids"]["en"], snapshot["menu"]["revision"], "en"),
            (snapshot["menu_view_ids"]["en"], snapshot["menu"]["revision"] + 1, "en"),
            (snapshot["menu_view_ids"]["en"], snapshot["menu"]["revision"], "ar"),
        ]):
            with self.subTest(view_id=view_id, revision=revision, locale=locale):
                widget = snapshot["widgets"]["en"]
                status, result, _ = self.restaurant_request("chat", {"client_message_id": f"invalid-{index}", "text": "Add the second one", "menu_revision": revision, "locale": locale, "rendered_view_id": view_id, "widget_view": {"widget_id": widget["widget_id"], "revision": widget["revision"], "rendered": self.rendered_menu(widget)}}, cookie, "chat")
                self.assertEqual((status, result["code"]), (409, "chat_conflict"))

    def test_chat_retry_binds_the_original_rendered_view(self) -> None:
        _, _, cookie = self.restaurant_request("session", {}, "", "session")
        snapshot = self.snapshot(cookie)
        view_id: str = snapshot["menu_view_ids"]["en"]
        widget = snapshot["widgets"]["en"]
        reference = {"widget_id": widget["widget_id"], "revision": widget["revision"], "rendered": self.rendered_menu(widget)}
        result = {"text": "Stored reply", "suggestion": None, "menu_revision": snapshot["menu"]["revision"], "cart_revision": snapshot["cart"]["revision"], "widget": None, "locale": "en"}
        with sqlite3.connect(Path(self.directory.name) / "test.sqlite") as connection:
            session_hash: str = connection.execute("SELECT session_hash FROM menu_views WHERE id = ?", (view_id,)).fetchone()[0]
            connection.execute("INSERT INTO chat_turns (session_hash, message_id, text, menu_revision, status, result_json, locale, rendered_view_id, widget_view) VALUES (?, 'retry', 'Show menu', ?, 'complete', ?, 'en', ?, ?)", (session_hash, snapshot["menu"]["revision"], json.dumps(result), view_id, json.dumps(reference, sort_keys=True)))
        request = {"client_message_id": "retry", "text": "Show menu", "menu_revision": snapshot["menu"]["revision"], "locale": "en", "rendered_view_id": view_id, "widget_view": reference}
        status, replayed, _ = self.restaurant_request("chat", request, cookie, "chat")
        self.assertEqual(status, 200)
        self.assertTrue(replayed["message_id"])
        self.assertEqual({key: value for key, value in replayed.items() if key not in ("message_id", "messages", "proposed_actions", "widget_author", "warnings", "suggestions", "widget_previews", "widget_authors", "widget_controls")}, result)
        self.assertEqual(self.restaurant_request("chat", request, cookie, "chat")[1]["message_id"], replayed["message_id"])
        old_widget_reply = {**result, "message_id": "legacy-assistant", "widget": widget["payload"], "messages": [{"kind": "text", "message_id": "legacy-assistant", "widget_id": None, "revision": None, "payload": {"text": result["text"]}}, {"kind": "widget", "message_id": widget["widget_id"], "widget_id": widget["widget_id"], "revision": widget["revision"], "payload": snapshot["updates"][0]["payload"]}]}
        with sqlite3.connect(Path(self.directory.name) / "test.sqlite") as connection:
            connection.execute("INSERT INTO chat_turns (session_hash, message_id, text, menu_revision, status, result_json, locale, rendered_view_id, widget_view) VALUES (?, 'legacy-widget-retry', 'Show menu', ?, 'complete', ?, 'en', ?, ?)", (session_hash, snapshot["menu"]["revision"], json.dumps(old_widget_reply), view_id, json.dumps(reference, sort_keys=True)))
        legacy_widget = self.restaurant_request("chat", {**request, "client_message_id": "legacy-widget-retry"}, cookie, "chat")[1]
        self.assertEqual(legacy_widget["widget_previews"], [widget["payload"]])
        status, conflict, _ = self.restaurant_request("chat", {**request, "rendered_view_id": None}, cookie, "chat")
        self.assertEqual((status, conflict["code"]), (409, "chat_conflict"))
        legacy = self.action_context(cookie)
        self.assertIsNone(legacy["actions_not_seen_in_latest_reply"])
        self.assertIsNone(legacy["quantity_reference"])

    def test_legacy_migration_preserves_new_action_reference(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        snapshot = self.snapshot(cookie)
        result = {"text": "Old reply", "suggestion": None, "menu_revision": snapshot["menu"]["revision"], "cart_revision": cart["revision"], "widget": None, "locale": "en"}
        database = Path(self.directory.name) / "test.sqlite"
        with sqlite3.connect(database) as connection:
            session_hash = connection.execute("SELECT session_hash FROM menu_views WHERE id = ?", (snapshot["menu_view_ids"]["en"],)).fetchone()[0]
            connection.execute("INSERT INTO chat_turns (session_hash, message_id, text, menu_revision, status, result_json, locale, action_sequence) VALUES (?, 'legacy', 'Hello', ?, 'complete', ?, 'en', -1)", (session_hash, snapshot["menu"]["revision"], json.dumps(result)))
        self.assertIsNone(self.action_context(cookie)["quantity_reference"])
        status, _, _ = self.restaurant_request("cart/quantity", {"action_id": "after-migration", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")
        self.assertEqual(status, 200)
        self.assertEqual(self.action_context(cookie)["quantity_reference"], {"item_id": "hummus", "quantity": 1, "source": "completed_action"})

    def action_context(self, cookie: str) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, "-c", "import json; import sys; from pathlib import Path; from app.chat import read_action_context; print(json.dumps(read_action_context(Path(sys.argv[1]), sys.argv[2], None, 'en')))", str(Path(self.directory.name) / "test.sqlite"), cookie.split("=", 1)[1]],
            cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True,
        )
        return json.loads(result.stdout)

    def test_action_context_records_only_completed_changes_once(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        self.assertEqual(self.action_context(cookie)["completed_actions"], [])
        first = {"action_id": "first", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}
        status, cart, _ = self.restaurant_request("cart/quantity", first, cookie, "cart")
        self.assertEqual(status, 200)
        status, cart, _ = self.restaurant_request("cart/quantity", {**first, "action_id": "second", "quantity": 2, "cart_revision": cart["revision"]}, cookie, "cart")
        self.assertEqual(status, 200)
        self.assertEqual(self.restaurant_request("cart/quantity", {**first, "action_id": "stale", "quantity": 3}, cookie, "cart")[0], 409)
        self.assertEqual(self.restaurant_request("cart/quantity", first, cookie, "cart")[0], 200)
        context = self.action_context(cookie)
        actions = context["completed_actions"]
        self.assertEqual([(action["action_id"], action["quantity"]) for action in actions], [("first", 1), ("second", 2)])
        self.assertEqual(actions[0]["cart_revision_after"], actions[1]["cart_revision_before"])
        self.assertEqual(actions[-1]["cart_revision_after"], context["snapshot"]["cart"]["revision"])
        self.assertEqual(context["snapshot"]["cart"]["items"][0]["quantity"], 2)
        status, _, _ = self.restaurant_request("cart/quantity", {**first, "action_id": "remove", "quantity": 0, "cart_revision": cart["revision"]}, cookie, "cart")
        self.assertEqual(status, 200)
        removed = self.action_context(cookie)
        self.assertEqual(removed["completed_actions"][-1]["quantity"], 0)
        self.assertEqual(removed["snapshot"]["cart"]["items"], [])
        _, _, other_cookie = self.restaurant_request("session", {}, "", "session")
        self.assertEqual(self.action_context(other_cookie)["completed_actions"], [])

    def test_action_context_keeps_one_immutable_confirmation(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        status, cart, _ = self.restaurant_request("cart/quantity", {"action_id": "add", "item_id": "falafel", "quantity": 2, "cart_revision": cart["revision"]}, cookie, "cart")
        self.assertEqual(status, 200)
        requests = [{"action_id": action_id, "cart_revision": cart["revision"]} for action_id in ("confirm-one", "confirm-two")]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda payload: self.restaurant_request("orders/confirm", payload, cookie, "confirm"), requests))
        self.assertEqual(sorted(result[0] for result in results), [200, 409])
        winner: int = next(index for index, result in enumerate(results) if result[0] == 200)
        self.assertEqual(self.restaurant_request("orders/confirm", requests[winner], cookie, "confirm")[1], results[winner][1])
        context = self.action_context(cookie)
        self.assertEqual([action["type"] for action in context["completed_actions"]], ["cart.set_quantity", "order.confirm"])
        self.assertEqual(context["completed_actions"][-1]["order"], results[winner][1])
        self.assertEqual(context["completed_actions"][-1]["cart_revision_after"], context["snapshot"]["cart"]["revision"])
        self.assertEqual(context["snapshot"]["cart"]["items"], [])
        self.assertIsNone(context["quantity_reference"])
        _, _, other_cookie = self.restaurant_request("session", {}, "", "session")
        self.assertEqual(self.action_context(other_cookie)["completed_actions"], [])

    def test_action_context_preserves_what_a_prior_reply_knew(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        status, cart, _ = self.restaurant_request("cart/quantity", {"action_id": "first", "item_id": "falafel", "quantity": 2, "cart_revision": cart["revision"]}, cookie, "cart")
        self.assertEqual(status, 200)
        before = self.action_context(cookie)
        sequence: int = before["completed_actions"][-1]["sequence"]
        reply = {"text": "Proposed hummus", "suggestion": {"item_id": "hummus", "quantity": 1}, "menu_revision": before["snapshot"]["menu"]["revision"], "cart_revision": cart["revision"], "widget": None, "locale": "en"}
        result = subprocess.run(
            [sys.executable, "-c", "import json; import sys; from pathlib import Path; from app.chat import begin_turn, finish_turn, read_history; path = Path(sys.argv[1]); token = sys.argv[2]; reply = json.loads(sys.argv[3]); begin_turn(path, token, 'proposal', 'Add hummus', reply['menu_revision'], 'en', None, None, None); finish_turn(path, token, 'proposal', reply, int(sys.argv[4])); print(json.dumps(read_history(path, token)))", str(Path(self.directory.name) / "test.sqlite"), cookie.split("=", 1)[1], json.dumps(reply), str(sequence)],
            cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True,
        )
        history = json.loads(result.stdout)
        historical_reply = json.loads(history[-1]["content"])
        self.assertEqual(historical_reply["reply"], reply)
        self.assertEqual(historical_reply["completed_actions_through_sequence"], sequence)
        after_reply = self.action_context(cookie)
        self.assertEqual(len(after_reply["completed_actions"]), 1)
        self.assertEqual(after_reply["actions_not_seen_in_latest_reply"], [])
        self.assertEqual(after_reply["latest_assistant_proposal"], reply["suggestion"])
        self.assertEqual(after_reply["quantity_reference"], {"item_id": "hummus", "quantity": 1, "source": "assistant_proposal"})
        status, _, _ = self.restaurant_request("cart/quantity", {"action_id": "newer", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")
        self.assertEqual(status, 200)
        newer = self.action_context(cookie)
        self.assertGreater(newer["completed_actions"][-1]["sequence"], sequence)
        self.assertEqual([action["action_id"] for action in newer["actions_not_seen_in_latest_reply"]], ["newer"])
        self.assertEqual(newer["quantity_reference"], {"item_id": "hummus", "quantity": 1, "source": "completed_action"})

    def test_action_context_is_bounded_and_chronological(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        for quantity in range(1, 23):
            status, cart, _ = self.restaurant_request("cart/quantity", {"action_id": f"set-{quantity}", "item_id": "hummus", "quantity": quantity, "cart_revision": cart["revision"]}, cookie, "cart")
            self.assertEqual(status, 200)
        context = self.action_context(cookie)
        actions = context["completed_actions"]
        self.assertEqual([action["quantity"] for action in actions], list(range(3, 23)))
        self.assertEqual([action["sequence"] for action in actions], sorted(action["sequence"] for action in actions))
        self.assertEqual(actions[-1]["cart_revision_after"], context["snapshot"]["cart"]["revision"])

    def test_valid_card_and_nested_list_render_plans(self) -> None:
        for source, expected_kind in [
            ('{"type":"Card","children":[{"type":"Text","value":"Hello"}]}', "card"),
            ('{"type":"ListView","children":[{"type":"ListViewItem","children":[{"type":"Row","children":[{"type":"Title","value":"Menu"}]}]}]}', "list"),
        ]:
            with self.subTest(source=source):
                status, result = self.validate(source)
                self.assertEqual(status, 200)
                self.assertEqual(result["status"], "valid")
                self.assertEqual(result["preview"]["kind"], expected_kind)
                self.assertEqual(result["issues"], [])

    def test_table_rendering_and_invalid_cells(self) -> None:
        source = {"type": "Card", "children": [{"type": "Table", "children": [
            {"type": "Table.Row", "header": True, "children": [{"type": "Table.Cell", "children": [{"type": "Text", "value": "Dish"}]}]},
            {"type": "Table.Row", "children": [{"type": "Table.Cell", "align": "end", "children": [{"type": "Text", "value": "Hummus"}]}, {"type": "Unknown"}]},
            {"type": "Unknown"},
        ]}]}
        status, result = self.validate(json.dumps(source))
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "partial")
        rows = result["preview"]["children"][0]["rows"]
        self.assertTrue(rows[0]["header"])
        self.assertEqual(rows[1]["cells"][0]["align"], "end")
        self.assertEqual(rows[1]["cells"][0]["children"][0]["value"], "Hummus")
        self.assertEqual(rows[1]["cells"][1]["children"][0]["kind"], "problem")
        self.assertEqual(rows[2]["cells"][0]["children"][0]["kind"], "problem")
        self.assertEqual([entry["code"] for entry in result["issues"]], ["invalid_table_cell", "invalid_table_row"])
        source["children"][0]["children"] = [{"type": "Table.Row", "children": [{"type": "Table.Cell", "children": []}] * 21}]
        self.assertEqual(self.validate(json.dumps(source))[1]["status"], "invalid")

    def test_invalid_root_and_malformed_source_return_invalid_without_preview(self) -> None:
        for source, code in [('{"type":"Card","children":[', "invalid_json"), ('[]', "invalid_root"), ('{"type":"Card"}', "invalid_root"), ('{"type":"Card","type":"Card","children":[]}', "invalid_json"), ('{"view":"<Card />"}', "unsupported_template_format")]:
            with self.subTest(source=source):
                status, result = self.validate(source)
                self.assertEqual(status, 200)
                self.assertEqual(result["status"], "invalid")
                self.assertIsNone(result["preview"])
                self.assertEqual(result["issues"][0]["code"], code)

    def test_broken_child_preserves_valid_siblings_and_location(self) -> None:
        status, result = self.validate('{"type":"Card","children":[{"type":"Text","value":"Before"},{"type":"Mystery"},{"type":"Text","value":"After"}]}')
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["issues"][0]["path"], "$.children[1]")
        self.assertEqual([child["kind"] for child in result["preview"]["children"]], ["text", "problem", "text"])
        self.assertEqual([result["preview"]["children"][i]["value"] for i in (0, 2)], ["Before", "After"])

    def test_duplicate_sibling_key_is_replaced_with_placeholder(self) -> None:
        status, result = self.validate('{"type":"Card","children":[{"type":"Text","key":"a","value":"First"},{"type":"Text","key":"a","value":"Second"}]}')
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["issues"][0]["code"], "duplicate_key")
        self.assertEqual(result["preview"]["children"][1]["kind"], "problem")

    def test_executable_property_is_removed_and_text_preserved(self) -> None:
        status, result = self.validate('{"type":"Card","children":[{"type":"Text","value":"<script>alert(1)</script>","onClick":"alert(1)"}]}')
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["issues"][0]["code"], "unsupported_property")
        self.assertEqual(result["preview"]["children"], [{"kind": "text", "value": "<script>alert(1)</script>"}])

    def test_request_envelope_and_content_type_errors(self) -> None:
        for body, content_type, expected_status, code in [
            (b'{}', 'application/json', 422, 'invalid_envelope'),
            (b'{"source":12}', 'application/json', 422, 'invalid_envelope'),
            (b'{"source":"x","extra":1}', 'application/json', 422, 'invalid_envelope'),
            (b'{"source":"x","source":"y"}', 'application/json', 422, 'invalid_envelope'),
            (b'{}', 'text/plain', 415, 'unsupported_media_type'),
            (b'{"source":"\\ud800"}', 'application/json', 422, 'invalid_unicode'),
        ]:
            with self.subTest(body=body, content_type=content_type):
                status, result = self.request(body, content_type)
                self.assertEqual((status, result["code"]), (expected_status, code))

    def test_source_size_boundary_uses_utf8_bytes(self) -> None:
        prefix: str = '{"type":"Card","children":[],"x":"'
        suffix: str = '"}'
        for size, expected in [(32768, "partial"), (32769, "invalid")]:
            source: str = prefix + "a" * (size - len(prefix) - len(suffix) - 2) + "é" + suffix
            self.assertEqual(len(source.encode()), size)
            status, result = self.validate(source)
            self.assertEqual((status, result["status"]), (200, expected))

    def test_body_limit_is_enforced(self) -> None:
        status, result = self.request(b' ' * 262145, 'application/json')
        self.assertEqual((status, result["code"]), (413, "body_limit"))


if __name__ == "__main__":
    unittest.main()
