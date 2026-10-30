import json
from typing import Literal, NoReturn, TypedDict


class Issue(TypedDict):
    code: str
    path: str
    severity: Literal["warning", "error"]
    message: str


class TextNode(TypedDict):
    kind: Literal["text"]
    value: str


class ProblemNode(TypedDict):
    kind: Literal["problem"]
    message: str


class CardNode(TypedDict):
    kind: Literal["card"]
    children: list[TextNode | ProblemNode]


class ValidationResult(TypedDict):
    status: Literal["valid", "partial", "invalid"]
    preview: CardNode | None
    issues: list[Issue]


class InvalidSource(ValueError):
    pass


def reject_constant(value: str) -> NoReturn:
    raise InvalidSource("Nonstandard JSON constant")


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidSource("Duplicate JSON object key")
        result[key] = value
    return result


def check_structure(source: str) -> None:
    depth: int = 0
    containers: int = 0
    in_string: bool = False
    escaped: bool = False
    for character in source:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            containers += 1
            if depth > 16 or containers > 4096:
                raise InvalidSource("JSON structure exceeds limits")
        elif character in "]}":
            depth -= 1


def issue(code: str, path: str, severity: Literal["warning", "error"], message: str) -> Issue:
    return {"code": code, "path": path, "severity": severity, "message": message}


def invalid(code: str, message: str) -> ValidationResult:
    return {"status": "invalid", "preview": None, "issues": [issue(code, "$", "error", message)]}


def check_unicode(value: object) -> None:
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, list):
        for item in value:
            check_unicode(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            check_unicode(key)
            check_unicode(item)


def validate_source(source: str) -> ValidationResult:
    try:
        if len(source.encode("utf-8")) > 32768:
            return invalid("source_limit", "Widget source exceeds the size limit.")
        check_structure(source)
        data: object = json.loads(source, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (json.JSONDecodeError, InvalidSource, RecursionError):
        return invalid("invalid_json", "Widget JSON is malformed or exceeds structural limits.")
    check_unicode(data)
    if not isinstance(data, dict):
        return invalid("invalid_root", "The root must be a Card object.")
    if "view" in data:
        return invalid("unsupported_template_format", "Submit a hydrated JSON tree, not a Studio template.")
    if data.get("type") != "Card" or not isinstance(data.get("children"), list):
        return invalid("invalid_root", "The root must be a Card with a children array.")
    children: list[object] = data["children"]
    if len(children) > 100:
        return invalid("child_limit", "Card exceeds the child limit.")
    issues: list[Issue] = []
    preview_children: list[TextNode | ProblemNode] = []
    seen_keys: set[str] = set()
    for prop in data:
        if prop not in {"type", "children", "key"}:
            issues.append(issue("unsupported_property", f"$.{prop}", "warning", "Property is not supported."))
    for index, child in enumerate(children):
        path: str = f"$.children[{index}]"
        if not isinstance(child, dict) or child.get("type") != "Text" or not isinstance(child.get("value"), str):
            issues.append(issue("unsupported_child", path, "error", "Child is unsupported or invalid."))
            preview_children.append({"kind": "problem", "message": "This item could not be displayed."})
            continue
        value: str = child["value"]
        if len(value) > 4096:
            return invalid("text_limit", "Text exceeds the size limit.")
        key: object = child.get("key")
        if isinstance(key, str):
            if len(key) > 128:
                return invalid("key_limit", "Key exceeds the size limit.")
            if key in seen_keys:
                issues.append(issue("duplicate_key", path, "error", "Sibling key is duplicated."))
                preview_children.append({"kind": "problem", "message": "This item could not be displayed."})
                continue
            seen_keys.add(key)
        elif key is not None:
            issues.append(issue("invalid_key", f"{path}.key", "warning", "Key must be a string or null."))
        for prop in child:
            if prop not in {"type", "value", "key"}:
                issues.append(issue("unsupported_property", f"{path}.{prop}", "warning", "Property is not supported."))
        preview_children.append({"kind": "text", "value": value})
    root_key: object = data.get("key")
    if isinstance(root_key, str) and len(root_key) > 128:
        return invalid("key_limit", "Key exceeds the size limit.")
    if root_key is not None and not isinstance(root_key, str):
        issues.append(issue("invalid_key", "$.key", "warning", "Key must be a string or null."))
    if len(issues) > 100:
        issues = issues[:99] + [issue("issues_truncated", "$", "warning", "Additional issues were omitted.")]
    return {"status": "partial" if issues else "valid", "preview": {"kind": "card", "children": preview_children}, "issues": issues}
