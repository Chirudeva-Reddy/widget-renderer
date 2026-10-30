import math
from typing import Literal, NotRequired, TypedDict


class ChartIssue(TypedDict):
    code: str
    path: str
    severity: Literal["warning", "error"]
    message: str


class ChartSeries(TypedDict):
    type: Literal["bar", "line"]
    label: str
    color: NotRequired[Literal["blue", "purple", "orange", "green", "red", "yellow", "pink"]]


class ChartPoint(TypedDict):
    label: str
    values: list[float]


class ChartNode(TypedDict):
    kind: Literal["chart"]
    points: list[ChartPoint]
    series: list[ChartSeries]
    show_y_axis: bool
    show_legend: bool


class ChartLimitError(ValueError):
    pass


def chart_issue(code: str, path: str, severity: Literal["warning", "error"], message: str) -> ChartIssue:
    return {"code": code, "path": path, "severity": severity, "message": message}


def validate_chart(data: dict[str, object], path: str) -> tuple[ChartNode | None, list[ChartIssue]]:
    rows: object = data.get("data")
    raw_series: object = data.get("series")
    axis: object = data.get("xAxis")
    if not isinstance(rows, list) or not isinstance(raw_series, list) or not isinstance(axis, dict) or not isinstance(axis.get("dataKey"), str) or not axis["dataKey"] or not rows or not raw_series:
        return None, [chart_issue("invalid_chart", path, "error", "Chart requires non-empty data, series, and an x-axis key.")]
    if len(rows) > 200 or len(raw_series) > 4:
        raise ChartLimitError("Chart exceeds the data point or series limit.")
    issues: list[ChartIssue] = []
    series: list[ChartSeries] = []
    keys: list[str] = []
    for index, item in enumerate(raw_series):
        series_path: str = f"{path}.series[{index}]"
        if not isinstance(item, dict) or item.get("type") not in ("bar", "line") or not isinstance(item.get("dataKey"), str) or not item["dataKey"]:
            return None, [chart_issue("invalid_chart_series", series_path, "error", "Series requires a bar or line type and data key.")]
        key: str = item["dataKey"]
        if key in keys:
            return None, [chart_issue("invalid_chart_series", series_path, "error", "Series data keys must be unique.")]
        label: object = item.get("label", key)
        if not isinstance(label, str) or len(label) > 256:
            return None, [chart_issue("invalid_chart_series", series_path, "error", "Series label must be a string of at most 256 characters.")]
        chart_series: ChartSeries = {"type": item["type"], "label": label}
        color: object = item.get("color")
        if color in ("blue", "purple", "orange", "green", "red", "yellow", "pink"):
            chart_series["color"] = color
        elif "color" in item:
            issues.append(chart_issue("invalid_property", f"{series_path}.color", "warning", "Chart color is not supported."))
        for prop in item:
            if prop not in {"type", "dataKey", "label", "color"}:
                issues.append(chart_issue("unsupported_property", f"{series_path}.{prop}", "warning", "Property is not supported."))
        keys.append(key)
        series.append(chart_series)
    points: list[ChartPoint] = []
    axis_key: str = axis["dataKey"]
    for index, row in enumerate(rows):
        row_path: str = f"{path}.data[{index}]"
        if not isinstance(row, dict) or axis_key not in row:
            return None, [chart_issue("invalid_chart_data", row_path, "error", "Each data point must contain the x-axis key.")]
        x: object = row[axis_key]
        if isinstance(x, bool) or not isinstance(x, (str, int, float)) or (isinstance(x, (int, float)) and (abs(x) > 1e12 or not math.isfinite(x))) or (isinstance(x, str) and len(x) > 256):
            return None, [chart_issue("invalid_chart_data", row_path, "error", "X-axis values must be bounded strings or numbers.")]
        values: list[float] = []
        for key in keys:
            value: object = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 1e12 or not math.isfinite(value):
                return None, [chart_issue("invalid_chart_data", row_path, "error", "Every series value must be a finite number within bounds.")]
            values.append(float(value))
        if any(not isinstance(value, (str, int, float)) or isinstance(value, bool) or (isinstance(value, (int, float)) and (abs(value) > 1e12 or not math.isfinite(value))) for value in row.values()):
            return None, [chart_issue("invalid_chart_data", row_path, "error", "Chart fields must be bounded strings or numbers.")]
        points.append({"label": str(x), "values": values})
    for prop in data:
        if prop not in {"type", "key", "data", "series", "xAxis", "showYAxis", "showLegend"}:
            issues.append(chart_issue("unsupported_property", f"{path}.{prop}", "warning", "Property is not supported."))
    for prop in axis:
        if prop != "dataKey":
            issues.append(chart_issue("unsupported_property", f"{path}.xAxis.{prop}", "warning", "Property is not supported."))
    show_y: object = data.get("showYAxis", False)
    show_legend: object = data.get("showLegend", True)
    if not isinstance(show_y, bool):
        issues.append(chart_issue("invalid_property", f"{path}.showYAxis", "warning", "Show Y axis must be a boolean."))
        show_y = False
    if not isinstance(show_legend, bool):
        issues.append(chart_issue("invalid_property", f"{path}.showLegend", "warning", "Show legend must be a boolean."))
        show_legend = True
    if "key" in data and data["key"] is not None and not isinstance(data["key"], str):
        issues.append(chart_issue("invalid_key", f"{path}.key", "warning", "Key must be a string or null."))
    return {"kind": "chart", "points": points, "series": series, "show_y_axis": show_y, "show_legend": show_legend}, issues
