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


class ContainerNode(TypedDict):
    kind: Literal["card", "list", "list_item", "row", "col"]
    children: list["Node"]


Node = TextNode | ProblemNode | ContainerNode


class ValidationResult(TypedDict):
    status: Literal["valid", "partial", "invalid"]
    preview: ContainerNode | None
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
    root_type: object = data.get("type")
    if root_type not in ("Card", "ListView") or not isinstance(data.get("children"), list):
        return invalid("invalid_root", "The root must be a Card or ListView with a children array.")
    try:
        preview, issues = validate_container(data, "$", str(root_type))
        if count_nodes(preview) > 1000:
            raise InvalidSource("Widget exceeds the node limit.")
    except InvalidSource as error:
        return invalid("widget_limit", str(error))
    if len(issues) > 100:
        issues = issues[:99] + [issue("issues_truncated", "$", "warning", "Additional issues were omitted.")]
    return {"status": "partial" if issues else "valid", "preview": preview, "issues": issues}


def validate_container(data: dict[str, object], path: str, component: str) -> tuple[ContainerNode, list[Issue]]:
    kinds: dict[str, Literal["card", "list", "list_item", "row", "col"]] = {
        "Card": "card", "ListView": "list", "ListViewItem": "list_item", "Row": "row", "Col": "col",
    }
    children: object = data.get("children")
    if not isinstance(children, list):
        raise InvalidSource("Container children must be an array.")
    if len(children) > 100:
        raise InvalidSource("A container exceeds the child limit.")
    issues: list[Issue] = []
    nodes: list[Node] = []
    seen_keys: set[str] = set()
    for prop in data:
        if prop not in {"type", "children", "key"}:
            issues.append(issue("unsupported_property", f"{path}.{prop}", "warning", "Property is not supported."))
    key: object = data.get("key")
    if isinstance(key, str) and len(key) > 128:
        raise InvalidSource("Key exceeds the size limit.")
    if key is not None and not isinstance(key, str):
        issues.append(issue("invalid_key", f"{path}.key", "warning", "Key must be a string or null."))
    for index, child in enumerate(children):
        child_path: str = f"{path}.children[{index}]"
        if isinstance(child, dict) and isinstance(child.get("key"), str):
            child_key: str = child["key"]
            if len(child_key) > 128:
                raise InvalidSource("Key exceeds the size limit.")
            if child_key in seen_keys:
                issues.append(issue("duplicate_key", child_path, "error", "Sibling key is duplicated."))
                nodes.append({"kind": "problem", "message": "This item could not be displayed."})
                continue
            seen_keys.add(child_key)
        child_type: object = child.get("type") if isinstance(child, dict) else None
        allowed: bool = (component == "ListView" and child_type == "ListViewItem") or (component != "ListView" and child_type in ("Text", "Row", "Col"))
        if not isinstance(child, dict) or not allowed:
            issues.append(issue("unsupported_child", child_path, "error", "Child is unsupported or invalid."))
            nodes.append({"kind": "problem", "message": "This item could not be displayed."})
        elif child_type == "Text":
            value: object = child.get("value")
            if not isinstance(value, str):
                issues.append(issue("unsupported_child", child_path, "error", "Child is unsupported or invalid."))
                nodes.append({"kind": "problem", "message": "This item could not be displayed."})
                continue
            if len(value) > 4096:
                raise InvalidSource("Text exceeds the size limit.")
            for prop in child:
                if prop not in {"type", "value", "key"}:
                    issues.append(issue("unsupported_property", f"{child_path}.{prop}", "warning", "Property is not supported."))
            child_key_value: object = child.get("key")
            if child_key_value is not None and not isinstance(child_key_value, str):
                issues.append(issue("invalid_key", f"{child_path}.key", "warning", "Key must be a string or null."))
            nodes.append({"kind": "text", "value": value})
        elif not isinstance(child.get("children"), list):
            issues.append(issue("unsupported_child", child_path, "error", "Container children must be an array."))
            nodes.append({"kind": "problem", "message": "This item could not be displayed."})
        else:
            nested, nested_issues = validate_container(child, child_path, str(child_type))
            nodes.append(nested)
            issues.extend(nested_issues)
    return {"kind": kinds[component], "children": nodes}, issues


def count_nodes(node: Node) -> int:
    if node["kind"] in ("text", "problem"):
        return 1
    return 1 + sum(count_nodes(child) for child in node["children"])
