import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
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
