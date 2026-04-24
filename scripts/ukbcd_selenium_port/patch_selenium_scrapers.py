"""
AST-based transpiler: Selenium → Playwright (async API).

Parses Python source files, walks the AST to find Selenium-specific nodes,
mutates them into Playwright equivalents, and unparses back to Python.

Design decisions:
  - WebDriverWait / EC.* calls are stripped (Playwright auto-waits)
  - EC.invisibility_of_element_located → locator.wait_for(state="hidden")
  - time.sleep() calls are stripped
  - Select() wrappers are unwrapped into direct locator.select_option()
  - driver → page, with pre-pass rename of URL `page` param → `page_url`
  - create_webdriver() → Playwright launch boilerplate
  - driver.quit() → browser.close() / playwright.stop()
  - execute_script("arguments[0]...", el) → el.evaluate(...)

Usage:
    uv run python patch_selenium_scrapers.py <input_file_or_dir> [--dry-run] [--report]
"""

from __future__ import annotations

import argparse
import ast
import copy
import re
from pathlib import Path

# The variable name used for the Playwright Page object in output code.
PW_PAGE = "page"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def by_to_selector(by_attr: str, selector_node: ast.expr) -> ast.expr:
    """Convert a (By.X, selector) pair into a single Playwright selector string node."""
    prefix_map = {
        "ID": "#",
        "CSS_SELECTOR": "",
        "XPATH": "xpath=",
        "CLASS_NAME": ".",
        "NAME": None,  # special: [name="..."]
        "TAG_NAME": "",
        "LINK_TEXT": "text=",
    }

    prefix = prefix_map.get(by_attr)
    if prefix is None and by_attr == "NAME":
        if isinstance(selector_node, ast.Constant) and isinstance(selector_node.value, str):
            return ast.Constant(value=f'[name="{selector_node.value}"]')
        return _make_fstring('[name="', selector_node, '"]')

    if prefix is None:
        prefix = ""

    if not prefix:
        return selector_node

    if isinstance(selector_node, ast.Constant) and isinstance(selector_node.value, str):
        return ast.Constant(value=prefix + selector_node.value)

    return _make_fstring(prefix, selector_node)


def _make_fstring(prefix: str, node: ast.expr, suffix: str = "") -> ast.JoinedStr:
    """Build an f-string: f"{prefix}{node}{suffix}"."""
    values: list[ast.expr] = []
    if prefix:
        values.append(ast.Constant(value=prefix))
    if isinstance(node, ast.JoinedStr):
        values.extend(node.values)
    else:
        values.append(ast.FormattedValue(value=node, conversion=-1, format_spec=None))
    if suffix:
        values.append(ast.Constant(value=suffix))
    return ast.JoinedStr(values=values)


def _is_name(node, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_by_pair(node: ast.expr):
    """Check if node is (By.X, selector) tuple. Returns (by_attr, selector_node) or None."""
    if not isinstance(node, ast.Tuple) or len(node.elts) != 2:
        return None
    by_node = node.elts[0]
    if isinstance(by_node, ast.Attribute) and _is_name(by_node.value, "By"):
        return by_node.attr, node.elts[1]
    return None


KEYS_MAP = {
    "ENTER": "Enter",
    "RETURN": "Enter",
    "TAB": "Tab",
    "SPACE": " ",
    "ESCAPE": "Escape",
    "BACKSPACE": "Backspace",
    "DELETE": "Delete",
    "DOWN": "ArrowDown",
    "UP": "ArrowUp",
    "LEFT": "ArrowLeft",
    "RIGHT": "ArrowRight",
    "HOME": "Home",
    "END": "End",
    "PAGE_UP": "PageUp",
    "PAGE_DOWN": "PageDown",
}


def _is_keys_attr(node: ast.expr):
    """Check if node is Keys.X. Returns the playwright key name or None."""
    if isinstance(node, ast.Attribute) and _is_name(node.value, "Keys"):
        return KEYS_MAP.get(node.attr)
    return None


def _flatten_send_keys_arg(node: ast.expr) -> list[dict]:
    """Decompose a send_keys argument (possibly chained with +/*) into flat actions.

    Returns a list of dicts: {"type": "key", "value": "Enter", "count": 1}
                          or {"type": "text", "node": <ast_node>}
    """
    # Single key
    key = _is_keys_attr(node)
    if key:
        return [{"type": "key", "value": key}]

    # Keys.X * N  (repeat)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        key = _is_keys_attr(node.left)
        if key and isinstance(node.right, ast.Constant) and isinstance(node.right.value, int):
            return [{"type": "key", "value": key, "count": node.right.value}]

    # a + b  (concatenation — flatten both sides)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _flatten_send_keys_arg(node.left) + _flatten_send_keys_arg(node.right)

    # Plain text/expression
    return [{"type": "text", "node": node}]


def _make_page_locator(selector_node: ast.expr, frame_var: str | None = None) -> ast.Call:
    """Build: page.locator(selector_node) or frame.locator(selector_node) if inside a frame."""
    target = _make_name(frame_var) if frame_var else _make_name(PW_PAGE)
    return ast.Call(
        func=ast.Attribute(value=target, attr="locator", ctx=ast.Load()),
        args=[selector_node],
        keywords=[],
    )


def _make_method_call(obj: ast.expr, method: str, args=None, keywords=None) -> ast.Call:
    return ast.Call(
        func=ast.Attribute(value=obj, attr=method, ctx=ast.Load()),
        args=args or [],
        keywords=keywords or [],
    )


def _make_name(name: str) -> ast.Name:
    return ast.Name(id=name, ctx=ast.Load())


def _source_name_or_node(node: ast.expr) -> str:
    """Extract a variable name from a node, or return a placeholder."""
    if isinstance(node, ast.Name):
        return node.id
    # For complex expressions (e.g. find_element result), we can't get a simple name.
    # Return a sentinel that _transform_select_call will handle.
    return node


# ---------------------------------------------------------------------------
# Pre-pass: rename `page` parameter → `page_url` in functions with webdriver
# ---------------------------------------------------------------------------

class PageParamRenamer(ast.NodeTransformer):
    """Rename the `page` param/variable to `page_url` inside functions that
    call create_webdriver(), so that `page` is free for the Playwright Page."""

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # Check if this function body (transitively) calls create_webdriver
        has_webdriver = any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "create_webdriver"
            for child in ast.walk(node)
        )
        if has_webdriver:
            # Rename the 'page' parameter in the signature
            for arg in node.args.args:
                if arg.arg == "page":
                    arg.arg = "page_url"
            # Also rename annotation if present
            for arg in node.args.args:
                if arg.arg == "page_url" and arg.annotation:
                    pass  # keep annotation as-is
            # Rename all Name(id='page') references to 'page_url' in the body
            _NameRenamer("page", "page_url").visit(node)
        self.generic_visit(node)
        return node


class _NameRenamer(ast.NodeTransformer):
    """Rename all ast.Name nodes matching old → new."""
    def __init__(self, old: str, new: str):
        self.old = old
        self.new = new

    def visit_Name(self, node: ast.Name):
        if node.id == self.old:
            node.id = self.new
        return node


# ---------------------------------------------------------------------------
# Report mode — inventory Selenium patterns without transforming
# ---------------------------------------------------------------------------

class SeleniumReporter(ast.NodeVisitor):
    def __init__(self):
        self.imports: list[str] = []
        self.by_usage: dict[str, int] = {}
        self.ec_usage: dict[str, int] = {}
        self.driver_methods: dict[str, int] = {}
        self.has_select = False
        self.has_keys = False
        self.has_execute_script = False
        self.has_switch_to_frame = False
        self.sleep_count = 0

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module and "selenium" in node.module:
            self.imports.append(node.module)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if _is_name(getattr(node, "value", None), "By"):
            self.by_usage[node.attr] = self.by_usage.get(node.attr, 0) + 1
        if _is_name(getattr(node, "value", None), "EC"):
            self.ec_usage[node.attr] = self.ec_usage.get(node.attr, 0) + 1
        if _is_name(getattr(node, "value", None), "Keys"):
            self.has_keys = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Attribute):
            if _is_name(node.func.value, "driver"):
                m = node.func.attr
                self.driver_methods[m] = self.driver_methods.get(m, 0) + 1
        if isinstance(node.func, ast.Name) and node.func.id == "Select":
            self.has_select = True
        if isinstance(node.func, ast.Attribute) and _is_name(node.func.value, "time") and node.func.attr == "sleep":
            self.sleep_count += 1
        self.generic_visit(node)


def report_file(path: Path) -> dict:
    source = path.read_text()
    tree = ast.parse(source)
    r = SeleniumReporter()
    r.visit(tree)
    return {
        "file": path.name,
        "imports": r.imports,
        "by": r.by_usage,
        "ec": r.ec_usage,
        "driver_methods": r.driver_methods,
        "select": r.has_select,
        "keys": r.has_keys,
        "sleeps": r.sleep_count,
    }


# ---------------------------------------------------------------------------
# Main transformer
# ---------------------------------------------------------------------------

class SeleniumToPlaywright(ast.NodeTransformer):

    def __init__(self):
        self.wait_vars: set[str] = set()       # variables assigned from WebDriverWait(...)
        self.select_vars: dict[str, str] = {}   # var → source locator var name
        self.driver_var = "driver"
        # Frame tracking: when inside a frame, locators go through self.frame_var
        self.frame_var: str | None = None       # e.g. "frame" when inside an iframe
        # Track var → selector for locator assignments (for frame_locator resolution)
        self.locator_selectors: dict[str, ast.expr] = {}
        # Track variables that are Playwright locators (from .all() iteration etc.)
        self.locator_loop_vars: set[str] = set()
        # Track variables that hold lists of locators (from .all() assignments)
        self._locator_list_vars: set[str] = set()

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module and node.module.startswith("selenium"):
            return None
        # Strip create_webdriver (replaced by Playwright boilerplate)
        node.names = [a for a in node.names if a.name != "create_webdriver"]
        if not node.names:
            return None
        return node

    def visit_Import(self, node: ast.Import):
        names = [alias for alias in node.names if not alias.name.startswith("selenium")]
        if not names:
            return None
        node.names = names
        return node

    # ------------------------------------------------------------------
    # Strip time.sleep() and expand compound send_keys
    # ------------------------------------------------------------------

    def visit_Expr(self, node: ast.Expr):
        # Check for standalone waits BEFORE generic_visit transforms the inner Call
        if isinstance(node.value, ast.Call):
            result = self._try_transform_wait_until(node.value, standalone=True)
            if result is not None:
                if result == "STRIP":
                    return None
                node.value = result
                # Still need to visit children of the transformed node
                self.generic_visit(node)
                return node

        self.generic_visit(node)
        if not hasattr(node, "value") or node.value is None:
            return None
        # Handle send_keys expansion (fill + press → two statements)
        if hasattr(node.value, "_send_keys_expansion"):
            return [ast.Expr(value=expr) for expr in node.value._send_keys_expansion]
        # Strip standalone time.sleep(...)
        if isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and _is_name(func.value, "time") and func.attr == "sleep":
                return None
        return node

    # ------------------------------------------------------------------
    # Assignments — track wait vars, select vars, transform RHS
    # ------------------------------------------------------------------

    def _make_browser_boilerplate(self, lineno: int) -> list[ast.stmt]:
        """Generate _ctx = await _get_browser_pool().new_context() + page = ... + route blocker."""
        stmts = []

        # _ctx = await _get_browser_pool().new_context()
        stmts.append(ast.Assign(
            targets=[ast.Name(id="_ctx", ctx=ast.Store())],
            value=ast.Await(value=_make_method_call(
                ast.Call(func=_make_name("_get_browser_pool"), args=[], keywords=[]),
                "new_context",
            )),
            lineno=lineno,
        ))

        # page = await _ctx.new_page()
        stmts.append(ast.Assign(
            targets=[ast.Name(id=PW_PAGE, ctx=ast.Store())],
            value=ast.Await(value=_make_method_call(_make_name("_ctx"), "new_page")),
            lineno=lineno,
        ))

        # Resource blocking (images etc.) is handled by Camoufox at the
        # browser level via block_images=True, so no page.route() needed.

        return stmts

    def visit_Assign(self, node: ast.Assign):
        self.generic_visit(node)

        # Detect: wait = WebDriverWait(driver, N)
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and _is_name(node.value.func, "WebDriverWait")
        ):
            self.wait_vars.add(node.targets[0].id)
            return None  # strip

        # Detect: var = WebDriverWait(driver, N).until(...)
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Call):
                result = self._try_transform_wait_until(node.value, standalone=False)
                if result is not None and result != "STRIP":
                    node.value = result
                    return node

        # Detect: dropdown = Select(element)
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and _is_name(node.value.func, "Select")
            and node.value.args
        ):
            var_name = node.targets[0].id
            source = node.value.args[0]
            if isinstance(source, ast.Name):
                # Simple: Select(var) → track and strip
                self.select_vars[var_name] = source.id
                return None
            else:
                # Complex: Select(driver.find_element(...)) → already transformed
                # to e.g. page.locator('#address').first — keep as assignment
                # Strip .first if present (select_option works on locator, not element)
                if isinstance(source, ast.Attribute) and source.attr == "first":
                    source = source.value
                self.select_vars[var_name] = var_name  # self-referencing
                node.value = source
                return node

        # Detect: driver = create_webdriver(...)
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and _is_name(node.value.func, "create_webdriver")
        ):
            target_name = node.targets[0].id
            self.driver_var = target_name
            return self._make_browser_boilerplate(node.lineno)

        # Detect: driver = kwargs.get('web_driver') or kwargs.get("web_driver")
        # Only match when the TARGET is the driver var (e.g. `driver = kwargs.get('web_driver')`),
        # not when extracting kwargs for later use (e.g. `web_driver = kwargs.get('web_driver')`).
        # Replace with browser boilerplate (driver was passed in, not created locally).
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == self.driver_var  # target must be the driver var
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "get"
            and _is_name(node.value.func.value, "kwargs")
            and node.value.args
            and isinstance(node.value.args[0], ast.Constant)
            and node.value.args[0].value == "web_driver"
        ):
            return self._make_browser_boilerplate(node.lineno)

        # Track locator selectors: var = page.locator(selector) → remember selector
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "locator"
            and node.value.args
        ):
            self.locator_selectors[node.targets[0].id] = node.value.args[0]

        # Track locator list vars: var = something.all() or something.all()[slice]
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            val = node.value
            is_all_call = (
                isinstance(val, ast.Call)
                and isinstance(val.func, ast.Attribute)
                and val.func.attr == "all"
            )
            is_sliced_all = (
                isinstance(val, ast.Subscript)
                and isinstance(val.value, ast.Call)
                and isinstance(val.value.func, ast.Attribute)
                and val.value.func.attr == "all"
            )
            if is_all_call or is_sliced_all:
                self._locator_list_vars.add(node.targets[0].id)

        return node

    # ------------------------------------------------------------------
    # For loops — track locator iteration variables for .text → .text_content()
    # ------------------------------------------------------------------

    def visit_For(self, node: ast.For):
        # First, transform the iterable (but not the body yet)
        node.iter = self.visit(node.iter)
        node.target = self.visit(node.target) if isinstance(node.target, ast.AST) else node.target

        # NOW check if iterating over .all() — the loop var is a Playwright Locator
        iter_node = node.iter
        is_locator_iter = self._is_locator_all_iter(iter_node)

        if is_locator_iter:
            # Direct: for var in x.all()
            if isinstance(node.target, ast.Name):
                self.locator_loop_vars.add(node.target.id)
            # Enumerate: for idx, var in enumerate(x.all())
            elif isinstance(node.target, ast.Tuple):
                for elt in node.target.elts:
                    if isinstance(elt, ast.Name) and elt.id != "_":
                        # In enumerate, the second element is the locator
                        pass
                # Specifically track the last element (the value, not index)
                if len(node.target.elts) >= 2 and isinstance(node.target.elts[-1], ast.Name):
                    self.locator_loop_vars.add(node.target.elts[-1].id)

        # Now transform the body (where .text references live)
        new_body = []
        for stmt in node.body:
            result = self.visit(stmt)
            if result is None:
                continue
            if isinstance(result, list):
                new_body.extend(result)
            else:
                new_body.append(result)
        node.body = new_body or [ast.Pass()]

        if node.orelse:
            new_orelse = []
            for stmt in node.orelse:
                result = self.visit(stmt)
                if result is None:
                    continue
                if isinstance(result, list):
                    new_orelse.extend(result)
                else:
                    new_orelse.append(result)
            node.orelse = new_orelse

        return node

    # ------------------------------------------------------------------
    # List/generator comprehensions — track locator iteration vars
    # ------------------------------------------------------------------

    def _visit_comprehension(self, node):
        """Shared logic for ListComp, SetComp, GeneratorExp."""
        # Transform generators first, then track loop vars, then transform elt/value
        for gen in node.generators:
            gen.iter = self.visit(gen.iter)
            # Track if iterating over .all()
            if isinstance(gen.target, ast.Name):
                iter_node = gen.iter
                is_locator = (
                    (isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Attribute) and iter_node.func.attr == "all")
                    or (isinstance(iter_node, ast.Name) and iter_node.id in self._locator_list_vars)
                )
                if is_locator:
                    self.locator_loop_vars.add(gen.target.id)
            # Transform conditions
            gen.ifs = [self.visit(if_clause) for if_clause in gen.ifs]
        # Transform the output expression
        if hasattr(node, "elt"):
            node.elt = self.visit(node.elt)
        if hasattr(node, "key"):
            node.key = self.visit(node.key)
            node.value = self.visit(node.value)
        return node

    def visit_ListComp(self, node):
        return self._visit_comprehension(node)

    def visit_SetComp(self, node):
        return self._visit_comprehension(node)

    def visit_GeneratorExp(self, node):
        return self._visit_comprehension(node)

    def visit_DictComp(self, node):
        return self._visit_comprehension(node)

    # ------------------------------------------------------------------
    # General Call transformations
    # ------------------------------------------------------------------

    def visit_Call(self, node: ast.Call):
        self.generic_visit(node)

        # --- wait.until(EC.*(...)) ---
        result = self._try_transform_wait_until(node, standalone=False)
        if result is not None and result != "STRIP":
            return result

        # --- driver.method(...) calls ---
        if isinstance(node.func, ast.Attribute) and _is_name(node.func.value, self.driver_var):
            method = node.func.attr

            if method == "get":
                node.func.value = _make_name(PW_PAGE)
                node.func.attr = "goto"
                return node

            if method == "find_element" and node.args:
                return self._transform_find_element(node, single=True)

            if method == "find_elements" and node.args:
                return self._transform_find_element(node, single=False)

            if method == "execute_script":
                return self._transform_execute_script(node)

            if method == "refresh":
                node.func.value = _make_name(PW_PAGE)
                node.func.attr = "reload"
                return node

            if method == "maximize_window":
                return None

            if method == "set_window_size":
                w = node.args[0] if node.args else ast.Constant(value=1920)
                h = node.args[1] if len(node.args) > 1 else ast.Constant(value=1080)
                return ast.Call(
                    func=ast.Attribute(value=_make_name(PW_PAGE), attr="set_viewport_size", ctx=ast.Load()),
                    args=[ast.Dict(keys=[ast.Constant("width"), ast.Constant("height")], values=[w, h])],
                    keywords=[],
                )

            if method == "quit":
                pass  # handled at statement level in visit_If

        # --- Select var method calls ---
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            var_name = node.func.value.id
            if var_name in self.select_vars:
                return self._transform_select_call(node, self.select_vars[var_name])

        # --- element.find_element(By.*, sel) on non-driver objects ---
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("find_element", "find_elements"):
            if node.args and len(node.args) >= 2:
                by_node = node.args[0]
                if isinstance(by_node, ast.Attribute) and _is_name(by_node.value, "By"):
                    pw_sel = by_to_selector(by_node.attr, node.args[1])
                    locator = _make_method_call(node.func.value, "locator", [pw_sel])
                    if node.func.attr == "find_element":
                        return ast.Attribute(value=locator, attr="first", ctx=ast.Load())
                    else:
                        return _make_method_call(locator, "all")

        # --- driver.switch_to.frame(x) → frame = page.frame_locator(selector) ---
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "frame"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "switch_to"
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == self.driver_var
            and node.args
        ):
            arg = node.args[0]
            # Resolve the selector: if arg is a variable we tracked, use its selector
            if isinstance(arg, ast.Name) and arg.id in self.locator_selectors:
                selector = self.locator_selectors[arg.id]
            else:
                selector = arg  # pass through as-is (might need manual review)
            self.frame_var = "frame"
            # Return: frame = page.frame_locator(selector)
            return ast.Assign(
                targets=[ast.Name(id="frame", ctx=ast.Store())],
                value=ast.Call(
                    func=ast.Attribute(value=_make_name(PW_PAGE), attr="frame_locator", ctx=ast.Load()),
                    args=[selector], keywords=[],
                ),
            )

        # --- driver.switch_to.default_content() → clear frame context ---
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "default_content"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "switch_to"
        ):
            self.frame_var = None
            return None  # strip the call

        # --- driver.switch_to.window(handle) → handle.bring_to_front() ---
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "window"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "switch_to"
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == self.driver_var
            and node.args
        ):
            return _make_method_call(node.args[0], "bring_to_front")

        # --- Inline Select(el).method(...) chains (no intermediate variable) ---
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in ("select_by_value", "select_by_index", "select_by_visible_text")
            and isinstance(node.func.value, ast.Call)
            and _is_name(node.func.value.func, "Select")
            and node.func.value.args
        ):
            source = node.func.value.args[0]
            return self._transform_select_call(node, _source_name_or_node(source))

        # --- driver.switch_to.active_element → page.locator(':focus') ---
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "active_element"
            and isinstance(node.func.value.value, ast.Attribute)
            and node.func.value.value.attr == "switch_to"
            and isinstance(node.func.value.value.value, ast.Name)
            and node.func.value.value.value.id == self.driver_var
        ):
            # Rewrite: page.locator(':focus').method(...)
            node.func.value = _make_page_locator(ast.Constant(value=":focus"), self.frame_var)
            # Don't return — fall through so send_keys/etc transform can also run

        # --- Standalone driver.quit() not in `if driver:` pattern ---
        if (
            isinstance(node.func, ast.Attribute)
            and _is_name(node.func.value, self.driver_var)
            and node.func.attr == "quit"
        ):
            # Replace with await _ctx.close()
            node.func.value = _make_name("_ctx")
            node.func.attr = "close"
            return ast.Await(value=node)

        # --- element.clear() → element.fill("") ---
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "clear"
            and not node.args
            and not _is_name(node.func.value, "self")
        ):
            return _make_method_call(node.func.value, "fill", [ast.Constant(value="")])

        # --- element.send_keys(...) → fill/press ---
        if isinstance(node.func, ast.Attribute) and node.func.attr == "send_keys":
            result = self._transform_send_keys(node)
            if isinstance(result, list):
                node._send_keys_expansion = result
                return node
            return result

        return node

    # ------------------------------------------------------------------
    # Attribute access transformations
    # ------------------------------------------------------------------

    def visit_Attribute(self, node: ast.Attribute):
        self.generic_visit(node)

        # driver.page_source → page.content()
        if _is_name(node.value, self.driver_var) and node.attr == "page_source":
            return ast.Call(
                func=ast.Attribute(value=_make_name(PW_PAGE), attr="content", ctx=ast.Load()),
                args=[], keywords=[],
            )

        # select_var.options → source_var.locator("option").all()
        if isinstance(node.value, ast.Name) and node.value.id in self.select_vars and node.attr == "options":
            source_var = self.select_vars[node.value.id]
            return _make_method_call(
                _make_method_call(_make_name(source_var), "locator", [ast.Constant(value="option")]),
                "all",
            )

        # driver.current_url → page.url
        if _is_name(node.value, self.driver_var) and node.attr == "current_url":
            return ast.Attribute(value=_make_name(PW_PAGE), attr="url", ctx=ast.Load())

        # driver.current_window_handle → page (Playwright has no window handles, page IS the handle)
        if _is_name(node.value, self.driver_var) and node.attr == "current_window_handle":
            return _make_name(PW_PAGE)

        # driver.window_handles → _ctx.pages
        if _is_name(node.value, self.driver_var) and node.attr == "window_handles":
            return ast.Attribute(value=_make_name("_ctx"), attr="pages", ctx=ast.Load())

        # driver.title → page.title()
        if _is_name(node.value, self.driver_var) and node.attr == "title":
            return ast.Call(
                func=ast.Attribute(value=_make_name(PW_PAGE), attr="title", ctx=ast.Load()),
                args=[], keywords=[],
            )

        # locator_var.text → locator_var.text_content()
        # Catches: known locator loop vars, and expression chains ending in
        # .first, .last (which produce Playwright Locator objects)
        if node.attr == "text" and self._is_locator_expr(node.value):
            return ast.Call(
                func=ast.Attribute(value=node.value, attr="text_content", ctx=ast.Load()),
                args=[], keywords=[],
            )

        return node

    def _is_locator_all_iter(self, node: ast.expr) -> bool:
        """Check if node is .all(), .all()[slice], enumerate(.all()), or a locator list var."""
        # Direct .all()
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "all"
        ):
            return True
        # Sliced .all()[1:] etc.
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "all"
        ):
            return True
        # enumerate(.all())
        if (
            isinstance(node, ast.Call)
            and _is_name(node.func, "enumerate")
            and node.args
            and self._is_locator_all_iter(node.args[0])
        ):
            return True
        # Variable known to hold a locator list
        if isinstance(node, ast.Name) and node.id in self._locator_list_vars:
            return True
        return False

    def _is_locator_expr(self, node: ast.expr) -> bool:
        """Heuristic: is this node likely a Playwright Locator expression?"""
        # Known loop var from .all() iteration
        if isinstance(node, ast.Name) and node.id in self.locator_loop_vars:
            return True
        # expr.first or expr.last
        if isinstance(node, ast.Attribute) and node.attr in ("first", "last"):
            return True
        # expr.locator(...) or expr.nth(...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("locator", "nth"):
                return True
        return False

    # ------------------------------------------------------------------
    # If statements — transform `if driver: driver.quit()` → cleanup
    # ------------------------------------------------------------------

    def visit_If(self, node: ast.If):
        # Check BEFORE generic_visit so inner driver.quit() hasn't been transformed yet
        if (
            _is_name(node.test, self.driver_var)
            and len(node.body) == 1
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Call)
            and isinstance(node.body[0].value.func, ast.Attribute)
            and _is_name(node.body[0].value.func.value, self.driver_var)
            and node.body[0].value.func.attr == "quit"
        ):
            close_stmt = ast.If(
                test=_make_name("_ctx"),
                body=[ast.Expr(value=ast.Await(value=_make_method_call(_make_name("_ctx"), "close")))],
                orelse=[],
            )
            return [close_stmt]

        # Also handle: `if driver:` (non-quit) → `if _ctx:`
        if _is_name(node.test, self.driver_var):
            node.test = _make_name("_ctx")

        # Also handle: `if not driver:` → `if not _ctx:`
        if (
            isinstance(node.test, ast.UnaryOp)
            and isinstance(node.test.op, ast.Not)
            and _is_name(node.test.operand, self.driver_var)
        ):
            node.test.operand = _make_name("_ctx")

        # Handle: if 'driver' in locals() → if '_ctx' in locals()
        if (
            isinstance(node.test, ast.Compare)
            and len(node.test.comparators) == 1
            and isinstance(node.test.left, ast.Constant)
            and node.test.left.value == self.driver_var
            and isinstance(node.test.ops[0], ast.In)
        ):
            node.test.left = ast.Constant(value="_ctx")

        self.generic_visit(node)
        return node

    # ------------------------------------------------------------------
    # ExceptHandler — rename exception types
    # ------------------------------------------------------------------

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        self.generic_visit(node)
        if node.type:
            node.type = self._rename_exception(node.type)
        return node

    def visit_Name(self, node: ast.Name):
        return node

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _try_transform_wait_until(self, node: ast.Call, standalone: bool):
        """Detect WebDriverWait(...).until(EC.*(...)) or wait.until(EC.*(...))."""
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "until":
            return None

        caller = node.func.value
        is_inline_wait = isinstance(caller, ast.Call) and _is_name(caller.func, "WebDriverWait")
        is_var_wait = isinstance(caller, ast.Name) and caller.id in self.wait_vars

        if not is_inline_wait and not is_var_wait:
            return None
        if not node.args:
            return "STRIP"

        condition = node.args[0]

        if isinstance(condition, ast.Lambda):
            return "STRIP" if standalone else None

        if isinstance(condition, ast.Call) and isinstance(condition.func, ast.Attribute):
            if _is_name(condition.func.value, "EC"):
                return self._transform_ec_call(condition.func.attr, condition, standalone)

        return "STRIP" if standalone else None

    def _transform_ec_call(self, ec_method: str, condition: ast.Call, standalone: bool):
        """Transform EC.method((By.X, selector)) into Playwright locator."""
        if not condition.args:
            return "STRIP"

        by_pair = _is_by_pair(condition.args[0])
        if not by_pair:
            return "STRIP"

        by_attr, selector_node = by_pair
        pw_selector = by_to_selector(by_attr, selector_node)
        locator = _make_page_locator(pw_selector, self.frame_var)

        if ec_method in ("presence_of_element_located", "element_to_be_clickable", "visibility_of_element_located"):
            if standalone:
                # Standalone wait (not assigned) — must actually wait, not just create locator
                return _make_method_call(locator, "wait_for")
            return locator

        if ec_method == "invisibility_of_element_located":
            return _make_method_call(locator, "wait_for",
                keywords=[ast.keyword(arg="state", value=ast.Constant(value="hidden"))])

        if ec_method == "presence_of_all_elements_located":
            return _make_method_call(locator, "all")

        if ec_method == "frame_to_be_available_and_switch_to_it":
            return ast.Call(
                func=ast.Attribute(value=_make_name(PW_PAGE), attr="frame_locator", ctx=ast.Load()),
                args=[pw_selector], keywords=[],
            )

        if ec_method == "text_to_be_present_in_element":
            return locator

        return locator

    def _transform_find_element(self, node: ast.Call, single: bool) -> ast.Call:
        """Transform driver.find_element(By.X, sel) → page.locator(sel)[.first]"""
        if len(node.args) >= 2:
            by_node = node.args[0]
            sel_node = node.args[1]
            if isinstance(by_node, ast.Attribute) and _is_name(by_node.value, "By"):
                pw_selector = by_to_selector(by_node.attr, sel_node)
                locator = _make_page_locator(pw_selector, self.frame_var)
                if single:
                    return ast.Attribute(value=locator, attr="first", ctx=ast.Load())
                else:
                    return _make_method_call(locator, "all")
        return node

    def _transform_execute_script(self, node: ast.Call) -> ast.Call:
        """Transform driver.execute_script(js, *args).

        Selenium: driver.execute_script("arguments[0].click()", element)
        Playwright: element.evaluate("el => el.click()")

        Falls back to page.evaluate(js) for scripts without element args.
        """
        if not node.args:
            node.func.value = _make_name(PW_PAGE)
            node.func.attr = "evaluate"
            return node

        js_node = node.args[0]
        extra_args = node.args[1:]

        # Check for arguments[0] pattern in the JS string
        if (
            extra_args
            and isinstance(js_node, ast.Constant)
            and isinstance(js_node.value, str)
            and "arguments[0]" in js_node.value
        ):
            # Rewrite: element.evaluate("el => <body>")
            # Replace "arguments[0]" with "el" in the JS
            new_js = js_node.value.replace("arguments[0]", "el")
            # Strip trailing semicolons for arrow function body
            new_js = new_js.rstrip("; ")
            new_js = f"el => {new_js}"
            return _make_method_call(
                extra_args[0],
                "evaluate",
                [ast.Constant(value=new_js)],
            )

        # No arguments pattern — simple page.evaluate(js)
        node.func.value = _make_name(PW_PAGE)
        node.func.attr = "evaluate"
        return node

    def _transform_send_keys(self, node: ast.Call) -> ast.expr | list[ast.expr]:
        """Transform element.send_keys(...) → fill() / press().

        Handles complex chains like Keys.TAB * 2 + Keys.ENTER, text + Keys.TAB, etc.
        by decomposing the BinOp tree into a flat list of actions.
        """
        obj = node.func.value
        if not node.args:
            return node

        arg = node.args[0]
        parts = _flatten_send_keys_arg(arg)
        actions = []
        for part in parts:
            if part["type"] == "key":
                for _ in range(part.get("count", 1)):
                    actions.append(_make_method_call(copy.deepcopy(obj), "press", [ast.Constant(value=part["value"])]))
            elif part["type"] == "text":
                actions.append(_make_method_call(copy.deepcopy(obj), "fill", [part["node"]]))

        if len(actions) == 1:
            return actions[0]
        return actions

    def _transform_select_call(self, node: ast.Call, source_var) -> ast.Call:
        """Transform Select(el).select_by_*(val) → el.select_option(...).

        source_var can be a string (variable name) or an ast.expr node.
        """
        method = node.func.attr
        source = _make_name(source_var) if isinstance(source_var, str) else source_var
        if not node.args:
            return node

        if method == "select_by_value":
            return _make_method_call(source, "select_option",
                keywords=[ast.keyword(arg="value", value=node.args[0])])
        if method == "select_by_index":
            return _make_method_call(source, "select_option",
                keywords=[ast.keyword(arg="index", value=node.args[0])])
        if method == "select_by_visible_text":
            return _make_method_call(source, "select_option",
                keywords=[ast.keyword(arg="label", value=node.args[0])])

        return node

    def _rename_exception(self, node: ast.expr) -> ast.expr:
        """Rename Selenium exceptions to Playwright equivalents."""
        if isinstance(node, ast.Name):
            mapping = {
                "TimeoutException": "TimeoutError",
                "NoSuchElementException": "TimeoutError",
                "StaleElementReferenceException": "TimeoutError",
            }
            if node.id in mapping:
                node.id = mapping[node.id]
        elif isinstance(node, ast.Tuple):
            node.elts = [self._rename_exception(e) for e in node.elts]
            seen = set()
            unique = []
            for e in node.elts:
                key = ast.dump(e)
                if key not in seen:
                    seen.add(key)
                    unique.append(e)
            node.elts = unique
            if len(node.elts) == 1:
                return node.elts[0]
        return node


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def inject_playwright_import(tree: ast.Module) -> None:
    """Add ``from api.services.browser_pool import get as _get_browser_pool`` and
    ``from __future__ import annotations`` at the top.

    The __future__ import ensures Selenium type annotations (e.g. WebDriver)
    that survived transpilation are never evaluated at runtime.
    The browser_pool import is only added if the transpiled code actually
    references _get_browser_pool (scrapers without create_webdriver don't need it).
    """
    # Only inject browser_pool import if the code actually uses it
    _uses_pool = any(
        isinstance(node, ast.Name) and node.id == "_get_browser_pool"
        for node in ast.walk(tree)
    )
    pw_import = ast.ImportFrom(
        module="api.services.browser_pool",
        names=[ast.alias(name="get", asname="_get_browser_pool")],
        level=0,
    ) if _uses_pool else None
    # Check if __future__ annotations import already exists
    has_future = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(a.name == "annotations" for a in node.names)
        for node in tree.body
    )
    insert_idx = 0
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("__future__"):
            insert_idx = i + 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            insert_idx = i + 1
        else:
            break
    if pw_import is not None:
        tree.body.insert(insert_idx, pw_import)
    if not has_future:
        future_import = ast.ImportFrom(
            module="__future__",
            names=[ast.alias(name="annotations")],
            level=0,
        )
        tree.body.insert(0, future_import)


def fix_driver_none(tree: ast.Module, driver_var: str = "driver") -> None:
    """Replace `driver = None` with `_ctx = None`."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        new_body = []
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == driver_var
                and isinstance(stmt.value, ast.Constant)
                and stmt.value.value is None
            ):
                # Replace with: _ctx = None
                ctx_none = ast.Assign(
                    targets=[ast.Name(id="_ctx", ctx=ast.Store())],
                    value=ast.Constant(value=None),
                    lineno=stmt.lineno,
                )
                new_body.append(ctx_none)
            else:
                new_body.append(stmt)
        node.body = new_body


def strip_time_imports(tree: ast.Module) -> None:
    """Remove all `import time` statements (module-level and inline).

    Since we strip time.sleep() calls, time is typically no longer needed.
    If time is still referenced for non-sleep purposes, we keep the import.
    """
    # Check if 'time' is referenced anywhere that's NOT an import statement
    time_used = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            continue
        if isinstance(node, ast.Name) and node.id == "time":
            time_used = True
            break
        if isinstance(node, ast.Attribute) and isinstance(getattr(node, "value", None), ast.Name) and node.value.id == "time":
            time_used = True
            break

    if time_used:
        return

    # Strip all `import time` — both module-level and inline
    def _strip_time_from_body(stmts: list) -> list:
        return [s for s in stmts if not (isinstance(s, ast.Import) and len(s.names) == 1 and s.names[0].name == "time")]

    tree.body = _strip_time_from_body(tree.body)
    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            stmts = getattr(node, attr, None)
            if isinstance(stmts, list):
                new_stmts = _strip_time_from_body(stmts)
                if len(new_stmts) != len(stmts):
                    setattr(node, attr, new_stmts)


# ---------------------------------------------------------------------------
# Handle switch_to.frame — needs special Call-level handling
# ---------------------------------------------------------------------------

class FrameSwitchTransformer(ast.NodeTransformer):
    """Second pass: transform driver.switch_to.frame(x) → page.frame_locator(...)."""

    def visit_Call(self, node: ast.Call):
        self.generic_visit(node)

        # driver.switch_to.frame(element)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "frame"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "switch_to"
            and isinstance(node.func.value.value, ast.Name)
        ):
            node.func = ast.Attribute(
                value=_make_name(PW_PAGE), attr="frame_locator", ctx=ast.Load(),
            )
            return node

        # driver.switch_to.default_content() → strip
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "default_content"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "switch_to"
        ):
            return None

        return node

    def visit_Expr(self, node: ast.Expr):
        self.generic_visit(node)
        if not hasattr(node, "value") or node.value is None:
            return None
        return node


# ---------------------------------------------------------------------------
# Flatten lists returned by multi-statement expansions
# ---------------------------------------------------------------------------

class StatementFlattener(ast.NodeTransformer):
    def _flatten(self, stmts):
        if stmts is None:
            return stmts
        result = []
        for s in stmts:
            if isinstance(s, list):
                result.extend(s)
            else:
                result.append(s)
        return result

    def visit_Module(self, node):
        self.generic_visit(node)
        node.body = self._flatten(node.body)
        return node

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.body = self._flatten(node.body)
        return node

    def visit_If(self, node):
        self.generic_visit(node)
        node.body = self._flatten(node.body)
        node.orelse = self._flatten(node.orelse)
        return node

    def visit_Try(self, node):
        self.generic_visit(node)
        node.body = self._flatten(node.body)
        node.orelse = self._flatten(node.orelse)
        node.finalbody = self._flatten(node.finalbody)
        return node

    def visit_TryStar(self, node):
        self.generic_visit(node)
        node.body = self._flatten(node.body)
        node.orelse = self._flatten(node.orelse)
        node.finalbody = self._flatten(node.finalbody)
        return node

    def visit_For(self, node):
        self.generic_visit(node)
        node.body = self._flatten(node.body)
        node.orelse = self._flatten(node.orelse)
        return node

    def visit_While(self, node):
        self.generic_visit(node)
        node.body = self._flatten(node.body)
        node.orelse = self._flatten(node.orelse)
        return node

    def visit_With(self, node):
        self.generic_visit(node)
        node.body = self._flatten(node.body)
        return node

    def visit_ExceptHandler(self, node):
        self.generic_visit(node)
        node.body = self._flatten(node.body)
        return node


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Async conversion: sync Playwright → async Playwright
# ---------------------------------------------------------------------------

# Playwright method names that are async (require `await` in the async API).
# Excludes sync methods like locator(), frame_locator(), nth(), and properties.
# NOTE: start/stop/close are handled at AST generation time (in the create_webdriver
# and driver.quit() transforms) because they clash with common non-Playwright methods
# (e.g. re.Match.start(), httpx.Client.close()).
PLAYWRIGHT_ASYNC_METHODS = frozenset({
    # Playwright lifecycle — start/stop/close/launch/new_page/new_context handled at generation time
    # Page navigation/info
    'goto', 'content', 'reload', 'title', 'evaluate',
    'set_viewport_size', 'wait_for_load_state',
    # Locator actions
    'click', 'dblclick', 'fill', 'press',
    'select_option', 'check', 'uncheck', 'hover',
    'text_content', 'inner_text', 'inner_html',
    'get_attribute', 'input_value',
    'all', 'count', 'wait_for',
    'is_visible', 'is_hidden',
    'screenshot',
    'bring_to_front',
})


class WrapAwaitPass(ast.NodeTransformer):
    """Wrap Playwright async method calls in ``await`` expressions.

    Walks the AST bottom-up so inner calls are wrapped before outer ones.
    Only wraps calls whose outermost method name is in PLAYWRIGHT_ASYNC_METHODS.
    """

    def visit_Call(self, node: ast.Call):
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in PLAYWRIGHT_ASYNC_METHODS
        ):
            return ast.Await(value=node)
        return node


def _func_contains_await(node: ast.FunctionDef) -> bool:
    """Check if a sync function body contains Await nodes (excluding nested functions)."""
    for child in ast.walk(node):
        if child is node:
            continue
        # Don't descend into nested function definitions
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not node:
            continue
        if isinstance(child, ast.Await):
            return True
    return False


def _upgrade_to_async(node: ast.FunctionDef) -> ast.AsyncFunctionDef:
    """Convert a FunctionDef to AsyncFunctionDef."""
    async_func = ast.AsyncFunctionDef(
        name=node.name,
        args=node.args,
        body=node.body,
        decorator_list=node.decorator_list,
        returns=node.returns,
        type_comment=getattr(node, 'type_comment', None),
    )
    ast.copy_location(node, async_func)
    return async_func


def make_parse_data_async(tree: ast.Module) -> None:
    """Convert any ``def`` containing ``await`` nodes to ``async def``.

    This handles parse_data and any helper functions that contain Playwright calls.
    Runs after WrapAwaitPass has inserted await expressions.
    """
    # Collect functions that need upgrading across all scopes
    for parent in ast.walk(tree):
        body = getattr(parent, 'body', None)
        if not isinstance(body, list):
            continue
        new_body = []
        for item in body:
            if isinstance(item, ast.FunctionDef) and _func_contains_await(item):
                new_body.append(_upgrade_to_async(item))
            else:
                new_body.append(item)
        parent.body = new_body


def _wrap_async_func_calls(tree: ast.Module) -> None:
    """Wrap calls to async functions in ``await`` if not already awaited.

    After make_parse_data_async, some calls to newly-async functions may not
    be awaited (e.g. `result = get_helper(page)` where get_helper is now async).
    """
    # Collect names of all async functions defined in the module
    async_func_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            async_func_names.add(node.name)

    if not async_func_names:
        return

    class _AwaitInserter(ast.NodeTransformer):
        def visit_Call(self, node: ast.Call):
            self.generic_visit(node)
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name and func_name in async_func_names:
                # Check if already inside an Await
                return ast.Await(value=node)
            return node

        def visit_Await(self, node: ast.Await):
            # Don't descend into Await — the inner call doesn't need double-wrapping
            return node

    _AwaitInserter().visit(tree)


def transpile(source: str) -> str:
    """Transpile a Selenium Python source string to async Playwright."""
    tree = ast.parse(source)

    # Pre-pass: rename `page` param → `page_url` to avoid collision with Playwright's page
    tree = PageParamRenamer().visit(tree)

    # Pass 1: main Selenium → Playwright transforms
    transformer = SeleniumToPlaywright()
    tree = transformer.visit(tree)

    # Pass 2: flatten multi-statement expansions
    tree = StatementFlattener().visit(tree)

    # Post-processing
    inject_playwright_import(tree)
    fix_driver_none(tree, transformer.driver_var)
    strip_time_imports(tree)
    _strip_residual_selenium(tree, transformer.driver_var)
    _rewrite_driver_params(tree, transformer.driver_var)
    _add_first_to_action_locators(tree)
    _fix_empty_bodies(tree)

    # Convert to async: wrap Playwright calls in await, then make containing functions async
    tree = WrapAwaitPass().visit(tree)
    make_parse_data_async(tree)
    _wrap_async_func_calls(tree)
    # Re-run: _wrap_async_func_calls may have introduced new await nodes in sync functions
    make_parse_data_async(tree)
    _fix_empty_bodies(tree)

    ast.fix_missing_locations(tree)
    code = ast.unparse(tree)
    code = _fix_option_clicks(code)
    return code



def _fix_option_clicks(code: str) -> str:
    """Rewrite option-click patterns to select_option.

    Playwright can't .click() on <option> elements — they're invisible.
    This rewrites patterns like:
        page.locator("xpath=//select[@id='X']//option[contains(., 'text')]").click()
    to:
        page.locator("#X").select_option(label="text")

    Handles both constant selectors and f-string selectors with variables.
    """
    # Pattern 1: f-string XPath with variable — select[@id='X']//option[contains(., 'var')]
    # Rewrite to: find option value via XPath, then select_option(value=...) on parent.
    # Uses contains() for partial matching (the original Selenium behavior).
    # The (?:\.first)? handles cases where _add_first_to_action_locators already ran.
    code = re.sub(
        r'''([ ]*)await page\.locator\(f"""xpath=\{"//select\[@id='([^']+)'\]//option\[contains\(\., '" \+ (\w+) \+ "'\)\]"\}"""\)(?:\.first)?\.click\(\)''',
        lambda m: (
            f'{m.group(1)}_opt_val = await page.locator(f"""xpath={{"//select[@id=\'{m.group(2)}\']//option[contains(., \'" + {m.group(3)} + "\')]"}}""" ).first.get_attribute("value")\n'
            f'{m.group(1)}await page.locator("#{m.group(2)}").select_option(value=_opt_val)'
        ),
        code,
    )
    # Pattern 2: Static XPath — select[@id='X']//option[contains(., 'literal')]
    code = re.sub(
        r"""([ ]*)await page\.locator\((['"])xpath=//select\[@id='([^']+)'\]//option\[contains\(\., '([^']+)'\)\]\2\)(?:\.first)?\.click\(\)""",
        lambda m: (
            f'{m.group(1)}_opt_val = await page.locator({m.group(2)}xpath=//select[@id=\'{m.group(3)}\']//option[contains(., \'{m.group(4)}\')]{m.group(2)}).first.get_attribute("value")\n'
            f'{m.group(1)}await page.locator({m.group(2)}#{m.group(3)}{m.group(2)}).select_option(value=_opt_val)'
        ),
        code,
    )
    return code


def _strip_residual_selenium(tree: ast.Module, driver_var: str = "driver") -> None:
    """Clean up residual Selenium references after the main transform.

    Handles two patterns:
    1. Calls whose ONLY purpose is waiting (all args are EC.*/By.* expressions,
       and the function name suggests waiting) → strip entirely.
    2. Calls that pass (By.X, selector) as positional args for locating elements
       (e.g. click_element(By.XPATH, sel)) → rewrite to page.locator(sel).func().
    """
    class _Cleaner(ast.NodeTransformer):
        def _has_ec_ref(self, node: ast.AST) -> bool:
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                    if child.value.id == "EC":
                        return True
            return False

        def _is_wait_call(self, node: ast.Call) -> bool:
            """Check if this call is a pure wait wrapper (has EC.* args, name suggests wait)."""
            if not self._has_ec_ref(node):
                return False
            # Check function name
            func = node.func
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            else:
                return False
            return "wait" in name.lower()

        def _try_rewrite_by_call(self, node: ast.Call) -> ast.expr | None:
            """Try to rewrite func(By.X, selector, ...) → page.locator(pw_sel).func(...)."""
            if len(node.args) < 2:
                return None
            by_node = node.args[0]
            sel_node = node.args[1]
            if not (isinstance(by_node, ast.Attribute) and _is_name(by_node.value, "By")):
                return None
            # Get function name
            func = node.func
            if isinstance(func, ast.Attribute):
                method_name = func.attr
            elif isinstance(func, ast.Name):
                method_name = func.id
            else:
                return None
            # Convert to Playwright: page.locator(selector).action()
            pw_sel = by_to_selector(by_node.attr, sel_node)
            locator = _make_page_locator(pw_sel)
            # Guess action from function name
            if "click" in method_name.lower():
                return _make_method_call(locator, "click")
            elif "fill" in method_name.lower() or "type" in method_name.lower() or "input" in method_name.lower():
                extra_args = node.args[2:] if len(node.args) > 2 else []
                return _make_method_call(locator, "fill", extra_args)
            # Default: just create the locator (caller will get a locator object)
            return locator

        def visit_Expr(self, node: ast.Expr):
            self.generic_visit(node)
            if not hasattr(node, "value") or node.value is None:
                return None
            if isinstance(node.value, ast.Call):
                # Strip pure wait calls
                if self._is_wait_call(node.value):
                    return None
                # Rewrite By.* calls to Playwright locator calls
                rewritten = self._try_rewrite_by_call(node.value)
                if rewritten is not None:
                    node.value = rewritten
                    return node
            return node

        def visit_Assign(self, node: ast.Assign):
            self.generic_visit(node)
            if isinstance(node.value, ast.Call):
                if self._is_wait_call(node.value):
                    return None
                rewritten = self._try_rewrite_by_call(node.value)
                if rewritten is not None:
                    node.value = rewritten
                    return node
            return node

        def _is_class_method(self_, node) -> bool:
            """Check if function is a class method (has 'self' or 'cls' as first arg)."""
            if node.args.args and node.args.args[0].arg in ('self', 'cls'):
                return True
            return False

        def visit_FunctionDef(self_, node):
            # Strip non-class-method helpers that still reference Selenium constructs.
            # Class methods (parse_data etc.) are kept even if they contain EC refs
            # in nested functions — the nested functions themselves get stripped.
            if not self_._is_class_method(node) and self_._has_ec_ref(node):
                return None
            self_.generic_visit(node)
            return node

        def visit_AsyncFunctionDef(self_, node):
            if not self_._is_class_method(node) and self_._has_ec_ref(node):
                return None
            self_.generic_visit(node)
            return node

    _Cleaner().visit(tree)


def _rewrite_driver_params(tree: ast.Module, driver_var: str = "driver") -> None:
    """Rewrite function parameters and call sites that pass the old driver variable.

    Handles:
    - Functions with a `driver` parameter: rename to unused, or remove
    - Call sites that pass `driver` as an argument: pass `page` instead
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Check if any parameter is named after the driver var (e.g. "driver")
        for i, arg in enumerate(node.args.args):
            if arg.arg == driver_var:
                # Rename to page — the function body already uses page.* after transpilation
                arg.arg = PW_PAGE
                # Clear any type annotation (e.g. : WebDriver)
                arg.annotation = None

    # Fix call sites: func(driver) → func(page)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for i, arg in enumerate(node.args):
                if isinstance(arg, ast.Name) and arg.id == driver_var:
                    arg.id = PW_PAGE
            for kw in node.keywords:
                if isinstance(kw.value, ast.Name) and kw.value.id == driver_var:
                    kw.value.id = PW_PAGE


# Methods that trigger Playwright's strict-mode check (must resolve to exactly 1 element).
_STRICT_ACTIONS = frozenset({
    "click", "dblclick", "fill", "press", "type", "check", "uncheck",
    "select_option", "set_input_files", "hover", "focus", "scroll_into_view_if_needed",
    "get_attribute", "text_content", "inner_text", "inner_html", "input_value",
    "is_visible", "is_enabled", "is_checked", "evaluate",
})
# Suffixes on a locator chain that already narrow to one element.
_NARROWING_ATTRS = frozenset({"first", "last"})
_NARROWING_METHODS = frozenset({"nth", "all"})


def _add_first_to_action_locators(tree: ast.Module) -> None:
    """Insert ``.first`` between ``page.locator(sel)`` and strict-mode actions.

    Selenium's ``find_element`` returns the first match; Playwright's locator
    raises if the selector resolves to multiple elements when an action is
    performed.  The main transform adds ``.first`` for ``find_element`` calls,
    but some upstream patterns (WebDriverWait result assignments, manual XPath
    construction) slip through.  This pass catches them generically.

    Handles both inline chains and variable-based patterns:
      - ``page.locator(sel).click()``      → ``page.locator(sel).first.click()``
      - ``var = page.locator(sel); var.click()``  → ``var = page.locator(sel).first; ...``
    """

    def _is_page_locator(node: ast.AST) -> bool:
        """True if *node* is ``page.locator(...)``."""
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "locator"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == PW_PAGE
        )

    def _already_narrowed(node: ast.AST) -> bool:
        """True if the expression already ends with .first/.last/.nth()/etc."""
        if isinstance(node, ast.Attribute) and node.attr in _NARROWING_ATTRS:
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _NARROWING_METHODS
        ):
            return True
        return False

    def _wrap_first(node: ast.AST) -> ast.Attribute:
        return ast.Attribute(value=node, attr="first", ctx=ast.Load())

    # Pass 1: inline chains  —  page.locator(sel).ACTION()
    # The AST shape is Call(func=Attribute(value=LOCATOR, attr=ACTION))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in _STRICT_ACTIONS:
            continue
        target = func.value  # the object the action is called on
        if _is_page_locator(target) and not _already_narrowed(target):
            func.value = _wrap_first(target)

    # Pass 2: variable assignments  —  var = page.locator(sel)  (add .first to RHS)
    # Only if var is later used with a strict action.
    # Collect variable names assigned from page.locator()
    locator_vars: dict[str, ast.Assign] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and _is_page_locator(node.value) and not _already_narrowed(node.value):
                locator_vars[tgt.id] = node
    # Check if any of those vars are used with strict actions
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _STRICT_ACTIONS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in locator_vars
        ):
            assign = locator_vars.pop(node.func.value.id)
            assign.value = _wrap_first(assign.value)


def _fix_empty_bodies(tree: ast.Module) -> None:
    """Insert `pass` into any empty body/orelse/finalbody to keep valid syntax."""
    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            stmts = getattr(node, attr, None)
            if isinstance(stmts, list) and len(stmts) == 0:
                # Only add pass if this attribute is required to be non-empty
                # body is always required; orelse/finalbody can be empty
                if attr == "body":
                    stmts.append(ast.Pass())


def transpile_file(input_path: Path, output_path: Path | None = None, dry_run: bool = False) -> str:
    source = input_path.read_text()
    result = transpile(source)
    if dry_run:
        return result
    out = output_path or input_path
    out.write_text(result + "\n")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Transpile Selenium scripts to Playwright (sync API)")
    parser.add_argument("path", help="Input file or directory")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing files")
    parser.add_argument("--report", action="store_true", help="Report Selenium patterns without transforming")
    parser.add_argument("--output-dir", "-o", help="Output directory (default: overwrite in place)")
    args = parser.parse_args()

    target = Path(args.path)

    if args.report:
        files = sorted(target.glob("*.py")) if target.is_dir() else [target]
        for f in files:
            r = report_file(f)
            print(f"\n{'=' * 60}")
            print(f"  {r['file']}")
            print(f"{'=' * 60}")
            print(f"  Imports:  {', '.join(r['imports']) or 'none'}")
            print(f"  By.*:     {r['by']}")
            print(f"  EC.*:     {r['ec']}")
            print(f"  Methods:  {r['driver_methods']}")
            print(f"  Select:   {r['select']}")
            print(f"  Keys:     {r['keys']}")
            print(f"  Sleeps:   {r['sleeps']}")
        return

    files = sorted(target.glob("*.py")) if target.is_dir() else [target]
    out_dir = Path(args.output_dir) if args.output_dir else None

    success = 0
    errors = []
    for f in files:
        try:
            out_path = (out_dir / f.name) if out_dir else None
            result = transpile_file(f, out_path, dry_run=args.dry_run)
            if args.dry_run:
                print(f"\n{'=' * 60}")
                print(f"  {f.name}")
                print(f"{'=' * 60}")
                print(result)
            else:
                print(f"  OK  {f.name}")
            success += 1
        except Exception as e:
            errors.append((f.name, str(e)))
            print(f"  ERR {f.name}: {e}")

    print(f"\n{success}/{len(files)} files transpiled, {len(errors)} errors")
    if errors:
        for name, err in errors:
            print(f"  - {name}: {err}")


if __name__ == "__main__":
    main()
