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
