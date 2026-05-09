from __future__ import annotations

import re

from indexing.parsers.common import node_text, tree_sitter_parser


BACKEND_ROUTE_DECORATOR_PATTERN = re.compile(
    r"@(?P<router>[A-Za-z_][A-Za-z0-9_]*)\.(?P<method>get|post|put|delete|patch)\(\s*(?P<args>[^\n)]*['\"](?P<route>[^'\"]+)['\"][^\n)]*)\)",
    re.IGNORECASE,
)
BACKEND_ROUTE_DECORATOR_START_PATTERN = re.compile(
    r"@(?P<router>[A-Za-z_][A-Za-z0-9_]*)\.(?P<method>get|post|put|delete|patch|route)\s*\(",
    re.IGNORECASE,
)
BACKEND_HANDLER_PATTERN = re.compile(r"(?:async\s+)?def\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(")
BACKEND_RESPONSE_KEY_PATTERN = re.compile(r"['\"](?P<key>[A-Za-z_][A-Za-z0-9_]*)['\"]\s*:")
JS_RESPONSE_KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9_$])(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:")
CSHARP_ANONYMOUS_OBJECT_KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9_$])(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")
DJANGO_URL_PATTERN = re.compile(
    r"\b(?P<kind>path|re_path)\(\s*(?:r)?['\"](?P<route>[^'\"]+)['\"]\s*,\s*(?P<handler>[A-Za-z_][A-Za-z0-9_\.]*)",
    re.IGNORECASE,
)
EXPRESS_ROUTE_PATTERN = re.compile(
    r"\b(?P<router>app|router|[A-Za-z_][A-Za-z0-9_]*)\.(?P<method>get|post|put|delete|patch|all)\(\s*[`'\"](?P<route>/[^`'\"]+)[`'\"]\s*,\s*(?P<handler>[A-Za-z_][A-Za-z0-9_]*)?",
    re.IGNORECASE,
)
CSHARP_MINIMAL_API_PATTERN = re.compile(
    r"\b(?P<router>app|endpoints|group|[A-Za-z_][A-Za-z0-9_]*)\.Map(?P<method>Get|Post|Put|Delete|Patch)\(\s*\"(?P<route>/[^\"]*)\"\s*,\s*(?P<handler>[A-Za-z_][A-Za-z0-9_]*)?",
    re.IGNORECASE,
)
CSHARP_ROUTE_ATTR_PATTERN = re.compile(r"\[(?P<name>Route|HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch)(?:\s*\(\s*\"(?P<route>[^\"]*)\"[^\)]*\))?\]", re.IGNORECASE)
CSHARP_CLASS_PATTERN = re.compile(r"(?:public\s+|internal\s+|sealed\s+|partial\s+|abstract\s+)*class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
CSHARP_METHOD_PATTERN = re.compile(r"\s*(?:public|internal|private|protected)\s+(?:async\s+)?(?P<return_type>Task<[^>]+>|Task|ActionResult<[^>]+>|IActionResult|Results<[^>]+>|[A-Za-z_][A-Za-z0-9_<>,\[\]\?]*)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(", re.IGNORECASE)
CSHARP_RECORD_PATTERN = re.compile(r"(?:public\s+|internal\s+)?record\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:\((?P<params>[^;{]*)\)|\{(?P<body>[\s\S]*?)\})", re.IGNORECASE)
CSHARP_DTO_CLASS_PATTERN = re.compile(r"(?:public\s+|internal\s+)?(?:class|record)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)[^{;]*\{(?P<body>[\s\S]*?)(?=\n\s*(?:public\s+|internal\s+)?(?:class|record|interface|struct)\s+[A-Za-z_]|\Z)", re.IGNORECASE)
CSHARP_PROPERTY_PATTERN = re.compile(r"(?:public|internal)\s+(?P<type>[A-Za-z_][A-Za-z0-9_<>,\[\]\?]*)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{", re.IGNORECASE)
CSHARP_RECORD_PARAM_PATTERN = re.compile(r"(?P<type>[A-Za-z_][A-Za-z0-9_<>,\[\]\?]*)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
PYDANTIC_CLASS_PATTERN = re.compile(r"class\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\([^)]*(?:BaseModel|Schema|Model)[^)]*\):(?P<body>[\s\S]*?)(?=\nclass\s|\ndef\s|\n@|\Z)")
PYDANTIC_FIELD_PATTERN = re.compile(r"^\s+(?P<field>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<type>[^=\n]+)", re.MULTILINE)
RESPONSE_MODEL_PATTERN = re.compile(r"response_model\s*=\s*(?:list\s*\[\s*)?(?P<model>[A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
ROUTE_METHODS_PATTERN = re.compile(r"methods\s*=\s*\[(?P<methods>[^\]]+)\]", re.IGNORECASE)
FRONTEND_ROUTE_USAGE_PATTERN = re.compile(
    r"(?:apiClient|axios)\.(?P<method>get|post|put|delete|patch)\(\s*[`'\"](?P<route>/[^`'\"]+)[`'\"]|fetch\(\s*[`'\"](?P<fetch_route>/[^`'\"]+)[`'\"]",
    re.IGNORECASE,
)
FRONTEND_ROUTE_CONSTANT_PATTERN = re.compile(
    r"(?:const|let|var)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*[`'\"](?P<route>/[^`'\"]+)[`'\"]"
)
FRONTEND_ACCESS_KEY_PATTERN = re.compile(r"(?:response\.data|\bdata|\bpayload|\bresult)\.(?P<key>[A-Za-z_][A-Za-z0-9_]*)|\.response\.(?P<response_key>[A-Za-z_][A-Za-z0-9_]*)")
NESTED_ACCESS_PATTERN = re.compile(r"(?:response\.data|\bdata|\bpayload|\bresult)\.(?P<path>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
ARRAY_CALLBACK_PATTERN = re.compile(r"(?:response\.data|\bdata|\bpayload|\bresult)\.(?P<parent>[A-Za-z_][A-Za-z0-9_]*)\.(?:map|forEach|filter)\s*\(\s*\(?(?P<item>[A-Za-z_][A-Za-z0-9_]*)\)?\s*=>(?P<body>[\s\S]{0,900}?)(?:\)\s*[;,\n]|\Z)")
CHART_DATAKEY_PATTERN = re.compile(r"\b(?P<parent>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{?(?:response\.data|\bdata|\bpayload|\bresult)\.(?P<source>[A-Za-z_][A-Za-z0-9_]*)\}[\s\S]{0,1200}?dataKey\s*=\s*['\"](?P<key>[A-Za-z_][A-Za-z0-9_]*)['\"]")
JSON_RESPONSE_PATTERN = re.compile(r"json\((?P<body>\{[\s\S]{0,2000}?\})\)", re.IGNORECASE)
FUNCTION_NAME_PATTERN = re.compile(r"(?:export\s+)?(?:const|let|var)\s+(?P<const_name>[A-Za-z_][A-Za-z0-9_]*)(?:\s*:\s*[^=]+?)?\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_][A-Za-z0-9_]*)?(?:\s*:\s*[^=]+?)?\s*=>|(?:export\s+)?(?:async\s+)?function\s+(?P<func_name>[A-Za-z_][A-Za-z0-9_]*)")
STRING_LITERAL_PATTERN = re.compile(r"^\s*(['\"])(?P<value>/[^'\"]*)\1")


def iter_backend_route_decorators(source: str) -> list[dict[str, object]]:
    """Return balanced FastAPI/Flask-style route decorators without crossing into later decorators."""
    decorators: list[dict[str, object]] = []
    for match in BACKEND_ROUTE_DECORATOR_START_PATTERN.finditer(source):
        open_index = match.end() - 1
        close_index = open_index + 1
        depth = 1
        quote = ""
        while close_index < len(source) and depth > 0:
            char = source[close_index]
            previous = source[close_index - 1] if close_index > 0 else ""
            if quote:
                if char == quote and previous != "\\":
                    quote = ""
            elif char in {"'", '"'}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            close_index += 1
        if depth != 0:
            continue
        args = source[open_index + 1:close_index - 1]
        route_match = STRING_LITERAL_PATTERN.search(args)
        if route_match is None:
            continue
        route = route_match.group("value")
        if "\n" in route or "@" in route or not route.startswith("/"):
            continue
        method = match.group("method")
        if method.lower() == "route":
            methods_match = ROUTE_METHODS_PATTERN.search(args)
            methods_text = methods_match.group("methods") if methods_match is not None else ""
            methods = re.findall(r"['\"](?P<method>GET|POST|PUT|DELETE|PATCH)['\"]", methods_text, flags=re.IGNORECASE)
            method = methods[0] if methods else "GET"
        decorators.append(
            {
                "router": match.group("router"),
                "method": method,
                "args": args,
                "route": route,
                "end": close_index,
            }
        )
    return decorators


def iter_backend_route_mappings(source: str) -> list[dict[str, object]]:
    """Return Django-style path/re_path route mappings."""
    mappings: list[dict[str, object]] = []
    for match in DJANGO_URL_PATTERN.finditer(source):
        route = match.group("route") or ""
        if not route:
            continue
        if match.group("kind").lower() == "re_path":
            route = route.lstrip("^").rstrip("$")
        route = "/" + route.strip().strip("/")
        if "<" in route or "(" in route:
            route = re.sub(r"<(?:[^:>]+:)?(?P<name>[^>]+)>", r"{\g<name>}", route)
        mappings.append(
            {
                "router": match.group("kind"),
                "method": "GET",
                "args": match.group(0),
                "route": route.rstrip("/") or "/",
                "handler": match.group("handler").rsplit(".", 1)[-1],
                "end": match.end(),
            }
        )
    return mappings


def iter_express_route_handlers(source: str) -> list[dict[str, object]]:
    """Return Express/Koa-style app/router route handlers from JS/TS backend files."""
    handlers: list[dict[str, object]] = []
    for match in EXPRESS_ROUTE_PATTERN.finditer(source):
        route = match.group("route") or ""
        if not route:
            continue
        method = match.group("method").upper()
        handlers.append(
            {
                "router": match.group("router"),
                "method": "ANY" if method == "ALL" else method,
                "args": match.group(0),
                "route": route,
                "handler": match.group("handler") or "",
                "end": match.end(),
            }
        )
    return handlers


def _normalize_csharp_route(route: str, class_name: str = "") -> str:
    value = str(route or "").strip()
    if class_name:
        controller = class_name[:-10] if class_name.endswith("Controller") else class_name
        value = re.sub(r"\[controller\]", controller, value, flags=re.IGNORECASE)
    value = value.replace("{id:int}", "{id}")
    return ("/" + value.strip().strip("/")).lower()


def _json_field_name(name: str) -> str:
    token = str(name or "").strip()
    if not token:
        return ""
    return token[:1].lower() + token[1:]


def _csharp_model_name_from_type(type_hint: str) -> tuple[str, bool]:
    hint = str(type_hint or "").strip().strip("?")
    wrappers = ("Task", "ActionResult", "Ok", "Created", "JsonHttpResult")
    changed = True
    while changed:
        changed = False
        for wrapper in wrappers:
            match = re.fullmatch(rf"{wrapper}<(?P<inner>.+)>", hint)
            if match:
                hint = match.group("inner").strip()
                changed = True
    results_match = re.fullmatch(r"Results<(?P<inner>.+)>", hint)
    if results_match:
        for part in results_match.group("inner").split(","):
            model, is_array = _csharp_model_name_from_type(part.strip())
            if model:
                return model, is_array
    collection_match = re.fullmatch(r"(?:IEnumerable|List|IReadOnlyList|Collection)<(?P<inner>[A-Za-z_][A-Za-z0-9_]*)>", hint)
    if collection_match:
        return collection_match.group("inner"), True
    array_match = re.fullmatch(r"(?P<inner>[A-Za-z_][A-Za-z0-9_]*)\[\]", hint)
    if array_match:
        return array_match.group("inner"), True
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", hint) and hint not in {"IActionResult", "IResult", "Task", "string", "int", "long", "bool", "double", "decimal"}:
        return hint, False
    return "", False


def csharp_model_shapes(source: str) -> dict[str, dict[str, object]]:
    shapes: dict[str, dict[str, object]] = {}
    field_types: dict[str, dict[str, tuple[str, bool]]] = {}
    for record in CSHARP_RECORD_PATTERN.finditer(source):
        model_name = record.group("name")
        params = record.group("params") or ""
        body = record.group("body") or ""
        fields: list[str] = []
        nested_types: dict[str, tuple[str, bool]] = {}
        for prop in CSHARP_RECORD_PARAM_PATTERN.finditer(params):
            field_name = _json_field_name(prop.group("name"))
            if field_name:
                fields.append(field_name)
                nested_model, is_array = _csharp_model_name_from_type(prop.group("type"))
                if nested_model:
                    nested_types[field_name] = (nested_model, is_array)
        for prop in CSHARP_PROPERTY_PATTERN.finditer(body):
            field_name = _json_field_name(prop.group("name"))
            if field_name:
                fields.append(field_name)
                nested_model, is_array = _csharp_model_name_from_type(prop.group("type"))
                if nested_model:
                    nested_types[field_name] = (nested_model, is_array)
        if fields:
            shapes[model_name] = {"fields": sorted(set(fields)), "nested": {}}
            field_types[model_name] = nested_types
    for klass in CSHARP_DTO_CLASS_PATTERN.finditer(source):
        model_name = klass.group("name")
        body = klass.group("body") or ""
        fields = []
        nested_types = {}
        for prop in CSHARP_PROPERTY_PATTERN.finditer(body):
            field_name = _json_field_name(prop.group("name"))
            if field_name:
                fields.append(field_name)
                nested_model, is_array = _csharp_model_name_from_type(prop.group("type"))
                if nested_model:
                    nested_types[field_name] = (nested_model, is_array)
        if fields:
            shapes[model_name] = {"fields": sorted(set(fields)), "nested": {}}
            field_types[model_name] = nested_types
    for model_name, nested_types in field_types.items():
        nested_shapes: dict[str, list[str]] = {}
        for field_name, (nested_model, is_array) in nested_types.items():
            nested = shapes.get(nested_model, {})
            nested_fields = nested.get("fields", []) if isinstance(nested, dict) else []
            if nested_fields:
                nested_shapes[f"{field_name}[]" if is_array else field_name] = list(nested_fields)
        shapes[model_name]["nested"] = nested_shapes
    return shapes


def _combine_routes(prefix: str, route: str, class_name: str = "") -> str:
    parts = [part for part in [prefix, route] if str(part or "").strip()]
    if not parts:
        return "/"
    return _normalize_csharp_route("/".join(part.strip("/") for part in parts), class_name=class_name)


def iter_csharp_route_handlers(source: str) -> list[dict[str, object]]:
    """Return ASP.NET controller/minimal API routes from C# source."""
    handlers: list[dict[str, object]] = []
    for match in CSHARP_MINIMAL_API_PATTERN.finditer(source):
        handlers.append(
            {
                "router": match.group("router"),
                "method": match.group("method").upper(),
                "args": match.group(0),
                "route": _normalize_csharp_route(match.group("route") or ""),
                "handler": match.group("handler") or "",
                "end": match.end(),
                "framework": "aspnet_minimal_api",
            }
        )
    class_matches = list(CSHARP_CLASS_PATTERN.finditer(source))
    for index, class_match in enumerate(class_matches):
        class_name = class_match.group("name") or ""
        class_start = class_match.start()
        class_end = class_matches[index + 1].start() if index + 1 < len(class_matches) else len(source)
        class_prefix = source[max(0, class_start - 1200):class_start]
        class_route = ""
        for attr in CSHARP_ROUTE_ATTR_PATTERN.finditer(class_prefix):
            if attr.group("name").lower() == "route":
                class_route = attr.group("route") or ""
        class_body = source[class_match.end():class_end]
        for method_match in CSHARP_METHOD_PATTERN.finditer(class_body):
            method_name = method_match.group("name") or ""
            method_offset = class_match.end() + method_match.start()
            attr_prefix = source[max(class_match.end(), method_offset - 900):method_offset]
            for attr in CSHARP_ROUTE_ATTR_PATTERN.finditer(attr_prefix):
                attr_name = attr.group("name")
                if attr_name.lower() == "route":
                    continue
                method = attr_name[4:].upper()
                route = _combine_routes(class_route, attr.group("route") or "", class_name=class_name)
                handlers.append(
                    {
                        "router": class_name,
                        "method": method,
                        "args": attr.group(0),
                        "route": route,
                        "handler": method_name,
                        "response_model": _csharp_model_name_from_type(method_match.group("return_type") or "")[0],
                        "end": method_offset + method_match.end() - method_match.start(),
                        "framework": "aspnet_controller",
                    }
                )
    return handlers


def _walk_nodes(node):
    yield node
    for child in node.children:
        yield from _walk_nodes(child)


def _string_node_value(source_bytes: bytes, node) -> str:
    text = node_text(source_bytes, node).strip()
    if len(text) >= 2 and text[0] in {"'", '"', "`"} and text[-1] == text[0]:
        return text[1:-1]
    return text


def _member_expression_parts(source_bytes: bytes, node) -> list[str]:
    if node.type == "identifier":
        return [node_text(source_bytes, node)]
    if node.type == "property_identifier":
        return [node_text(source_bytes, node)]
    if node.type != "member_expression":
        return []
    parts: list[str] = []
    for child in node.children:
        if child.type in {".", "optional_chain"}:
            continue
        child_parts = _member_expression_parts(source_bytes, child)
        if child_parts:
            parts.extend(child_parts)
    return parts


def _frontend_route_constants(source: str) -> dict[str, str]:
    return {
        match.group("name"): match.group("route")
        for match in FRONTEND_ROUTE_CONSTANT_PATTERN.finditer(source)
        if match.group("name") and match.group("route")
    }


def _call_route_from_ast(source_bytes: bytes, node, route_constants: dict[str, str] | None = None) -> dict[str, object] | None:
    function_node = node.child_by_field_name("function")
    arguments_node = node.child_by_field_name("arguments")
    if function_node is None or arguments_node is None:
        return None
    function_text = node_text(source_bytes, function_node)
    method = ""
    if function_node.type == "identifier" and function_text == "fetch":
        method = "fetch"
    elif function_node.type == "member_expression":
        parts = _member_expression_parts(source_bytes, function_node)
        if len(parts) >= 2 and parts[-2] in {"apiClient", "axios"} and parts[-1].lower() in {"get", "post", "put", "delete", "patch"}:
            method = parts[-1].lower()
    if not method:
        return None
    constants = route_constants or {}
    for child in arguments_node.children:
        if child.type in {"string", "template_string"}:
            route = _string_node_value(source_bytes, child)
            if route.startswith("/"):
                return {"method": method, "route": route, "start": node.start_byte, "end": node.end_byte, "parser": "tree_sitter"}
            return None
        if child.type == "identifier":
            constant_name = node_text(source_bytes, child)
            route = constants.get(constant_name, "")
            if route.startswith("/"):
                return {"method": method, "route": route, "start": node.start_byte, "end": node.end_byte, "parser": "tree_sitter"}
    return None


def frontend_route_usages(source: str, language: str = "tsx") -> list[dict[str, object]]:
    source_bytes = source.encode("utf-8")
    parser = tree_sitter_parser(language)
    usages: list[dict[str, object]] = []
    route_constants = _frontend_route_constants(source)
    if parser is not None:
        try:
            tree = parser.parse(source_bytes)
            for node in _walk_nodes(tree.root_node):
                if node.type != "call_expression":
                    continue
                usage = _call_route_from_ast(source_bytes, node, route_constants=route_constants)
                if usage is not None:
                    usages.append(usage)
        except Exception:
            usages = []
    if usages:
        return usages
    for match in FRONTEND_ROUTE_USAGE_PATTERN.finditer(source):
        found_route = match.group("route") or match.group("fetch_route") or ""
        if found_route:
            usages.append(
                {
                    "method": match.group("method") or "fetch",
                    "route": found_route,
                    "start": match.start(),
                    "end": match.end(),
                    "parser": "regex",
                }
            )
    return usages


def response_keys(snippet: str) -> list[str]:
    keys = {match.group("key") for match in BACKEND_RESPONSE_KEY_PATTERN.finditer(snippet) if match.group("key")}
    keys.update(match.group("key") for match in JS_RESPONSE_KEY_PATTERN.finditer(snippet) if match.group("key"))
    if "new {" in snippet:
        keys.update(match.group("key") for match in CSHARP_ANONYMOUS_OBJECT_KEY_PATTERN.finditer(snippet) if match.group("key"))
    return sorted(keys)[:30]


def _model_name_from_type(type_hint: str) -> tuple[str, bool]:
    hint = str(type_hint or "").strip().strip("'\"")
    list_match = re.search(r"(?:list|List|Sequence)\s*\[\s*(?P<model>[A-Za-z_][A-Za-z0-9_]*)\s*\]", hint)
    if list_match is not None:
        return list_match.group("model"), True
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", hint):
        return hint, False
    return "", False


def pydantic_model_shapes(source: str) -> dict[str, dict[str, object]]:
    shapes: dict[str, dict[str, object]] = {}
    field_types: dict[str, dict[str, tuple[str, bool]]] = {}
    for match in PYDANTIC_CLASS_PATTERN.finditer(source):
        fields = []
        nested_types: dict[str, tuple[str, bool]] = {}
        for field in PYDANTIC_FIELD_PATTERN.finditer(match.group("body")):
            field_name = field.group("field")
            if not field_name:
                continue
            fields.append(field_name)
            model_name, is_array = _model_name_from_type(field.group("type"))
            if model_name:
                nested_types[field_name] = (model_name, is_array)
        if fields:
            model_name = match.group("name")
            shapes[model_name] = {"fields": sorted(set(fields)), "nested": {}}
            field_types[model_name] = nested_types
    for model_name, nested_types in field_types.items():
        nested_shapes: dict[str, list[str]] = {}
        for field_name, (nested_model, is_array) in nested_types.items():
            nested = shapes.get(nested_model, {})
            nested_fields = nested.get("fields", []) if isinstance(nested, dict) else []
            if nested_fields:
                nested_shapes[f"{field_name}[]" if is_array else field_name] = list(nested_fields)
        shapes[model_name]["nested"] = nested_shapes
    return shapes


def response_model_name(decorator_args: str) -> str:
    match = RESPONSE_MODEL_PATTERN.search(decorator_args)
    return match.group("model") if match is not None else ""


def balanced_body(snippet: str, start: int, opener: str, closer: str) -> str:
    depth = 1
    end = start
    while end < len(snippet) and depth > 0:
        if snippet[end] == opener:
            depth += 1
        elif snippet[end] == closer:
            depth -= 1
        end += 1
    return snippet[start:end - 1]


def nested_response_keys(snippet: str) -> dict[str, list[str]]:
    nested: dict[str, list[str]] = {}
    for match in re.finditer(r"['\"](?P<parent>[A-Za-z_][A-Za-z0-9_]*)['\"]\s*:\s*\{", snippet):
        parent = match.group("parent")
        body = balanced_body(snippet, match.end(), "{", "}")
        keys = response_keys(body)
        if keys:
            nested[parent] = keys
    for match in re.finditer(r"['\"](?P<parent>[A-Za-z_][A-Za-z0-9_]*)['\"]\s*:\s*\[\s*\{", snippet):
        parent = f"{match.group('parent')}[]"
        body = balanced_body(snippet, match.end(), "{", "}")
        keys = response_keys(body)
        if keys:
            nested[parent] = keys
    return nested


def returned_payload_source(handler_source: str) -> str:
    direct_return = re.search(r"return\s+(?P<body>\{)", handler_source)
    if direct_return is not None:
        return handler_source[direct_return.start():]
    return_match = re.search(r"return\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b", handler_source)
    if return_match is None:
        return handler_source
    variable_name = return_match.group("name")
    assignment = re.search(rf"\b{re.escape(variable_name)}\s*=\s*\{{", handler_source)
    if assignment is None:
        return handler_source
    body = balanced_body(handler_source, assignment.end(), "{", "}")
    return "{" + body + "}"


def consumer_keys(snippet: str) -> tuple[list[str], list[str]]:
    snippet = snippet.replace("?.", ".")
    flat = {
        access.group("key") or access.group("response_key")
        for access in FRONTEND_ACCESS_KEY_PATTERN.finditer(snippet)
        if access.group("key") or access.group("response_key")
    }
    nested = {access.group("path") for access in NESTED_ACCESS_PATTERN.finditer(snippet) if access.group("path")}
    for access in ARRAY_CALLBACK_PATTERN.finditer(snippet):
        parent = access.group("parent")
        item = access.group("item")
        body = access.group("body") or ""
        if parent and item:
            for key_match in re.finditer(rf"\b{re.escape(item)}\.(?P<key>[A-Za-z_][A-Za-z0-9_]*)", body):
                nested.add(f"{parent}[].{key_match.group('key')}")
    for access in CHART_DATAKEY_PATTERN.finditer(snippet):
        source = access.group("source")
        key = access.group("key")
        if source and key:
            nested.add(f"{source}[].{key}")
    for chart_data_match in re.finditer(r"data\s*=\s*\{?\s*(?:response\.data|\bdata|\bpayload|\bresult)\.(?P<source>[A-Za-z_][A-Za-z0-9_]*)\s*\}?", snippet):
        source = chart_data_match.group("source")
        chart_window = snippet[chart_data_match.end():chart_data_match.end() + 12000]
        for key_match in re.finditer(r"dataKey\s*=\s*['\"](?P<key>[A-Za-z_][A-Za-z0-9_]*)['\"]", chart_window):
            nested.add(f"{source}[].{key_match.group('key')}")
    alias_parents: dict[str, str] = {}
    data_aliases = {"data", "payload", "result"}
    for match in re.finditer(r"(?:const|let|var)\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:response\.data|\bdata|\bpayload|\bresult)\b(?!\.)", snippet):
        data_aliases.add(match.group("alias"))
    data_roots = "|".join(re.escape(alias) for alias in sorted(data_aliases))
    for match in re.finditer(rf"(?:const|let|var)\s+\{{(?P<fields>[^}}]+)\}}\s*=\s*(?:response\.data|\b(?:{data_roots}))\b", snippet):
        for raw_field in match.group("fields").split(","):
            token = raw_field.strip()
            if not token:
                continue
            if ":" in token:
                parent, alias = [part.strip() for part in token.split(":", 1)]
            else:
                parent = alias = token
            if parent and alias:
                flat.add(parent)
                alias_parents[alias] = parent
    for root_alias, root_parent in list(alias_parents.items()):
        for match in re.finditer(rf"(?:const|let|var)\s+\{{(?P<fields>[^}}]+)\}}\s*=\s*{re.escape(root_alias)}\b", snippet):
            for raw_field in match.group("fields").split(","):
                token = raw_field.strip()
                if not token:
                    continue
                if ":" in token:
                    child, alias = [part.strip() for part in token.split(":", 1)]
                else:
                    child = alias = token
                if child and alias:
                    nested.add(f"{root_parent}.{child}")
                    alias_parents[alias] = f"{root_parent}.{child}"
    for match in re.finditer(rf"(?:const|let|var)\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:response\.data|\b(?:{data_roots}))\.(?P<parent>[A-Za-z_][A-Za-z0-9_]*)", snippet):
        flat.add(match.group("parent"))
        alias_parents[match.group("alias")] = match.group("parent")
    for alias, parent in alias_parents.items():
        for match in re.finditer(rf"\b{re.escape(alias)}\.(?P<child>[A-Za-z_][A-Za-z0-9_]*)", snippet):
            nested.add(f"{parent}.{match.group('child')}")
        for match in re.finditer(rf"\b{re.escape(alias)}\.(?:map|forEach|filter)\s*\(\s*\(?(?P<item>[A-Za-z_][A-Za-z0-9_]*)\)?\s*=>(?P<body>[\s\S]{{0,1000}}?)(?:\)\s*[;,\n]|\Z)", snippet):
            body = match.group("body") or ""
            for key_match in re.finditer(rf"\b{re.escape(match.group('item'))}\.(?P<key>[A-Za-z_][A-Za-z0-9_]*)", body):
                nested.add(f"{parent}[].{key_match.group('key')}")
        for data_match in re.finditer(rf"data\s*=\s*\{{?\s*{re.escape(alias)}\s*\}}?", snippet):
            chart_window = snippet[data_match.end():data_match.end() + 1600]
            for key_match in re.finditer(r"dataKey\s*=\s*['\"](?P<key>[A-Za-z_][A-Za-z0-9_]*)['\"]", chart_window):
                nested.add(f"{parent}[].{key_match.group('key')}")
    flat -= {"filter", "forEach", "length", "map", "slice", "forecast_source", "no_sales_record", "skipped", "toLocaleString", "type", "updated"}
    nested = {
        path
        for path in nested
        if path.rsplit(".", 1)[-1] not in {"filter", "forEach", "length", "map", "slice", "toLocaleString"}
    }
    return sorted(flat)[:30], sorted(nested)[:30]


def normalize_route(route: str) -> str:
    normalized = "/" + str(route or "").strip().strip("/")
    if normalized.startswith("/api/"):
        normalized = normalized[4:]
    return normalized.rstrip("/") or "/"


def route_matches(found_route: str, requested_route: str) -> bool:
    return not requested_route or normalize_route(found_route) == normalize_route(requested_route)


def enclosing_function_name(source: str, offset: int) -> str:
    prefix = source[max(0, offset - 5000):offset]
    matches = list(FUNCTION_NAME_PATTERN.finditer(prefix))
    return (matches[-1].group("const_name") or matches[-1].group("func_name")) if matches else ""


def function_call_pattern(function_name: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(function_name) + r"\s*\(")
