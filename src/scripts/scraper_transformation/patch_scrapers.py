#!/usr/bin/env python3
"""
patch_scrapers.py — AST-based transform: sync requests → async httpx.

Uses AST node positions (lineno, end_lineno, col_offset, end_col_offset)
to make precise source-level replacements, preserving formatting and comments.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


class SourceRewriter:
    """Collects edits (indexed by line/col) and applies them in reverse order."""

    def __init__(self, source: str):
        self.source = source
        self.lines = source.splitlines(keepends=True)
        # Each edit: (start_line, start_col, end_line, end_col, replacement)
        # Lines are 1-indexed (matching ast), cols are 0-indexed
        self._edits: list[tuple[int, int, int, int, str]] = []

    def replace_node(self, node: ast.AST, replacement: str):
        """Replace an AST node's source span with replacement text."""
        self._edits.append(
            (
                node.lineno,
                node.col_offset,
                node.end_lineno,
                node.end_col_offset,
                replacement,
            )
        )

    def replace_range(
        self,
        start_line: int,
        start_col: int,
        end_line: int,
        end_col: int,
        replacement: str,
    ):
        self._edits.append((start_line, start_col, end_line, end_col, replacement))

    def delete_statement(self, node: ast.stmt):
        """Delete an entire statement including its line(s) and trailing newline."""
        start = node.lineno
        end = node.end_lineno
        # Delete entire lines
        for lineno in range(start, end + 1):
            self.lines[lineno - 1] = ""

    def apply(self) -> str:
        """Apply all edits and return new source."""
        # Sort edits in reverse order so positions don't shift
        edits = sorted(self._edits, key=lambda e: (e[0], e[1]), reverse=True)
        lines = list(self.lines)

        for start_line, start_col, end_line, end_col, replacement in edits:
            if start_line == end_line:
                # Single-line edit
                ln = lines[start_line - 1]
                lines[start_line - 1] = ln[:start_col] + replacement + ln[end_col:]
            else:
                # Multi-line edit: combine the affected lines, then splice
                combined = ""
                for i in range(start_line - 1, end_line):
                    combined += lines[i]

                # Calculate positions in the combined string
                before = ""
                for i in range(start_line - 1, start_line - 1):
                    before += lines[i]
                before = lines[start_line - 1][:start_col]

                last_line = lines[end_line - 1]
                after = last_line[end_col:]

                new_content = before + replacement + after
                lines[start_line - 1] = new_content
                for i in range(start_line, end_line):
                    lines[i] = ""

        return "".join(lines)


def transform_source(source: str) -> tuple[str, list[str]]:
    """Transform a single source file. Returns (new_source, warnings)."""
    warnings: list[str] = []

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return source, [f"Parse error: {e}"]

    # --- Analysis pass ---
    has_requests_import = False
    has_time_import = False
    has_from_time_import_sleep = False
    uses_time_sleep = False
    uses_time_other = False
    httpadapter_classes: dict[str, ast.ClassDef] = {}
    session_var_names: set[str] = set()
    init_session_attr: str | None = None
    methods_needing_async: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "requests":
                    has_requests_import = True
                if alias.name == "time":
                    has_time_import = True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "requests" or (
                node.module and node.module.startswith("requests.")
            ):
                has_requests_import = True
            if node.module == "time":
                for alias in node.names:
                    if alias.name == "sleep":
                        has_from_time_import_sleep = True

    if not has_requests_import:
        return source, ["No 'import requests' found — skipping"]

    # Find HTTPAdapter subclasses
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if _name_contains(base, "HTTPAdapter"):
                    httpadapter_classes[node.name] = node

    # Find session variables
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            if _is_requests_session(node.value):
                tgt = node.targets[0]
                if isinstance(tgt, ast.Name):
                    session_var_names.add(tgt.id)
                elif (
                    isinstance(tgt, ast.Attribute)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == "self"
                ):
                    init_session_attr = tgt.attr
                    session_var_names.add(f"self.{tgt.attr}")

    # Find time.sleep / sleep usage
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _is_attr_call(node, "time", "sleep"):
                uses_time_sleep = True
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id == "sleep"
                and has_from_time_import_sleep
            ):
                uses_time_sleep = True
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "time" and node.attr != "sleep":
                uses_time_other = True

    # Find helper methods that receive a session param and call HTTP methods on it
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name != "__init__"
            and node.name != "fetch"
        ):
            # Check if any param is named s/session
            param_names = {a.arg for a in node.args.args}
            has_session_param = bool(param_names & {"s", "session"})
            # Check if method uses self._session
            uses_session_attr = init_session_attr and _body_uses_attr(
                node, "self", init_session_attr
            )
            if has_session_param or uses_session_attr:
                methods_needing_async.add(node.name)

    # --- Build edits using line-based approach with AST guidance ---
    # We'll do targeted string replacements using AST node positions

    lines = source.splitlines(keepends=True)
    # Collect line-level operations
    delete_lines: set[int] = set()  # 1-indexed lines to remove entirely
    line_replacements: dict[int, str] = {}  # 1-indexed line -> replacement

    # We need to track multiline statement ranges too
    delete_ranges: list[tuple[int, int]] = []  # (start, end) 1-indexed inclusive

    # 1. Handle imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "requests":
                    # Replace the whole import statement
                    _mark_stmt_replace(
                        node,
                        lines,
                        delete_ranges,
                        line_replacements,
                        _get_stmt_text(node, lines),
                        "import httpx",
                    )
                if alias.name == "time" and uses_time_sleep and not uses_time_other:
                    _mark_stmt_replace(
                        node,
                        lines,
                        delete_ranges,
                        line_replacements,
                        _get_stmt_text(node, lines),
                        "import asyncio",
                    )

        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("requests.adapters"):
                # Remove entirely
                for ln in range(node.lineno, node.end_lineno + 1):
                    delete_lines.add(ln)

            elif node.module and node.module.startswith("requests.exceptions"):
                # Replace with httpx equivalents
                old_text = _get_stmt_text(node, lines)
                new_text = old_text.replace(
                    "from requests.exceptions import", "from httpx import"
                )
                new_text = _replace_exception_names(new_text)
                _mark_stmt_replace(
                    node, lines, delete_ranges, line_replacements, old_text, new_text
                )

            elif node.module == "time":
                for alias in node.names:
                    if alias.name == "sleep":
                        if uses_time_sleep:
                            old_text = _get_stmt_text(node, lines)
                            _mark_stmt_replace(
                                node,
                                lines,
                                delete_ranges,
                                line_replacements,
                                old_text,
                                "import asyncio",
                            )

    # 2. Remove HTTPAdapter subclass definitions
    for cls_name, cls_node in httpadapter_classes.items():
        for ln in range(cls_node.lineno, cls_node.end_lineno + 1):
            delete_lines.add(ln)

    # 3. Process Source class body
    source_class = _find_source_class(tree)
    if source_class:
        _process_class(
            source_class,
            lines,
            delete_lines,
            delete_ranges,
            line_replacements,
            session_var_names,
            httpadapter_classes,
            methods_needing_async,
            init_session_attr,
            source,
        )

    # 4. Process module-level functions that use requests
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name not in ("fetch",):
            _process_module_function(
                node,
                lines,
                delete_lines,
                delete_ranges,
                line_replacements,
                session_var_names,
                source,
            )

    # --- Apply edits ---
    result_lines = []
    need_asyncio_import = uses_time_sleep and has_time_import and uses_time_other
    asyncio_inserted = False
    i = 1  # 1-indexed
    while i <= len(lines):
        # line_replacements take priority over deletions
        if i in line_replacements:
            pass  # will be handled below
        elif i in delete_lines:
            i += 1
            continue
        else:
            # Check if this line starts a delete range
            in_range = False
            for rs, re_ in delete_ranges:
                if rs <= i <= re_:
                    in_range = True
                    break
            if in_range:
                i += 1
                continue

        line = line_replacements.get(i, lines[i - 1])
        result_lines.append(line)

        # Insert asyncio import after time import if needed
        if need_asyncio_import and not asyncio_inserted:
            stripped = lines[i - 1].strip()
            if stripped.startswith("import time"):
                result_lines.append("import asyncio\n")
                asyncio_inserted = True

        i += 1

    result = "".join(result_lines)
    # Clean up excessive blank lines
    result = re.sub(r"\n{4,}", "\n\n\n", result)

    # --- Final text-level cleanup for remaining requests references ---
    # These catch edge cases the AST transform doesn't handle structurally:
    # type annotations, lowercase session(), context managers, bare exception refs
    result = _final_requests_cleanup(result)

    return result, warnings


def _process_class(
    cls: ast.ClassDef,
    lines: list[str],
    delete_lines: set[int],
    delete_ranges: list[tuple[int, int]],
    line_replacements: dict[int, str],
    session_var_names: set[str],
    adapter_classes: dict[str, ast.ClassDef],
    methods_needing_async: set[str],
    init_session_attr: str | None,
    full_source: str,
):
    """Process the Source class: transform methods, session creation, HTTP calls."""

    for node in ast.iter_child_nodes(cls):
        if isinstance(node, ast.FunctionDef):
            _process_method(
                node,
                lines,
                delete_lines,
                delete_ranges,
                line_replacements,
                session_var_names,
                adapter_classes,
                methods_needing_async,
                init_session_attr,
                full_source,
            )


def _process_module_function(
    func: ast.FunctionDef,
    lines: list[str],
    delete_lines: set[int],
    delete_ranges: list[tuple[int, int]],
    line_replacements: dict[int, str],
    session_var_names: set[str],
    full_source: str,
):
    """Process module-level functions for bare requests.get/post calls."""
    has_requests_call = False
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and _is_bare_requests_call(node):
            has_requests_call = True
            _transform_bare_request(node, lines, line_replacements)
        if isinstance(node, ast.Call) and _is_attr_call(node, "time", "sleep"):
            _replace_time_sleep(node, lines, line_replacements)

    # Make the function async if it had requests calls
    if has_requests_call:
        line = lines[func.lineno - 1]
        if "async def" not in line:
            line_replacements[func.lineno] = line.replace(
                f"def {func.name}(", f"async def {func.name}(", 1
            )


def _process_method(
    method: ast.FunctionDef,
    lines: list[str],
    delete_lines: set[int],
    delete_ranges: list[tuple[int, int]],
    line_replacements: dict[int, str],
    session_var_names: set[str],
    adapter_classes: dict[str, ast.ClassDef],
    methods_needing_async: set[str],
    init_session_attr: str | None,
    full_source: str,
):
    """Process a single method within Source class."""

    # Make fetch() and helper methods async
    if method.name == "fetch" or method.name in methods_needing_async:
        line = lines[method.lineno - 1]
        if "async def" not in line:
            line_replacements[method.lineno] = line.replace(
                f"def {method.name}(", f"async def {method.name}(", 1
            )

    # Walk all nodes in the method body
    for node in ast.walk(method):
        # --- requests.Session() → httpx.AsyncClient(...) ---
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and _is_requests_session(node.value)
        ):
            _transform_session_assign(
                node,
                lines,
                delete_lines,
                delete_ranges,
                line_replacements,
                adapter_classes,
                method,
                full_source,
            )
            continue

        # --- s.mount(...) → delete ---
        if isinstance(node, (ast.Expr,)) and isinstance(node.value, ast.Call):
            if _is_method_call_on(node.value, session_var_names, "mount"):
                for ln in range(node.lineno, node.end_lineno + 1):
                    delete_lines.add(ln)
                continue

        # --- s.get(...) / s.post(...) etc → await s.get(...) ---
        if isinstance(node, ast.Call) and _is_session_http_call(
            node, session_var_names
        ):
            _add_await_before_call(node, lines, line_replacements)

        # --- requests.get(...) / requests.post(...) → await httpx client call ---
        if isinstance(node, ast.Call) and _is_bare_requests_call(node):
            _transform_bare_request(node, lines, line_replacements)

        # --- time.sleep(x) → await asyncio.sleep(x) ---
        if isinstance(node, ast.Call) and _is_attr_call(node, "time", "sleep"):
            _replace_time_sleep(node, lines, line_replacements)

        # --- sleep(x) from `from time import sleep` → await asyncio.sleep(x) ---
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sleep"
        ):
            _replace_bare_sleep(node, lines, line_replacements)

        # --- self.helper_method(s) → await self.helper_method(s) ---
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
                and node.func.attr in methods_needing_async
            ):
                _add_await_before_call(node, lines, line_replacements)

        # --- requests.exceptions.X → httpx.X ---
        if isinstance(node, ast.Attribute):
            _replace_requests_exceptions_in_node(node, lines, line_replacements)

    # Handle __init__ with self._session = requests.Session()
    if method.name == "__init__" and init_session_attr:
        for node in ast.walk(method):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and _is_requests_session(node.value)
            ):
                indent = _get_indent(lines[node.lineno - 1])
                new = f"{indent}self.{init_session_attr} = httpx.AsyncClient(follow_redirects=True)\n"
                for ln in range(node.lineno, node.end_lineno + 1):
                    if ln == node.lineno:
                        line_replacements[ln] = new
                    else:
                        delete_lines.add(ln)


def _transform_session_assign(
    node: ast.Assign,
    lines: list[str],
    delete_lines: set[int],
    delete_ranges: list[tuple[int, int]],
    line_replacements: dict[int, str],
    adapter_classes: dict[str, ast.ClassDef],
    method: ast.FunctionDef,
    full_source: str,
):
    """Transform s = requests.Session() to s = httpx.AsyncClient(...)."""
    tgt = node.targets[0]
    if isinstance(tgt, ast.Name):
        var_name = tgt.id
    elif isinstance(tgt, ast.Attribute):
        var_name = f"self.{tgt.attr}"
    else:
        return

    indent = _get_indent(lines[node.lineno - 1])

    # Look for .mount() calls with adapter in the method to get SSL context
    ssl_context_var = None
    ssl_context_code = None
    mount_nodes: list[ast.stmt] = []

    for stmt in method.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            # .mount() call
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "mount"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == var_name
            ):
                mount_nodes.append(stmt)
                # Check if adapter class is used
                if call.args and len(call.args) >= 2:
                    adapter_arg = call.args[1]
                    if isinstance(adapter_arg, ast.Call):
                        adapter_name = None
                        if isinstance(adapter_arg.func, ast.Name):
                            adapter_name = adapter_arg.func.id
                        # Check if adapter constructor takes a ctx arg
                        # e.g. CustomHttpAdapter(ctx) — ctx already exists in method body
                        if adapter_arg.args:
                            first_arg = adapter_arg.args[0]
                            if isinstance(first_arg, ast.Name):
                                ssl_context_var = first_arg.id
                        # Adapter with no args — SSL context is internal to adapter class
                        # e.g. LegacyTLSAdapter() — extract SSL setup lines
                        elif adapter_name and adapter_name in adapter_classes:
                            ssl_context_code = _extract_ssl_lines(
                                adapter_classes[adapter_name], full_source
                            )
                            ssl_context_var = "ctx"

    # Build AsyncClient kwargs
    kwargs_parts = []
    if ssl_context_var:
        kwargs_parts.append(f"verify={ssl_context_var}")
    kwargs_parts.append("follow_redirects=True")

    asyncclient_line = (
        f"{indent}{var_name} = httpx.AsyncClient({', '.join(kwargs_parts)})\n"
    )

    if ssl_context_code:
        # Adapter class has internal SSL setup — prepend extracted lines before the client
        ssl_lines = ssl_context_code.strip().splitlines()
        prefix = "\n".join(indent + sl for sl in ssl_lines) + "\n"
        asyncclient_line = prefix + asyncclient_line

    if ssl_context_var and not ssl_context_code and mount_nodes:
        # ctx is defined in the method body and passed to the adapter constructor.
        # The ctx may be defined between the Session() and mount() lines.
        # Place AsyncClient at the mount() position (where ctx is guaranteed defined).
        mount_stmt = mount_nodes[0]
        # Delete original Session() line
        for ln in range(node.lineno, node.end_lineno + 1):
            delete_lines.add(ln)
        # Replace mount line with AsyncClient creation
        line_replacements[mount_stmt.lineno] = asyncclient_line
        for ln in range(mount_stmt.lineno + 1, mount_stmt.end_lineno + 1):
            delete_lines.add(ln)
        # Delete any other mount statements
        for stmt in mount_nodes[1:]:
            for ln in range(stmt.lineno, stmt.end_lineno + 1):
                delete_lines.add(ln)
    else:
        # Replace the Session() assignment in-place
        line_replacements[node.lineno] = asyncclient_line
        for ln in range(node.lineno + 1, node.end_lineno + 1):
            delete_lines.add(ln)
        # Delete mount statements
        for stmt in mount_nodes:
            for ln in range(stmt.lineno, stmt.end_lineno + 1):
                delete_lines.add(ln)


def _extract_ssl_lines(cls_node: ast.ClassDef, source: str) -> str | None:
    """Extract SSL context setup lines from an HTTPAdapter subclass."""
    for method in cls_node.body:
        if isinstance(method, ast.FunctionDef) and method.name in (
            "init_poolmanager",
            "__init__",
        ):
            ctx_lines = []
            for stmt in method.body:
                seg = ast.get_source_segment(source, stmt)
                if seg and (
                    "ssl" in seg or "ctx" in seg or "create_default_context" in seg
                ):
                    if (
                        "kwargs" not in seg
                        and "super()" not in seg
                        and "return" not in seg
                        and "poolmanager" not in seg
                    ):
                        # Dedent the line
                        ctx_lines.append(seg.strip())
            if ctx_lines:
                return "\n".join(ctx_lines)
    return None


def _find_ssl_context_setup(
    method: ast.FunctionDef, var_name: str, source: str
) -> str | None:
    """Find ssl context setup for a named variable in method body."""
    ctx_lines = []
    for stmt in method.body:
        seg = ast.get_source_segment(source, stmt)
        if (
            seg
            and var_name in seg
            and ("ssl" in seg or "create_default_context" in seg)
        ):
            ctx_lines.append(seg.strip())
    return "\n".join(ctx_lines) if ctx_lines else None


def _add_await_before_call(
    call_node: ast.Call, lines: list[str], line_replacements: dict[int, str]
):
    """Add 'await' before a call expression on its line."""
    lineno = call_node.lineno
    col = call_node.col_offset
    line = line_replacements.get(lineno, lines[lineno - 1])

    # Check if 'await' is already there
    before_call = line[:col]
    if before_call.rstrip().endswith("await"):
        return

    # Insert 'await ' at the call's column offset
    # But we need to be careful: if this is `r = s.get(...)`, we want `r = await s.get(...)`
    new_line = line[:col] + "await " + line[col:]
    line_replacements[lineno] = new_line


def _transform_bare_request(
    call_node: ast.Call, lines: list[str], line_replacements: dict[int, str]
):
    """Transform requests.get(...) / requests.post(...).

    Since these need an async context manager, we wrap them.
    For simplicity in this mechanical transform, we replace `requests.METHOD(` with
    `await httpx.AsyncClient().METHOD(` — the client will be GC'd.
    A more proper approach would use `async with`, but that requires restructuring
    the surrounding code which is complex for an automated transform.
    """
    func = call_node.func
    if not isinstance(func, ast.Attribute):
        return
    method_name = func.attr  # get, post, etc.

    lineno = func.value.lineno
    line = line_replacements.get(lineno, lines[lineno - 1])

    # Find 'requests.get(' or 'requests.post(' in the line and replace
    old_pattern = f"requests.{method_name}("
    if old_pattern not in line:
        return

    # Replace requests.METHOD( with await httpx.AsyncClient().METHOD(
    new_pattern = f"await httpx.AsyncClient(follow_redirects=True).{method_name}("
    new_line = line.replace(old_pattern, new_pattern, 1)
    line_replacements[lineno] = new_line


def _replace_time_sleep(
    call_node: ast.Call, lines: list[str], line_replacements: dict[int, str]
):
    """Replace time.sleep(x) with await asyncio.sleep(x)."""
    lineno = call_node.lineno
    line = line_replacements.get(lineno, lines[lineno - 1])
    # Find time.sleep and replace, adding await
    new_line = line.replace("time.sleep(", "await asyncio.sleep(", 1)
    # Ensure there's not already an await
    if "await await" in new_line:
        new_line = new_line.replace("await await", "await", 1)
    line_replacements[lineno] = new_line


def _replace_bare_sleep(
    call_node: ast.Call, lines: list[str], line_replacements: dict[int, str]
):
    """Replace sleep(x) (from `from time import sleep`) with await asyncio.sleep(x)."""
    lineno = call_node.lineno
    col = call_node.col_offset
    line = line_replacements.get(lineno, lines[lineno - 1])
    # Replace sleep( with await asyncio.sleep( at the right position
    before = line[:col]
    after = line[col:]
    if after.startswith("sleep("):
        new_line = before + "await asyncio.sleep(" + after[len("sleep(") :]
        line_replacements[lineno] = new_line


def _replace_requests_exceptions_in_node(
    node: ast.Attribute, lines: list[str], line_replacements: dict[int, str]
):
    """Replace requests.exceptions.X references in code lines."""
    lineno = node.lineno
    line = line_replacements.get(lineno, lines[lineno - 1])
    replacements = {
        "requests.exceptions.RequestException": "httpx.HTTPError",
        "requests.exceptions.HTTPError": "httpx.HTTPStatusError",
        "requests.exceptions.ConnectionError": "httpx.ConnectError",
        "requests.exceptions.Timeout": "httpx.TimeoutException",
    }
    changed = False
    for old, new in replacements.items():
        if old in line:
            line = line.replace(old, new)
            changed = True
    if changed:
        line_replacements[lineno] = line


# --- Predicates ---


def _name_contains(node: ast.AST, name: str) -> bool:
    if isinstance(node, ast.Name):
        return name in node.id
    if isinstance(node, ast.Attribute):
        return name in node.attr or _name_contains(node.value, name)
    return False


def _is_requests_session(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Session"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "requests"
    )


def _is_attr_call(node: ast.Call, obj: str, attr: str) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == obj
    )


def _is_session_http_call(node: ast.Call, session_var_names: set[str]) -> bool:
    """Check if node is s.get/s.post/self._session.get etc."""
    http_methods = {"get", "post", "put", "delete", "patch", "head", "options"}
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in http_methods:
        return False
    val = func.value
    if isinstance(val, ast.Name) and val.id in session_var_names:
        return True
    if (
        isinstance(val, ast.Attribute)
        and isinstance(val.value, ast.Name)
        and val.value.id == "self"
        and f"self.{val.attr}" in session_var_names
    ):
        return True
    return False


def _is_bare_requests_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in ("get", "post", "put", "delete", "patch")
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "requests"
    )


def _is_method_call_on(call: ast.Call, var_names: set[str], method: str) -> bool:
    if isinstance(call.func, ast.Attribute) and call.func.attr == method:
        val = call.func.value
        if isinstance(val, ast.Name) and val.id in var_names:
            return True
    return False


def _is_headers_update(call: ast.Call, session_var_names: set[str]) -> bool:
    """Check for s.headers.update(...) or session.headers.update(...)."""
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "update"):
        return False
    val = func.value
    if not (isinstance(val, ast.Attribute) and val.attr == "headers"):
        return False
    obj = val.value
    if isinstance(obj, ast.Name) and obj.id in session_var_names:
        return True
    return False


def _body_uses_attr(func_node: ast.FunctionDef, obj: str, attr: str) -> bool:
    """Check if function body references obj.attr (e.g. self._session)."""
    for node in ast.walk(func_node):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == attr
            and isinstance(node.value, ast.Name)
            and node.value.id == obj
        ):
            return True
    return False


def _find_source_class(tree: ast.Module) -> ast.ClassDef | None:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Source":
            return node
    return None


# --- Helpers ---


def _final_requests_cleanup(source: str) -> str:
    """Final text-level pass to replace remaining requests.* references."""
    replacements = [
        # Type annotations
        ("requests.Response", "httpx.Response"),
        ("requests.Session", "httpx.AsyncClient"),
        # Lowercase session() constructor
        ("requests.session()", "httpx.AsyncClient(follow_redirects=True)"),
        # Exception classes used directly on requests module
        ("requests.HTTPError", "httpx.HTTPStatusError"),
        ("requests.RequestException", "httpx.HTTPError"),
        # Context manager form: with requests.Session() as X → X = httpx.AsyncClient(...)
        # This is handled by the broader Session replacement above
    ]
    for old, new in replacements:
        source = source.replace(old, new)

    # Handle `with requests.Session() as var:` → `var = httpx.AsyncClient(follow_redirects=True)`
    # This context manager pattern needs structural change
    source = re.sub(
        r"(\s*)with httpx\.AsyncClient\(follow_redirects=True\) as (\w+):",
        r"\1\2 = httpx.AsyncClient(follow_redirects=True)",
        source,
    )

    return source


def _get_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _get_stmt_text(node: ast.stmt, lines: list[str]) -> str:
    """Get the full source text of a statement."""
    result = []
    for i in range(node.lineno - 1, node.end_lineno):
        result.append(lines[i])
    return "".join(result)


def _replace_exception_names(text: str) -> str:
    text = text.replace("RequestException", "HTTPError")
    text = text.replace("ConnectionError", "ConnectError")
    text = text.replace("Timeout", "TimeoutException")
    return text


def _mark_stmt_replace(
    node: ast.stmt,
    lines: list[str],
    delete_ranges: list[tuple[int, int]],
    line_replacements: dict[int, str],
    old_text: str,
    new_text: str,
):
    """Replace a statement, handling multiline."""
    indent = _get_indent(lines[node.lineno - 1])
    line_replacements[node.lineno] = indent + new_text.lstrip() + "\n"
    # Delete extra lines if multiline
    if node.end_lineno > node.lineno:
        for ln in range(node.lineno + 1, node.end_lineno + 1):
            delete_ranges.append((ln, ln))


# --- File-level entry points ---


def transform_file(source_path: Path, output_path: Path) -> list[str]:
    source = source_path.read_text()
    transformed, warnings = transform_source(source)
    output_path.write_text(transformed)
    return warnings


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Patch waste collection scrapers from sync requests to async httpx"
    )
    parser.add_argument(
        "input_dir", type=Path, help="Directory with raw upstream scrapers"
    )
    parser.add_argument(
        "output_dir", type=Path, help="Directory to write patched files"
    )
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"Error: {args.input_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    source_files = sorted(args.input_dir.glob("*_gov_uk.py"))
    if not source_files:
        print(f"No *_gov_uk.py files found in {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Patching {len(source_files)} files...")

    all_warnings: dict[str, list[str]] = {}
    for src in source_files:
        out = args.output_dir / src.name
        warns = transform_file(src, out)
        if warns:
            all_warnings[src.name] = warns

    patched = len(source_files) - len(all_warnings)
    print(f"Patched: {patched}/{len(source_files)}")

    if all_warnings:
        print("\nWarnings:")
        for filename, warns in sorted(all_warnings.items()):
            for w in warns:
                print(f"  {filename}: {w}")


if __name__ == "__main__":
    main()
