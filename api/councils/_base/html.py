"""HTML parsing with one parser choice for every council."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup, Tag

from api.councils._base.errors import UpstreamError


def soup(markup: str | bytes) -> BeautifulSoup:
    """Parse with the stdlib parser, which the scrapers' selectors were written against."""
    return BeautifulSoup(markup, "html.parser")


def text_of(node: object) -> str:
    """Stripped text of a bs4 node, or "" when the node is missing.

    Text from child tags is joined with a space, so "(<b>if subscribed</b>)"
    reads "( if subscribed )". When inline markup sits inside the text you
    want, use `" ".join(node.get_text().split())` instead.
    """
    return node.get_text(" ", strip=True) if isinstance(node, Tag) else ""


def find_tag(node: Tag, *args: Any, what: str | None = None, **kwargs: Any) -> Tag:
    """`node.find(...)` as a Tag, or `UpstreamError` when the page has no such element.

    bs4 types `find` as `Tag | NavigableString | None`; this is the guard every
    scraper otherwise writes by hand. `what` is the error message (default names
    the tag searched for). Where a missing element is fine, use `find` and check.
    Not for `string=`-only searches: those match a text node, never a Tag.
    """
    found = node.find(*args, **kwargs)
    if not isinstance(found, Tag):
        raise UpstreamError(what or _missing(args, kwargs))
    return found


def select_tag(node: Tag, selector: str, *, what: str | None = None) -> Tag:
    """`node.select_one(selector)` as a Tag, or `UpstreamError` when nothing matches."""
    found = node.select_one(selector)
    if not isinstance(found, Tag):
        raise UpstreamError(what or f"page has no element matching {selector!r}")
    return found


def _missing(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    name = args[0] if args and isinstance(args[0], str) else kwargs.get("name")
    attrs = args[1] if len(args) > 1 else kwargs.get("attrs")
    extra = {k: v for k, v in kwargs.items() if k not in ("name", "attrs")}
    if isinstance(attrs, dict):
        extra = {**attrs, **extra}
    detail = ", ".join(f"{k}={v!r}" for k, v in extra.items())
    return f"page has no <{name or 'any'}> element" + (f" ({detail})" if detail else "")
