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
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.shared import load_overrides

# Service modules in api.compat.hacs.service that expose async helpers.
# Any call to these names (as bare function or .attr method) must be awaited,
# and the enclosing method must be made async. Keep in sync with patch_compat.py.
ASYNC_SERVICE_SYMBOLS: dict[str, set[str]] = {
    "AchieveForms": {"init_session", "run_lookup"},
    "FirmstepSelfService": {
        "get_hidden_form_inputs",
        "get_verification_token",
        "lookup_addresses",
    },
    "WhitespaceWRP": {"fetch_schedule"},
}


class SourceRewriter:
    """Collects edits (indexed by line/col) and applies them in reverse order."""

    def __init__(self, source: str):
        self.source = source
        self.lines = source.splitlines(keepends=True)
        # Each edit: (start_line, start_col, end_line, end_col, replacement)
        # Lines are 1-indexed (matching ast), cols are 0-indexed
        self._edits: list[tuple[int, int, int, int, str]] = []

    def replace_node(self, node: ast.expr | ast.stmt, replacement: str):
        """Replace an AST node's source span with replacement text."""
        assert node.end_lineno is not None and node.end_col_offset is not None
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
        assert node.end_lineno is not None
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
                before = lines[start_line - 1][:start_col]

                last_line = lines[end_line - 1]
                after = last_line[end_col:]

                new_content = before + replacement + after
                lines[start_line - 1] = new_content
                for i in range(start_line, end_line):
                    lines[i] = ""

        return "".join(lines)


@dataclass
class _AnalysisResult:
    """Results from analysing a source file's AST for sync→async transform."""

    has_requests_import: bool = False
    has_cloudscraper_import: bool = False
    has_curl_cffi_import: bool = False
    has_time_import: bool = False
    has_from_time_import_sleep: bool = False
    uses_time_sleep: bool = False
    uses_time_other: bool = False
    httpadapter_classes: dict[str, ast.ClassDef] = field(default_factory=dict)
    session_var_names: set[str] = field(default_factory=set)
    init_session_attr: str | None = None
    methods_needing_async: set[str] = field(default_factory=set)
    async_callables: set[str] = field(default_factory=set)


def _analyse_import_node(node: ast.Import, result: _AnalysisResult) -> None:
    """Analyse a plain `import X` statement."""
    names = {alias.name for alias in node.names}
    if "requests" in names:
        result.has_requests_import = True
    if "cloudscraper" in names:
        result.has_cloudscraper_import = True
    if "time" in names:
        result.has_time_import = True


def _analyse_import_from_node(node: ast.ImportFrom, result: _AnalysisResult) -> None:
    """Analyse a `from X import Y` statement."""
    mod = node.module or ""
    if mod == "requests" or mod.startswith("requests."):
        result.has_requests_import = True
    if mod == "curl_cffi" and any(a.name == "requests" for a in node.names):
        result.has_requests_import = True
        result.has_curl_cffi_import = True
    if mod == "time" and any(a.name == "sleep" for a in node.names):
        result.has_from_time_import_sleep = True
    if mod.startswith("waste_collection_schedule.service."):
        module_tail = mod.rsplit(".", 1)[-1]
        if module_tail in ASYNC_SERVICE_SYMBOLS:
            result.async_callables.update(ASYNC_SERVICE_SYMBOLS[module_tail])


def _analyse_imports(tree: ast.Module, result: _AnalysisResult) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _analyse_import_node(node, result)
        elif isinstance(node, ast.ImportFrom):
            _analyse_import_from_node(node, result)


def _analyse_sessions_and_adapters(tree: ast.Module, result: _AnalysisResult) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if _name_contains(base, "HTTPAdapter"):
                    result.httpadapter_classes[node.name] = node

    _analyse_session_vars(tree, result)


def _analyse_session_vars(tree: ast.Module, result: _AnalysisResult) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            if _is_requests_session(node.value):
                tgt = node.targets[0]
                if isinstance(tgt, ast.Name):
                    result.session_var_names.add(tgt.id)
                elif (
                    isinstance(tgt, ast.Attribute)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == "self"
                ):
                    result.init_session_attr = tgt.attr
                    result.session_var_names.add(f"self.{tgt.attr}")
        if isinstance(node, ast.With):
            for item in node.items:
                if (
                    isinstance(item.context_expr, ast.Call)
                    and _is_requests_session(item.context_expr)
                    and item.optional_vars
                    and isinstance(item.optional_vars, ast.Name)
                ):
                    result.session_var_names.add(item.optional_vars.id)


def _analyse_time_usage(tree: ast.Module, result: _AnalysisResult) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _is_attr_call(node, "time", "sleep"):
                result.uses_time_sleep = True
            elif (
                isinstance(node.func, ast.Name)
                and node.func.id == "sleep"
                and result.has_from_time_import_sleep
            ):
                result.uses_time_sleep = True
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "time" and node.attr != "sleep":
                result.uses_time_other = True


def _method_needs_async(
    func: ast.FunctionDef,
    init_session_attr: str | None,
    async_callables: set[str],
) -> bool:
    """Check if a helper method directly needs async (uses sessions, requests,
    or calls an async service helper)."""
    param_names = {a.arg for a in func.args.args}
    if param_names & {"s", "session"}:
        return True
    if init_session_attr and _body_uses_attr(func, "self", init_session_attr):
        return True
    for n in ast.walk(func):
        if isinstance(n, ast.Call):
            if _is_bare_requests_call(n) or _is_requests_session(n):
                return True
            if _call_matches_async_helper(n, async_callables):
                return True
    return False


def _call_matches_async_helper(node: ast.Call, async_callables: set[str]) -> bool:
    """Check if a Call node targets one of the known async service helpers."""
    if not async_callables:
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id in async_callables:
        return True
    if isinstance(func, ast.Attribute) and func.attr in async_callables:
        return True
    return False


def _build_self_call_graph(tree: ast.Module) -> dict[str, set[str]]:
    """Build a mapping of method_name → set of self.method() callees."""
    method_calls: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            method_calls[node.name] = {
                n.func.attr
                for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "self"
            }
    return method_calls


def _analyse_async_methods(tree: ast.Module, result: _AnalysisResult) -> None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name not in ("__init__", "fetch")
            and _method_needs_async(
                node, result.init_session_attr, result.async_callables
            )
        ):
            result.methods_needing_async.add(node.name)

    # Transitive closure via call graph
    method_calls = _build_self_call_graph(tree)
    changed = True
    while changed:
        changed = False
        for method_name, callees in method_calls.items():
            if (
                method_name not in result.methods_needing_async
                and method_name not in ("__init__", "fetch")
                and callees & result.methods_needing_async
            ):
                result.methods_needing_async.add(method_name)
                changed = True


def _analyse_tree(tree: ast.Module) -> _AnalysisResult:
    result = _AnalysisResult()
    _analyse_imports(tree, result)
    _analyse_sessions_and_adapters(tree, result)
    _analyse_time_usage(tree, result)
    _analyse_async_methods(tree, result)
    return result


def _rewrite_import_from(
    node: ast.ImportFrom,
    lines: list[str],
    delete_lines: set[int],
    delete_ranges: list[tuple[int, int]],
    line_replacements: dict[int, str],
    analysis: _AnalysisResult,
) -> None:
    mod = node.module or ""
    if mod == "requests":
        _mark_stmt_replace(
            node,
            lines,
            delete_ranges,
            line_replacements,
            _get_stmt_text(node, lines),
            "import httpx",
        )
    elif mod == "curl_cffi" and any(a.name == "requests" for a in node.names):
        _mark_stmt_replace(
            node,
            lines,
            delete_ranges,
            line_replacements,
            _get_stmt_text(node, lines),
            "import httpx",
        )
    elif mod.startswith("requests.adapters"):
        _delete_stmt_lines(node, delete_lines)
    elif mod.startswith("requests.exceptions"):
        old_text = _get_stmt_text(node, lines)
        new_text = _replace_exception_names(
            old_text.replace("from requests.exceptions import", "from httpx import")
        )
        _mark_stmt_replace(
            node, lines, delete_ranges, line_replacements, old_text, new_text
        )
    elif mod == "time" and analysis.uses_time_sleep:
        if any(a.name == "sleep" for a in node.names):
            _mark_stmt_replace(
                node,
                lines,
                delete_ranges,
                line_replacements,
                _get_stmt_text(node, lines),
                "import asyncio",
            )


def _rewrite_imports(
    tree: ast.Module,
    lines: list[str],
    delete_lines: set[int],
    delete_ranges: list[tuple[int, int]],
    line_replacements: dict[int, str],
    analysis: _AnalysisResult,
) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("requests", "cloudscraper"):
                    _mark_stmt_replace(
                        node,
                        lines,
                        delete_ranges,
                        line_replacements,
                        _get_stmt_text(node, lines),
                        "import httpx",
                    )
                if (
                    alias.name == "time"
                    and analysis.uses_time_sleep
                    and not analysis.uses_time_other
                ):
                    _mark_stmt_replace(
                        node,
                        lines,
                        delete_ranges,
                        line_replacements,
                        _get_stmt_text(node, lines),
                        "import asyncio",
                    )
        elif isinstance(node, ast.ImportFrom):
            _rewrite_import_from(
                node,
                lines,
                delete_lines,
                delete_ranges,
                line_replacements,
                analysis,
            )


def _apply_edits(
    lines: list[str],
    delete_lines: set[int],
    delete_ranges: list[tuple[int, int]],
    line_replacements: dict[int, str],
    analysis: _AnalysisResult,
) -> str:
    result_lines: list[str] = []
    need_asyncio_import = (
        analysis.uses_time_sleep
        and analysis.has_time_import
        and analysis.uses_time_other
    )
    asyncio_inserted = False
    i = 1  # 1-indexed
    while i <= len(lines):
        if i in line_replacements:
            pass  # will be handled below
        elif i in delete_lines:
            i += 1
            continue
        else:
            in_range = any(rs <= i <= re_ for rs, re_ in delete_ranges)
            if in_range:
                i += 1
                continue

        line = line_replacements.get(i, lines[i - 1])
        result_lines.append(line)

        if need_asyncio_import and not asyncio_inserted:
            stripped = lines[i - 1].strip()
            if stripped.startswith("import time"):
                result_lines.append("import asyncio\n")
                asyncio_inserted = True

        i += 1

    result = "".join(result_lines)
    return re.sub(r"\n{4,}", "\n\n\n", result)


def transform_source(source: str) -> tuple[str, list[str]]:
    """Transform a single source file. Returns (new_source, warnings)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return source, [f"Parse error: {e}"]

    analysis = _analyse_tree(tree)

    if (
        not analysis.has_requests_import
        and not analysis.has_cloudscraper_import
        and not analysis.async_callables
    ):
        patched = _final_requests_cleanup(source)
        # Even without requests/cloudscraper, fetch() must be async for the registry
        if "async def fetch" not in patched:
            patched = re.sub(
                r"(\s+)def fetch\(self\)",
                r"\1async def fetch(self)",
                patched,
            )
        if patched != source:
            return patched, []
        return source, [
            "No 'import requests' or 'import cloudscraper' found — skipping"
        ]

    lines = source.splitlines(keepends=True)
    delete_lines: set[int] = set()
    line_replacements: dict[int, str] = {}
    delete_ranges: list[tuple[int, int]] = []

    _rewrite_imports(
        tree, lines, delete_lines, delete_ranges, line_replacements, analysis
    )

    # Remove HTTPAdapter subclass definitions
    for cls_name, cls_node in analysis.httpadapter_classes.items():
        assert cls_node.end_lineno is not None
        for ln in range(cls_node.lineno, cls_node.end_lineno + 1):
            delete_lines.add(ln)

    # Process Source class body
    source_class = _find_source_class(tree)
    if source_class:
        _process_class(
            source_class,
            lines,
            delete_lines,
            delete_ranges,
            line_replacements,
            analysis.session_var_names,
            analysis.httpadapter_classes,
            analysis.methods_needing_async,
            analysis.init_session_attr,
            source,
            analysis.async_callables,
        )

    # Process module-level functions that use requests
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name not in ("fetch",):
            _process_module_function(
                node,
                lines,
                delete_lines,
                delete_ranges,
                line_replacements,
                analysis.session_var_names,
                source,
            )

    result = _apply_edits(
        lines, delete_lines, delete_ranges, line_replacements, analysis
    )
    result = _final_requests_cleanup(result)
    return result, []


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
    async_callables: set[str],
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
                async_callables,
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


def _transform_call_node(
    node: ast.Call,
    lines: list[str],
    line_replacements: dict[int, str],
    local_session_vars: set[str],
    methods_needing_async: set[str],
    chained_bare_requests: set[int],
    async_callables: set[str],
) -> None:
    """Transform a Call node: add awaits, replace requests→httpx, sleep→asyncio."""
    if _is_session_http_call(node, local_session_vars):
        _add_await_before_call(node, lines, line_replacements)

    if _call_matches_async_helper(node, async_callables):
        _add_await_before_call(node, lines, line_replacements)

    if _is_bare_requests_call(node) and id(node) not in chained_bare_requests:
        _transform_bare_request(node, lines, line_replacements)

    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Call)
        and _is_bare_requests_call(node.func.value)
    ):
        _transform_chained_bare_request(node.func.value, node, lines, line_replacements)

    if _is_attr_call(node, "time", "sleep"):
        _replace_time_sleep(node, lines, line_replacements)

    if isinstance(node.func, ast.Name) and node.func.id == "sleep":
        _replace_bare_sleep(node, lines, line_replacements)

    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
        and (node.func.attr in methods_needing_async or node.func.attr == "fetch")
    ):
        _add_await_before_call(node, lines, line_replacements)


def _transform_node(
    node: ast.AST,
    method: ast.FunctionDef,
    lines: list[str],
    delete_lines: set[int],
    delete_ranges: list[tuple[int, int]],
    line_replacements: dict[int, str],
    local_session_vars: set[str],
    adapter_classes: dict[str, ast.ClassDef],
    methods_needing_async: set[str],
    chained_bare_requests: set[int],
    full_source: str,
    async_callables: set[str],
) -> None:
    """Transform a single AST node within a method body."""
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
        return

    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        if _is_method_call_on(node.value, local_session_vars, "mount"):
            _delete_stmt_lines(node, delete_lines)
            return

    if isinstance(node, ast.Call):
        _transform_call_node(
            node,
            lines,
            line_replacements,
            local_session_vars,
            methods_needing_async,
            chained_bare_requests,
            async_callables,
        )
    elif isinstance(node, ast.Attribute):
        _replace_requests_exceptions_in_node(node, lines, line_replacements)


def _find_chained_bare_requests(method: ast.FunctionDef) -> set[int]:
    """Find inner Call ids that are chained (e.g. requests.get(...).json())."""
    result: set[int] = set()
    for node in ast.walk(method):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            inner = node.func.value
            if isinstance(inner, ast.Call) and _is_bare_requests_call(inner):
                result.add(id(inner))
    return result


def _rewrite_init_session(
    method: ast.FunctionDef,
    init_session_attr: str,
    lines: list[str],
    delete_lines: set[int],
    line_replacements: dict[int, str],
) -> None:
    """Replace self._session = requests.Session() in __init__."""
    for node in ast.walk(method):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and _is_requests_session(node.value)
        ):
            assert node.end_lineno is not None
            indent = _get_indent(lines[node.lineno - 1])
            new = f"{indent}self.{init_session_attr} = httpx.AsyncClient(follow_redirects=True)\n"
            line_replacements[node.lineno] = new
            for ln in range(node.lineno + 1, node.end_lineno + 1):
                delete_lines.add(ln)


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
    async_callables: set[str],
):
    """Process a single method within Source class."""
    if method.name == "fetch" or method.name in methods_needing_async:
        line = lines[method.lineno - 1]
        if "async def" not in line:
            line_replacements[method.lineno] = line.replace(
                f"def {method.name}(", f"async def {method.name}(", 1
            )

    local_session_vars = set(session_var_names)
    for arg in method.args.args:
        if arg.arg in ("s", "session"):
            local_session_vars.add(arg.arg)

    chained_bare_requests = _find_chained_bare_requests(method)

    for node in ast.walk(method):
        _transform_node(
            node,
            method,
            lines,
            delete_lines,
            delete_ranges,
            line_replacements,
            local_session_vars,
            adapter_classes,
            methods_needing_async,
            chained_bare_requests,
            full_source,
            async_callables,
        )

    if method.name == "__init__" and init_session_attr:
        _rewrite_init_session(
            method, init_session_attr, lines, delete_lines, line_replacements
        )


def _delete_stmt_lines(stmt: ast.stmt, delete_lines: set[int]) -> None:
    """Mark all lines of a statement for deletion."""
    assert stmt.end_lineno is not None
    for ln in range(stmt.lineno, stmt.end_lineno + 1):
        delete_lines.add(ln)


def _scan_mount_calls(
    method: ast.FunctionDef,
    var_name: str,
    adapter_classes: dict[str, ast.ClassDef],
    full_source: str,
) -> tuple[list[ast.stmt], str | None, str | None]:
    """Find .mount() calls and extract SSL context info.

    Returns (mount_nodes, ssl_context_var, ssl_context_code).
    """
    ssl_context_var: str | None = None
    ssl_context_code: str | None = None
    mount_nodes: list[ast.stmt] = []

    for stmt in method.body:
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
            continue
        call = stmt.value
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "mount"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == var_name
        ):
            continue

        mount_nodes.append(stmt)
        if not (
            call.args and len(call.args) >= 2 and isinstance(call.args[1], ast.Call)
        ):
            continue

        adapter_arg = call.args[1]
        adapter_name = (
            adapter_arg.func.id if isinstance(adapter_arg.func, ast.Name) else None
        )
        if adapter_arg.args:
            first_arg = adapter_arg.args[0]
            if isinstance(first_arg, ast.Name):
                ssl_context_var = first_arg.id
        elif adapter_name and adapter_name in adapter_classes:
            ssl_context_code = _extract_ssl_lines(
                adapter_classes[adapter_name], full_source
            )
            ssl_context_var = "ctx"

    return mount_nodes, ssl_context_var, ssl_context_code


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
    mount_nodes, ssl_context_var, ssl_context_code = _scan_mount_calls(
        method, var_name, adapter_classes, full_source
    )

    # Build AsyncClient kwargs
    kwargs_parts = []
    if ssl_context_var:
        kwargs_parts.append(f"verify={ssl_context_var}")
    kwargs_parts.append("follow_redirects=True")

    asyncclient_line = (
        f"{indent}{var_name} = httpx.AsyncClient({', '.join(kwargs_parts)})\n"
    )

    if ssl_context_code:
        ssl_lines = ssl_context_code.strip().splitlines()
        prefix = "\n".join(indent + sl for sl in ssl_lines) + "\n"
        asyncclient_line = prefix + asyncclient_line

    assert node.end_lineno is not None
    if ssl_context_var and not ssl_context_code and mount_nodes:
        # Place AsyncClient at mount() position (where ctx is guaranteed defined)
        mount_stmt = mount_nodes[0]
        _delete_stmt_lines(node, delete_lines)
        assert mount_stmt.end_lineno is not None
        line_replacements[mount_stmt.lineno] = asyncclient_line
        for ln in range(mount_stmt.lineno + 1, mount_stmt.end_lineno + 1):
            delete_lines.add(ln)
        for stmt in mount_nodes[1:]:
            _delete_stmt_lines(stmt, delete_lines)
    else:
        line_replacements[node.lineno] = asyncclient_line
        for ln in range(node.lineno + 1, node.end_lineno + 1):
            delete_lines.add(ln)
        for stmt in mount_nodes:
            _delete_stmt_lines(stmt, delete_lines)


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


def _transform_chained_bare_request(
    inner_call: ast.Call,
    outer_call: ast.Call,
    lines: list[str],
    line_replacements: dict[int, str],
):
    """Transform requests.get(...).json() → (await httpx.AsyncClient(...).get(...)).json()."""
    func = inner_call.func
    if not isinstance(func, ast.Attribute):
        return
    method_name = func.attr

    start_lineno = func.value.lineno
    line = line_replacements.get(start_lineno, lines[start_lineno - 1])

    old_pattern = f"requests.{method_name}("
    if old_pattern not in line:
        return

    new_pattern = f"(await httpx.AsyncClient(follow_redirects=True).{method_name}("
    new_line = line.replace(old_pattern, new_pattern, 1)
    line_replacements[start_lineno] = new_line

    # Insert closing paren ')' after the inner call's closing paren
    assert inner_call.end_lineno is not None and inner_call.end_col_offset is not None
    end_lineno = inner_call.end_lineno
    end_col = inner_call.end_col_offset

    if start_lineno == end_lineno:
        # Same line — account for the shift from the replacement above
        shift = len(new_pattern) - len(old_pattern)
        adjusted_col = end_col + shift
        el = line_replacements[start_lineno]
        line_replacements[start_lineno] = el[:adjusted_col] + ")" + el[adjusted_col:]
    else:
        # Different lines — insert ')' at the inner call's end position
        el = line_replacements.get(end_lineno, lines[end_lineno - 1])
        line_replacements[end_lineno] = el[:end_col] + ")" + el[end_col:]


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
    if not isinstance(node, ast.Call):
        return False
    # requests.Session() or requests.session()
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        if node.func.value.id == "requests" and node.func.attr in (
            "Session",
            "session",
        ):
            return True
        # cloudscraper.create_scraper(...)
        if node.func.value.id == "cloudscraper" and node.func.attr == "create_scraper":
            return True
    # Bare Session() — from `from requests import Session`
    if isinstance(node.func, ast.Name) and node.func.id == "Session":
        return True
    return False


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


def _extract_call_arg_block(source: str, match_end: int) -> str:
    """Extract the argument block from a call site, handling nested parens."""
    depth = 1
    i = match_end
    while i < len(source) and depth > 0:
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            depth -= 1
        i += 1
    return source[match_end:i]


def _find_verify_vars(source: str, pattern: str) -> set[str]:
    """Find session vars whose HTTP calls contain verify=False."""
    result: set[str] = set()
    for m in re.finditer(pattern, source):
        arg_block = _extract_call_arg_block(source, m.end())
        if "verify=False" in arg_block:
            result.add(m.group(1))
    return result


def _hoist_verify_to_client(
    source: str, vars_to_fix: set[str], verify_val: str = "False"
) -> str:
    """Add verify= to AsyncClient constructors for the given session vars."""
    lines = source.split("\n")
    new_lines = []
    for line in lines:
        for var in vars_to_fix:
            escaped_var = re.escape(var)
            pattern = rf"(\s*){escaped_var}\s*=\s*httpx\.AsyncClient\(([^)]*)\)"
            m_line = re.match(pattern, line)
            if m_line and "verify=" not in m_line.group(2):
                args = m_line.group(2)
                val = f"verify={verify_val}"
                args = f"{val}, {args}" if args else val
                line = f"{m_line.group(1)}{var} = httpx.AsyncClient({args})"
        new_lines.append(line)
    return "\n".join(new_lines)


def _strip_verify_from_calls(source: str, verify_val: str = "False") -> str:
    """Remove verify=VAL from HTTP method call lines (not AsyncClient constructors)."""
    escaped_val = re.escape(verify_val)
    lines = source.split("\n")
    new_lines = []
    for line in lines:
        if f"verify={verify_val}" in line and "AsyncClient(" not in line:
            line = re.sub(rf",\s*verify={escaped_val}", "", line)
            line = re.sub(rf"verify={escaped_val},\s*", "", line)
            if line.strip() == "" or line.strip() == ",":
                continue
        new_lines.append(line)
    return "\n".join(new_lines)


def _handle_verify_false(source: str) -> str:
    """Move verify=False from per-request kwargs to AsyncClient constructors."""

    # Move verify=False in inline AsyncClient().METHOD() calls
    def _move_verify_to_client(m: re.Match[str]) -> str:
        pre, client_args, method, call_args = m.group(1, 2, 3, 4)
        call_args = re.sub(r",?\s*verify=False", "", call_args)
        call_args = re.sub(r"verify=False,?\s*", "", call_args)
        if "verify=" not in client_args:
            client_args = (
                "verify=False, " + client_args if client_args else "verify=False"
            )
        return f"{pre}httpx.AsyncClient({client_args}).{method}({call_args})"

    source = re.sub(
        r"(await\s+)httpx\.AsyncClient\(([^)]*)\)\.(get|post|put|delete|patch|head)\(([^)]*verify=False[^)]*)\)",
        _move_verify_to_client,
        source,
    )

    # Find session vars that use verify=False
    verify_false_vars = _find_verify_vars(
        source, r"await\s+(\w+)\.(get|post|put|delete|patch|head)\("
    )
    verify_false_vars |= _find_verify_vars(
        source, r"await\s+(self\.\w+)\.(get|post|put|delete|patch|head)\("
    )

    if verify_false_vars:
        source = _hoist_verify_to_client(source, verify_false_vars)
    source = _strip_verify_from_calls(source)
    return source


def _handle_verify_variable(source: str) -> str:
    """Move verify=VARIABLE (not literal) from per-request kwargs to AsyncClient constructors."""
    verify_var_mapping: dict[str, str] = {}
    for m in re.finditer(
        r"await\s+((?:self\.)?\w+)\.(get|post|put|delete|patch|head)\(",
        source,
    ):
        arg_block = _extract_call_arg_block(source, m.end())
        verify_m = re.search(r"verify=(self\.\w+|\w+)", arg_block)
        if verify_m and verify_m.group(1) not in ("False", "True"):
            verify_var_mapping[m.group(1)] = verify_m.group(1)

    if not verify_var_mapping:
        return source

    for var, verify_val in verify_var_mapping.items():
        source = _hoist_verify_to_client(source, {var}, verify_val)
        source = _strip_verify_from_calls(source, verify_val)

    return source


def _handle_legacy_session(source: str) -> str:
    """Handle get_legacy_session() callers."""
    source = re.sub(
        r"(\s+)def fetch\(self\)",
        r"\1async def fetch(self)",
        source,
    )
    source = re.sub(
        r"(?<!await )get_legacy_session\(\)\.(get|post|put|delete|patch)\(",
        r"await get_legacy_session().\1(",
        source,
    )
    for m in re.finditer(r"(\w+)\s*=\s*get_legacy_session\(\)", source):
        var = m.group(1)
        escaped = re.escape(var)
        source = re.sub(
            rf"(?<!await ){escaped}\.(get|post|put|delete|patch)\(",
            rf"await {var}.\1(",
            source,
        )
    source = re.sub(r"[^\n]*\.get_adapter\([^)]*\)[^\n]*\n", "", source)
    return source


def _handle_urllib(source: str) -> str:
    """Convert urllib.request callers to async httpx."""
    source = re.sub(r"import urllib\.request\b", "import httpx", source)
    source = re.sub(
        r"(\s+)def fetch\(self\)",
        r"\1async def fetch(self)",
        source,
    )
    source = re.sub(
        r"(\s+)\w+\s*=\s*urllib\.request\.Request\(([^,\n]+?)(?:,\s*headers=(\w+))?\)\n",
        r"\1__urllib_url__ = \2\n\1__urllib_headers__ = \3\n",
        source,
    )
    # Handle multi-line urllib.request.Request() calls
    source = re.sub(
        r"(\s+)\w+\s*=\s*urllib\.request\.Request\(\s*\n\s+([^,\n]+?)(?:,\s*headers=(\w+))?\s*\n\s*\)\n",
        r"\1__urllib_url__ = \2\n\1__urllib_headers__ = \3\n",
        source,
    )
    source = re.sub(
        r"(\s+)with urllib\.request\.urlopen\(\w+\) as (\w+):\n\s+(\w+)\s*=\s*\2\.read\(\)\n",
        r"\1__urllib_resp__ = await httpx.AsyncClient(follow_redirects=True).get(__urllib_url__, headers=__urllib_headers__)\n\1\3 = __urllib_resp__.content\n",
        source,
    )
    url_match = re.search(r"__urllib_url__\s*=\s*(.+)", source)
    headers_match = re.search(r"__urllib_headers__\s*=\s*(.+)", source)
    if url_match and headers_match:
        url_val = url_match.group(1).strip()
        headers_val = headers_match.group(1).strip()
        source = re.sub(r"[^\n]*__urllib_url__\s*=\s*[^\n]+\n", "", source)
        source = re.sub(r"[^\n]*__urllib_headers__\s*=\s*[^\n]+\n", "", source)
        source = source.replace("__urllib_url__", url_val)
        if headers_val and headers_val != "None":
            source = source.replace("__urllib_headers__", headers_val)
        else:
            source = re.sub(r",\s*headers=__urllib_headers__", "", source)
        source = source.replace("__urllib_resp__", "response")
    return source


def _final_requests_cleanup(source: str) -> str:
    """Final text-level pass to replace remaining requests.* references."""
    replacements = [
        ("requests.Response", "httpx.Response"),
        ("requests.Session", "httpx.AsyncClient"),
        ("requests.session()", "httpx.AsyncClient(follow_redirects=True)"),
        ("requests.HTTPError", "httpx.HTTPStatusError"),
        ("requests.RequestException", "httpx.HTTPError"),
        ("cloudscraper.create_scraper()", "httpx.AsyncClient(follow_redirects=True)"),
        ("allow_redirects=", "follow_redirects="),
    ]
    for old, new in replacements:
        source = source.replace(old, new)

    source = re.sub(
        r"(\s*)with (httpx\.AsyncClient\([^)]*\)) as (\w+):",
        r"\1async with \2 as \3:",
        source,
    )

    # Strip curl_cffi-specific impersonate= arg (not supported by httpx)
    source = re.sub(
        r"httpx\.AsyncClient\(impersonate=[\"'][^\"']*[\"']\)",
        "httpx.AsyncClient(follow_redirects=True)",
        source,
    )
    source = re.sub(
        r"impersonate=[\"'][^\"']*[\"'],?\s*",
        "",
        source,
    )

    source = _handle_verify_false(source)
    source = _handle_verify_variable(source)

    # Convert positional data arg in .post()/.put()/.patch() calls
    source = re.sub(
        r"(\.\s*(?:post|put|patch)\([^,\n]+),\s+(?!data=|json=|files=|headers=|params=|timeout=|content=|cookies=|auth=|follow_redirects=)(\w+)\)",
        r"\1, data=\2)",
        source,
    )

    # Convert requests-style multipart files= with (None, val) tuples to plain values
    if re.search(r":\s*\(None,\s*.+?\)", source):
        source = re.sub(r"(:\s*)\(None,\s*(.+?)\)", r"\1\2", source)
        source = re.sub(r"\bfiles=", "data=", source)

    # Convert response.url (httpx URL object) to str
    source = re.sub(
        r"(\w+)\.url\.(replace|split|startswith|endswith|strip|lower|upper)\(",
        r"str(\1.url).\2(",
        source,
    )
    source = re.sub(r"(\w+)\.url(?=\s*[,)\]}])", r"str(\1.url)", source)

    # Fix raise_for_status without ()
    source = re.sub(r"\.raise_for_status\b(?!\()", ".raise_for_status()", source)

    if "get_legacy_session" in source:
        source = _handle_legacy_session(source)

    if "urllib.request" in source and "import requests" not in source:
        source = _handle_urllib(source)

    # Rewrite waste_collection_schedule imports to use api.compat.hacs
    source = re.sub(
        r"from (?:src\.)?api\.waste_collection_schedule(\b)",
        r"from api.compat.hacs\1",
        source,
    )
    source = re.sub(
        r"from waste_collection_schedule(\b)",
        r"from api.compat.hacs\1",
        source,
    )

    return source


def _get_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _get_stmt_text(node: ast.stmt, lines: list[str]) -> str:
    """Get the full source text of a statement."""
    assert node.end_lineno is not None
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
    assert node.end_lineno is not None
    indent = _get_indent(lines[node.lineno - 1])
    line_replacements[node.lineno] = indent + new_text.lstrip() + "\n"
    # Delete extra lines if multiline
    if node.end_lineno > node.lineno:
        for ln in range(node.lineno + 1, node.end_lineno + 1):
            delete_ranges.append((ln, ln))


def _is_deprecated_scraper(source: str) -> bool:
    """Detect deprecated scrapers that just wrap another scraper.

    These import from waste_collection_schedule.source.<other_scraper>,
    meaning they delegate to a different scraper and have no standalone logic.
    """
    return bool(
        re.search(r"from\s+(?:api\.)?waste_collection_schedule\.source\.", source)
    )


# --- Requests fallback for Cloudflare-blocked scrapers ---


def _load_override_sets() -> tuple[set[str], set[str], set[str], set[str]]:
    """Load all override sets from overrides.json.

    Returns (requests_fallback, curl_cffi_fallback, ssl_verify_disabled, broken).
    """
    overrides = load_overrides()
    return (
        set(overrides.get("requests_fallback", [])),
        set(overrides.get("curl_cffi_fallback", [])),
        set(overrides.get("ssl_verify_disabled", [])),
        set(overrides.get("broken", [])),
    )


def _apply_requests_fallback(source: str) -> str:
    """Replace httpx imports with requests_fallback for Cloudflare-blocked scrapers."""
    source = source.replace(
        "import httpx",
        "from api.compat.requests_fallback import AsyncClient as _FallbackClient",
    )
    source = source.replace("httpx.AsyncClient", "_FallbackClient")
    if "httpx." in source:
        source = "import httpx\n" + source
    return source


def _apply_curl_cffi_fallback(source: str) -> str:
    """Replace httpx imports with curl_cffi_fallback for CF-blocked scrapers."""
    source = source.replace(
        "import httpx",
        "from api.compat.curl_cffi_fallback import AsyncClient as _CurlCffiClient",
    )
    source = source.replace("httpx.AsyncClient", "_CurlCffiClient")
    if "httpx." in source:
        source = "import httpx\n" + source
    return source


def _apply_ssl_verify_disabled(source: str) -> str:
    """Set verify=False on all HTTP client constructors for SSL-broken councils.

    If the scraper creates a custom ssl.SSLContext (for cipher/TLS settings),
    we inject check_hostname=False and verify_mode=CERT_NONE into the context
    instead of discarding it — this preserves TLS configuration while disabling
    certificate verification.
    """
    # If source creates an SSL context, inject cert-disable into the context
    if "ssl.create_default_context" in source:
        # Insert check_hostname=False and verify_mode after the context creation line
        source = re.sub(
            r"([ \t]+)(ctx|ssl_ctx|ssl_context|context)\s*=\s*ssl\.create_default_context\([^)]*\)\n",
            lambda m: (
                m.group(0)
                + f"{m.group(1)}{m.group(2)}.check_hostname = False\n"
                + f"{m.group(1)}{m.group(2)}.verify_mode = ssl.CERT_NONE\n"
            ),
            source,
        )
    else:
        # No custom SSL context — add verify=False to client constructors
        source = re.sub(
            r"httpx\.AsyncClient\(([^)]*)\)",
            lambda m: _inject_verify_false("httpx.AsyncClient", m.group(1), force=True),
            source,
        )
        # Also handle fallback clients
        for client_name in ("_FallbackClient", "_CurlCffiClient"):
            source = re.sub(
                rf"{re.escape(client_name)}\(([^)]*)\)",
                lambda m, cn=client_name: _inject_verify_false(
                    cn, m.group(1), force=True
                ),
                source,
            )
    # Handle get_legacy_session() — replace with httpx.AsyncClient(verify=False)
    if "get_legacy_session" in source:
        source = source.replace(
            "get_legacy_session()",
            "httpx.AsyncClient(verify=False, follow_redirects=True)",
        )
        # Remove the unused import
        source = re.sub(
            r"from api\.compat\.hacs\.service\.SSLError import get_legacy_session\n",
            "",
            source,
        )
        # Ensure httpx import exists
        if "import httpx" not in source:
            source = "import httpx\n" + source
    return source


def _inject_verify_false(client_name: str, args: str, force: bool = False) -> str:
    """Add verify=False to a client constructor if not already present.

    If force=True, replaces any existing verify= value with False.
    """
    if "verify=" in args:
        if force:
            args = re.sub(r"verify=\w+", "verify=False", args)
            return f"{client_name}({args})"
        return f"{client_name}({args})"
    if args.strip():
        return f"{client_name}(verify=False, {args})"
    return f"{client_name}(verify=False)"


# --- Init param normalisation ---


PARAM_NAME_NORMALISATIONS: dict[str, str] = {
    "post_code": "postcode",
    "address_postcode": "postcode",
    "number": "house_number",
    "house_number_or_name": "house_number",
    "housenumberorname": "house_number",
    "housenameornumber": "house_number",
    "name_number": "house_number",
    "door_num": "house_number",
    "property_name_or_number": "house_number",
    "address_name_number": "house_number",
    "address_name_numer": "house_number",
    "streetname": "street",
    "street_name": "street",
    "road_name": "street",
    "address_street": "street",
    "street_town": "town",
    "houseID": "address",
}


def _normalise_init_params(source: str) -> str:
    """Rename idiosyncratic Source.__init__ params to canonical names."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    cls = _find_source_class(tree)
    if cls is None:
        return source

    init = next(
        (
            n
            for n in cls.body
            if isinstance(n, ast.FunctionDef) and n.name == "__init__"
        ),
        None,
    )
    if init is None:
        return source

    existing = {a.arg for a in init.args.args} | {
        a.arg for a in init.args.kwonlyargs
    }
    renames: dict[str, str] = {}
    for arg in init.args.args:
        new_name = PARAM_NAME_NORMALISATIONS.get(arg.arg)
        if new_name is None:
            continue
        if new_name in existing or new_name in renames.values():
            continue
        renames[arg.arg] = new_name

    if not renames:
        return source

    for old, new in renames.items():
        source = re.sub(rf"\b{re.escape(old)}\b", new, source)
        source = re.sub(rf"\b_{re.escape(old)}\b", f"_{new}", source)
    return source


# --- File-level entry points ---


def transform_file(
    source_path: Path,
    output_path: Path,
    use_requests_fallback: bool = False,
    use_curl_cffi_fallback: bool = False,
    disable_ssl_verify: bool = False,
) -> list[str]:
    source = source_path.read_text()
    transformed, warnings = transform_source(source)
    transformed = _normalise_init_params(transformed)
    if use_curl_cffi_fallback:
        transformed = _apply_curl_cffi_fallback(transformed)
    elif use_requests_fallback:
        transformed = _apply_requests_fallback(transformed)
    if disable_ssl_verify:
        transformed = _apply_ssl_verify_disabled(transformed)
    output_path.write_text(transformed)
    return warnings


def _patch_single_file(
    src: Path,
    output_dir: Path,
    fallback_list: set[str],
    curl_cffi_list: set[str],
    ssl_disabled_list: set[str],
    broken_list: set[str],
) -> tuple[str | None, list[str]]:
    """Patch a single scraper file.

    Returns (deprecated_name_or_None, warnings).
    """
    out = output_dir / f"hacs_{src.name}"
    raw = src.read_text()
    if _is_deprecated_scraper(raw):
        if out.exists():
            out.unlink()
        return src.name, []
    if src.stem in broken_list:
        if out.exists():
            out.unlink()
        return src.name, []
    warns = transform_file(
        src,
        out,
        use_requests_fallback=src.stem in fallback_list,
        use_curl_cffi_fallback=src.stem in curl_cffi_list,
        disable_ssl_verify=src.stem in ssl_disabled_list,
    )
    return None, warns


def _log_override_info(
    fallback_list: set[str],
    curl_cffi_list: set[str],
    ssl_disabled_list: set[str],
    broken_list: set[str],
) -> None:
    """Print info about active overrides."""
    if fallback_list:
        print(f"Requests fallback enabled for {len(fallback_list)} scrapers.")
    if curl_cffi_list:
        print(f"curl_cffi fallback enabled for {len(curl_cffi_list)} scrapers.")
    if ssl_disabled_list:
        print(f"SSL verify disabled for {len(ssl_disabled_list)} scrapers.")
    if broken_list:
        print(f"Broken (skipped): {len(broken_list)} scrapers.")


def _print_results(
    total: int,
    deprecated: list[str],
    all_warnings: dict[str, list[str]],
) -> None:
    """Print patch results summary."""
    if deprecated:
        print(f"Deleted {len(deprecated)} deprecated scrapers: {', '.join(deprecated)}")

    patched = total - len(all_warnings) - len(deprecated)
    print(f"Patched: {patched}/{total}")

    if all_warnings:
        print("\nWarnings:")
        for filename, warns in sorted(all_warnings.items()):
            for w in warns:
                print(f"  {filename}: {w}")


def _patch_directory(input_dir: Path, output_dir: Path) -> None:
    """Patch all scraper files from input_dir into output_dir."""
    source_files = sorted(input_dir.glob("*_gov_uk.py"))
    if not source_files:
        print(f"No *_gov_uk.py files found in {input_dir}", file=sys.stderr)
        sys.exit(1)

    fallback_list, curl_cffi_list, ssl_disabled_list, broken_list = _load_override_sets()
    _log_override_info(fallback_list, curl_cffi_list, ssl_disabled_list, broken_list)

    print(f"Patching {len(source_files)} files...")

    all_warnings: dict[str, list[str]] = {}
    deprecated: list[str] = []
    for src in source_files:
        dep_name, warns = _patch_single_file(
            src,
            output_dir,
            fallback_list,
            curl_cffi_list,
            ssl_disabled_list,
            broken_list,
        )
        if dep_name:
            deprecated.append(dep_name)
        elif warns:
            all_warnings[src.name] = warns

    _print_results(len(source_files), deprecated, all_warnings)


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
    _patch_directory(args.input_dir, args.output_dir)


if __name__ == "__main__":
    main()
