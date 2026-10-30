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


class ChartApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        database: str = str(Path(cls.directory.name) / "test.sqlite")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]
        cls.server = subprocess.Popen(
            [sys.executable, "-c", "from pathlib import Path; import sys; import uvicorn; import app.main; app.main.DATABASE_PATH = Path(sys.argv[1]); uvicorn.run(app.main.app, host='127.0.0.1', port=int(sys.argv[2]), log_level='warning')", database, str(cls.port)],
            cwd=Path(__file__).resolve().parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
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
        raise RuntimeError("Chart test server did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        cls.server.communicate(timeout=5)
        cls.directory.cleanup()

    def validate(self, chart: dict[str, Any]) -> dict[str, Any]:
        source: str = json.dumps({"type": "Card", "children": [{"type": "Text", "value": "Before"}, chart, {"type": "Text", "value": "After"}]})
        request: urllib.request.Request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/payloads/validate", data=json.dumps({"source": source}).encode(), headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_bar_and_line_preserve_zero_negative_and_labels(self) -> None:
        chart = {"type": "Chart", "data": [{"day": "Mon", "orders": 0, "change": -3}, {"day": "Tue", "orders": 5, "change": 2}], "series": [{"type": "bar", "dataKey": "orders", "color": "green"}, {"type": "line", "dataKey": "change", "label": "Change"}], "xAxis": {"dataKey": "day"}, "showYAxis": True}
        result = self.validate(chart)
        self.assertEqual(result["status"], "valid")
        node = result["preview"]["children"][1]
        self.assertEqual(node["points"], [{"label": "Mon", "values": [0, -3]}, {"label": "Tue", "values": [5, 2]}])
        self.assertEqual([series["type"] for series in node["series"]], ["bar", "line"])
        self.assertTrue(node["show_y_axis"])

    def test_x_axis_string_shorthand(self) -> None:
        chart = {"type": "Chart", "data": [{"day": "Mon", "orders": 1}], "series": [{"type": "bar", "dataKey": "orders"}], "xAxis": "day"}
        result = self.validate(chart)
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["preview"]["children"][1]["points"], [{"label": "Mon", "values": [1]}])

    def test_invalid_data_becomes_placeholder_without_losing_siblings(self) -> None:
        base = {"type": "Chart", "data": [{"day": "Mon", "orders": 1}], "series": [{"type": "bar", "dataKey": "orders"}], "xAxis": {"dataKey": "day"}}
        for change in ({"series": [{"type": "area", "dataKey": "orders"}]}, {"data": [{"day": "Mon"}]}, {"data": [{"day": "Mon", "orders": True}]}, {"data": [{"day": "Mon", "orders": 1e300}]}):
            with self.subTest(change=change):
                result = self.validate({**base, **change})
                self.assertEqual(result["status"], "partial")
                self.assertEqual([child["kind"] for child in result["preview"]["children"]], ["text", "problem", "text"])

    def test_point_and_series_limits(self) -> None:
        chart = {"type": "Chart", "data": [{"day": str(i), "v": i} for i in range(200)], "series": [{"type": "bar", "dataKey": "v"}], "xAxis": {"dataKey": "day"}}
        self.assertEqual(self.validate(chart)["status"], "valid")
        self.assertEqual(self.validate({**chart, "data": chart["data"] + [{"day": "extra", "v": 1}]})["status"], "invalid")
        self.assertEqual(self.validate({**chart, "series": chart["series"] * 5})["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
