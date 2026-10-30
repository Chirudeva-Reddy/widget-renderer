import re
from typing import Literal, NotRequired, TypedDict


class ControlIssue(TypedDict):
    code: str
    path: str
    severity: Literal["warning", "error"]
    message: str


class ButtonNode(TypedDict):
    disabled: NotRequired[bool]
    kind: Literal["button"]
    label: str
    key: NotRequired[str]


class InputNode(TypedDict):
    key: NotRequired[str]
    kind: Literal["input"]
    name: str
    value: str
    placeholder: str
    required: bool
    disabled: bool


class SelectOption(TypedDict):
    label: str
    value: str
    disabled: bool


class SelectNode(TypedDict):
    key: NotRequired[str]
    kind: Literal["select"]
    name: str
    value: str
    placeholder: str
    disabled: bool
    options: list[SelectOption]


ControlNode = ButtonNode | InputNode | SelectNode


def problem(code: str, path: str, message: str) -> ControlIssue:
    return {"code": code, "path": path, "severity": "error", "message": message}


def validate_control(data: dict[str, object], path: str) -> tuple[ControlNode | None, list[ControlIssue]]:
    component: object = data.get("type")
    issues: list[ControlIssue] = []
    if component == "Button":
        label: object = data.get("label")
        if not isinstance(label, str) or not label or len(label) > 256:
            return None, [problem("invalid_control", path, "Button requires a label of at most 256 characters.")]
        node: ControlNode = {"kind": "button", "label": label}
        if isinstance(data.get("key"), str):
            node["key"] = data["key"]
        supported: set[str] = {"type", "label", "key", "disabled"}
        if "disabled" in data:
            if not isinstance(data["disabled"], bool):
                return None, [problem("invalid_control", path, "Button disabled must be boolean.")]
            node["disabled"] = data["disabled"]
    else:
        name: object = data.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
            return None, [problem("invalid_control", path, "Field name must be a simple name of at most 64 characters.")]
        disabled: object = data.get("disabled", False)
        placeholder: object = data.get("placeholder", "")
        if not isinstance(disabled, bool) or not isinstance(placeholder, str) or len(placeholder) > 256:
            return None, [problem("invalid_control", path, "Field disabled and placeholder values are invalid.")]
        default: object = data.get("defaultValue", "")
        if not isinstance(default, str) or len(default) > 256:
            return None, [problem("invalid_control", path, "Default value must be a string of at most 256 characters.")]
        if component == "Input":
            required: object = data.get("required", False)
            if data.get("inputType") != "number" or not isinstance(required, bool) or (default != "" and (not re.fullmatch(r"[0-9]+", default) or int(default) > 99)):
                return None, [problem("invalid_control", path, "Quantity input must be numeric and between 0 and 99.")]
            node = {"kind": "input", "name": name, "value": default, "placeholder": placeholder, "required": required, "disabled": disabled}
            supported = {"type", "name", "inputType", "defaultValue", "placeholder", "required", "disabled", "key"}
        elif component == "Select":
            raw_options: object = data.get("options")
            if not isinstance(raw_options, list) or not 1 <= len(raw_options) <= 100:
                return None, [problem("invalid_control", path, "Select requires between 1 and 100 options.")]
            options: list[SelectOption] = []
            values: set[str] = set()
            for index, option in enumerate(raw_options):
                if not isinstance(option, dict) or set(option) - {"value", "label", "disabled"} or not isinstance(option.get("value"), str) or not option["value"] or len(option["value"]) > 256 or not isinstance(option.get("label"), str) or len(option["label"]) > 256 or not isinstance(option.get("disabled", False), bool) or option["value"] in values:
                    return None, [problem("invalid_option", f"{path}.options[{index}]", "Option must have a unique value and a valid label.")]
                values.add(option["value"])
                options.append({"value": option["value"], "label": option["label"], "disabled": option.get("disabled", False)})
            if default and not any(option["value"] == default and not option["disabled"] for option in options):
                return None, [problem("invalid_control", path, "Default value must match an enabled option.")]
            node = {"kind": "select", "name": name, "value": default, "placeholder": placeholder, "disabled": disabled, "options": options}
            supported = {"type", "name", "defaultValue", "placeholder", "disabled", "options", "key"}
        else:
            return None, [problem("invalid_control", path, "Control type is not supported.")]
    if isinstance(data.get("key"), str):
        node["key"] = data["key"]
    for prop in data:
        if prop not in supported:
            issues.append({"code": "unsupported_property", "path": f"{path}.{prop}", "severity": "warning", "message": "Property is not supported in the preview."})
    if "key" in data and data["key"] is not None and not isinstance(data["key"], str):
        issues.append({"code": "invalid_key", "path": f"{path}.key", "severity": "warning", "message": "Key must be a string or null."})
    return node, issues
