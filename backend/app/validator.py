import json
from typing import Literal, NoReturn, NotRequired, TypedDict


class Issue(TypedDict):
    code: str
    path: str
    severity: Literal["warning", "error"]
    message: str


class TextNode(TypedDict):
    kind: Literal["text", "title", "caption"]
    value: str
    weight: NotRequired[Literal["normal", "medium", "semibold", "bold"]]


class BadgeNode(TypedDict):
    kind: Literal["badge"]
    label: str


class DividerNode(TypedDict):
    kind: Literal["divider"]


class ProblemNode(TypedDict):
    kind: Literal["problem"]
    message: str


class ContainerNode(TypedDict):
    kind: Literal["card", "list", "list_item", "row", "col"]
    children: list["Node"]
    gap: NotRequired[int]


class TableCell(TypedDict):
    children: list["Node"]
    align: NotRequired[Literal["start", "center", "end"]]


class TableRow(TypedDict):
    header: bool
    cells: list[TableCell]


class TableNode(TypedDict):
    kind: Literal["table"]
    rows: list[TableRow]


Node = TextNode | BadgeNode | DividerNode | ProblemNode | ContainerNode | TableNode


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
        if prop not in ({"type", "children", "key", "gap"} if component in ("Row", "Col", "ListViewItem") else {"type", "children", "key"}):
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
        allowed: bool = (component == "ListView" and child_type == "ListViewItem") or (component != "ListView" and child_type in ("Text", "Title", "Caption", "Badge", "Divider", "Table", "Row", "Col"))
        if not isinstance(child, dict) or not allowed:
            issues.append(issue("unsupported_child", child_path, "error", "Child is unsupported or invalid."))
            nodes.append({"kind": "problem", "message": "This item could not be displayed."})
        elif child_type in ("Text", "Title", "Caption"):
            value: object = child.get("value")
            if not isinstance(value, str):
                issues.append(issue("unsupported_child", child_path, "error", "Child is unsupported or invalid."))
                nodes.append({"kind": "problem", "message": "This item could not be displayed."})
                continue
            if len(value) > 4096:
                raise InvalidSource("Text exceeds the size limit.")
            for prop in child:
                if prop not in {"type", "value", "key", "weight"}:
                    issues.append(issue("unsupported_property", f"{child_path}.{prop}", "warning", "Property is not supported."))
            child_key_value: object = child.get("key")
            if child_key_value is not None and not isinstance(child_key_value, str):
                issues.append(issue("invalid_key", f"{child_path}.key", "warning", "Key must be a string or null."))
            text_kind: Literal["text", "title", "caption"] = {"Text": "text", "Title": "title", "Caption": "caption"}[str(child_type)]
            text_node: TextNode = {"kind": text_kind, "value": value}
            weight: object = child.get("weight")
            if weight in ("normal", "medium", "semibold", "bold"):
                text_node["weight"] = weight
            elif "weight" in child:
                issues.append(issue("invalid_property", f"{child_path}.weight", "warning", "Weight is not supported."))
            nodes.append(text_node)
        elif child_type == "Table":
            if not isinstance(child.get("children"), list):
                issues.append(issue("unsupported_child", child_path, "error", "Table children must be an array."))
                nodes.append({"kind": "problem", "message": "This table could not be displayed."})
            else:
                table, table_issues = validate_table(child, child_path)
                nodes.append(table)
                issues.extend(table_issues)
        elif child_type == "Badge":
            label: object = child.get("label")
            if not isinstance(label, str):
                issues.append(issue("unsupported_child", child_path, "error", "Badge requires a string label."))
                nodes.append({"kind": "problem", "message": "This item could not be displayed."})
                continue
            if len(label) > 4096:
                raise InvalidSource("Badge label exceeds the size limit.")
            for prop in child:
                if prop not in {"type", "label", "key"}:
                    issues.append(issue("unsupported_property", f"{child_path}.{prop}", "warning", "Property is not supported."))
            if child.get("key") is not None and not isinstance(child.get("key"), str):
                issues.append(issue("invalid_key", f"{child_path}.key", "warning", "Key must be a string or null."))
            nodes.append({"kind": "badge", "label": label})
        elif child_type == "Divider":
            for prop in child:
                if prop not in {"type", "key"}:
                    issues.append(issue("unsupported_property", f"{child_path}.{prop}", "warning", "Property is not supported."))
            if child.get("key") is not None and not isinstance(child.get("key"), str):
                issues.append(issue("invalid_key", f"{child_path}.key", "warning", "Key must be a string or null."))
            nodes.append({"kind": "divider"})
        elif not isinstance(child.get("children"), list):
            issues.append(issue("unsupported_child", child_path, "error", "Container children must be an array."))
            nodes.append({"kind": "problem", "message": "This item could not be displayed."})
        else:
            nested, nested_issues = validate_container(child, child_path, str(child_type))
            nodes.append(nested)
            issues.extend(nested_issues)
    container: ContainerNode = {"kind": kinds[component], "children": nodes}
    if component in ("Row", "Col", "ListViewItem") and "gap" in data:
        gap: object = data["gap"]
        if isinstance(gap, int) and not isinstance(gap, bool) and 0 <= gap <= 8:
            container["gap"] = gap
        else:
            issues.append(issue("invalid_property", f"{path}.gap", "warning", "Gap must be an integer from 0 to 8."))
    return container, issues


def count_nodes(node: Node) -> int:
    if node["kind"] in ("text", "title", "caption", "badge", "divider", "problem"):
        return 1
    if node["kind"] == "table":
        return 1 + sum(1 + sum(1 + sum(count_nodes(child) for child in cell["children"]) for cell in row["cells"]) for row in node["rows"])
    return 1 + sum(count_nodes(child) for child in node["children"])



def validate_table(data: dict[str, object], path: str) -> tuple[TableNode, list[Issue]]:
    rows_value: object = data["children"]
    if not isinstance(rows_value, list):
        raise InvalidSource("Table children must be an array.")
    if len(rows_value) > 100:
        raise InvalidSource("Table exceeds the row limit.")
    issues: list[Issue] = []
    rows: list[TableRow] = []
    for prop in data:
        if prop not in {"type", "children", "key"}:
            issues.append(issue("unsupported_property", f"{path}.{prop}", "warning", "Property is not supported."))
    table_key: object = data.get("key")
    if table_key is not None and not isinstance(table_key, str):
        issues.append(issue("invalid_key", f"{path}.key", "warning", "Key must be a string or null."))
    row_keys: set[str] = set()
    for row_index, row in enumerate(rows_value):
        row_path: str = f"{path}.children[{row_index}]"
        if not isinstance(row, dict) or row.get("type") != "Table.Row" or not isinstance(row.get("children"), list):
            issues.append(issue("invalid_table_row", row_path, "error", "Table row must contain a children array."))
            rows.append({"header": False, "cells": [{"children": [{"kind": "problem", "message": "This row could not be displayed."}]}]})
            continue
        if duplicate_table_key(row, row_keys, row_path, issues):
            rows.append({"header": False, "cells": [{"children": [{"kind": "problem", "message": "This row could not be displayed."}]}]})
            continue
        header_value: object = row.get("header", False)
        header: bool = header_value if isinstance(header_value, bool) else False
        if not isinstance(header_value, bool):
            issues.append(issue("invalid_property", f"{row_path}.header", "warning", "Header must be a boolean."))
        for prop in row:
            if prop not in {"type", "children", "key", "header"}:
                issues.append(issue("unsupported_property", f"{row_path}.{prop}", "warning", "Property is not supported."))
        row_children: list[object] = row["children"]
        if len(row_children) > 20:
            raise InvalidSource("Table row exceeds the 20-column limit.")
        cells: list[TableCell] = []
        cell_keys: set[str] = set()
        for cell_index, cell in enumerate(row_children):
            cell_path: str = f"{row_path}.children[{cell_index}]"
            if not isinstance(cell, dict) or cell.get("type") != "Table.Cell" or not isinstance(cell.get("children"), list):
                issues.append(issue("invalid_table_cell", cell_path, "error", "Table cell must contain a children array."))
                cells.append({"children": [{"kind": "problem", "message": "This cell could not be displayed."}]})
                continue
            if duplicate_table_key(cell, cell_keys, cell_path, issues):
                cells.append({"children": [{"kind": "problem", "message": "This cell could not be displayed."}]})
                continue
            cell_data: dict[str, object] = {"type": "Col", "children": cell["children"]}
            content, cell_issues = validate_container(cell_data, cell_path, "Col")
            issues.extend(cell_issues)
            safe_cell: TableCell = {"children": content["children"]}
            align: object = cell.get("align")
            if align in ("start", "center", "end"):
                safe_cell["align"] = align
            elif "align" in cell:
                issues.append(issue("invalid_property", f"{cell_path}.align", "warning", "Cell alignment is not supported."))
            for prop in cell:
                if prop not in {"type", "children", "key", "align"}:
                    issues.append(issue("unsupported_property", f"{cell_path}.{prop}", "warning", "Property is not supported."))
            cells.append(safe_cell)
        rows.append({"header": header, "cells": cells})
    return {"kind": "table", "rows": rows}, issues


def duplicate_table_key(data: dict[str, object], keys: set[str], path: str, issues: list[Issue]) -> bool:
    key: object = data.get("key")
    if isinstance(key, str):
        if len(key) > 128:
            raise InvalidSource("Key exceeds the size limit.")
        if key in keys:
            issues.append(issue("duplicate_key", path, "error", "Sibling key is duplicated."))
            return True
        keys.add(key)
    elif key is not None:
        issues.append(issue("invalid_key", f"{path}.key", "warning", "Key must be a string or null."))
    return False
