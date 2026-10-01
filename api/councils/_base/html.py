"""HTML parsing with one parser choice for every council."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag


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
