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

    def test_widget_revisions_are_owned_immutable_and_acknowledged(self) -> None:
        _, cart, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other_cookie = self.restaurant_request("session", {}, "", "session")
        first = self.widget("en", cookie)
        self.assertEqual(first, self.widget("en", cookie))
        self.assertNotEqual(first["widget_id"], self.widget("ar", cookie)["widget_id"])
        self.assertNotEqual(first["widget_id"], self.widget("en", other_cookie)["widget_id"])
        endpoint = f"widgets/{first['widget_id']}/rendered"
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1}, other_cookie, "widget-rendered")[0], 409)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1}, cookie, "widget-rendered")[1], first)
        status, _, _ = self.restaurant_request("cart/quantity", {"action_id": "widget-test", "item_id": "hummus", "quantity": 1, "cart_revision": cart["revision"]}, cookie, "cart")
        self.assertEqual(status, 200)
        second = self.widget("en", cookie)
        self.assertEqual(second["widget_id"], first["widget_id"])
        self.assertEqual(second["revision"], first["revision"] + 1)
        self.assertEqual(first["cart"]["items"], [])
        self.assertEqual(second["cart"]["items"][0]["quantity"], 1)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": second["revision"]}, cookie, "widget-rendered")[1], second)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 1}, cookie, "widget-rendered")[1], first)
        self.assertEqual(self.restaurant_request(endpoint, {"revision": 999}, cookie, "widget-rendered")[0], 409)
        with sqlite3.connect(Path(self.directory.name) / "test.sqlite") as connection:
            stored = connection.execute("SELECT envelope_json FROM widget_revisions WHERE widget_id = ? AND revision = 1", (first["widget_id"],)).fetchone()
            acknowledged = connection.execute("SELECT revision FROM widget_acknowledgements WHERE widget_id = ?", (first["widget_id"],)).fetchone()
        self.assertEqual(acknowledged[0], second["revision"])
        self.assertEqual(json.loads(stored[0]), first)

    def test_chat_rejects_foreign_and_mismatched_widget_references(self) -> None:
        _, _, cookie = self.restaurant_request("session", {}, "", "session")
        _, _, other = self.restaurant_request("session", {}, "", "session")
        widget = self.widget("en", cookie)
        reference = {"widget_id": widget["widget_id"], "revision": widget["revision"]}
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
        _, new_cart, _ = self.restaurant_request("cart/quantity", {"action_id": "checkout-add-again", "item_id": "hummus", "quantity": 1, "cart_revision": self.snapshot(cookie)["cart"]["revision"]}, cookie, "cart")
        self.assertEqual(new_cart["revision"], cart["revision"])
        self.assertEqual(self.restaurant_request("actions", {**confirm, "action_id": "replay-old-review"}, cookie, "widget-action")[0], 409)

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
                status, result, _ = self.restaurant_request("chat", {"client_message_id": f"invalid-{index}", "text": "Add the second one", "menu_revision": revision, "locale": locale, "rendered_view_id": view_id}, cookie, "chat")
                self.assertEqual((status, result["code"]), (409, "chat_conflict"))

    def test_chat_retry_binds_the_original_rendered_view(self) -> None:
        _, _, cookie = self.restaurant_request("session", {}, "", "session")
        snapshot = self.snapshot(cookie)
        view_id: str = snapshot["menu_view_ids"]["en"]
        result = {"text": "Stored reply", "suggestion": None, "menu_revision": snapshot["menu"]["revision"], "cart_revision": snapshot["cart"]["revision"], "widget": None, "locale": "en"}
        with sqlite3.connect(Path(self.directory.name) / "test.sqlite") as connection:
            session_hash: str = connection.execute("SELECT session_hash FROM menu_views WHERE id = ?", (view_id,)).fetchone()[0]
            connection.execute("INSERT INTO chat_turns (session_hash, message_id, text, menu_revision, status, result_json, locale, rendered_view_id) VALUES (?, 'retry', 'Show menu', ?, 'complete', ?, 'en', ?)", (session_hash, snapshot["menu"]["revision"], json.dumps(result), view_id))
        request = {"client_message_id": "retry", "text": "Show menu", "menu_revision": snapshot["menu"]["revision"], "locale": "en", "rendered_view_id": view_id}
        status, replayed, _ = self.restaurant_request("chat", request, cookie, "chat")
        self.assertEqual((status, replayed), (200, result))
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
            [sys.executable, "-c", "import json; import sys; from pathlib import Path; from app.chat import read_action_context; print(json.dumps(read_action_context(Path(sys.argv[1]), sys.argv[2])))", str(Path(self.directory.name) / "test.sqlite"), cookie.split("=", 1)[1]],
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
            [sys.executable, "-c", "import json; import sys; from pathlib import Path; from app.chat import begin_turn, finish_turn, read_history; path = Path(sys.argv[1]); token = sys.argv[2]; reply = json.loads(sys.argv[3]); begin_turn(path, token, 'proposal', 'Add hummus', reply['menu_revision'], 'en', None, None); finish_turn(path, token, 'proposal', reply, int(sys.argv[4])); print(json.dumps(read_history(path, token)))", str(Path(self.directory.name) / "test.sqlite"), cookie.split("=", 1)[1], json.dumps(reply), str(sequence)],
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
