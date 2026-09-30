"""Tag widgets with translation keys and re-apply strings without rebuilding."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Mapping, Sequence
from typing import Any

_ATTR = "_manmabot_i18n"
_NOTEBOOK_ATTR = "_manmabot_i18n_tabs"
_HEADING_ATTR = "_manmabot_i18n_headings"


def tag(widget: tk.Misc, key: str, option: str = "text") -> tk.Misc:
    """Remember that ``widget[option]`` should track translation ``key``."""
    setattr(widget, _ATTR, (option, key))
    return widget


def tag_notebook(notebook: tk.Misc, keys: Sequence[str]) -> tk.Misc:
    """Remember notebook tab texts in tab order (same order as ``add`` calls)."""
    setattr(notebook, _NOTEBOOK_ATTR, tuple(keys))
    return notebook


def tag_tree_heading(tree: tk.Misc, column: str, key: str) -> None:
    """Remember a Treeview heading text key for ``column`` (e.g. ``#0``)."""
    headings = getattr(tree, _HEADING_ATTR, None)
    if not isinstance(headings, dict):
        headings = {}
        setattr(tree, _HEADING_ATTR, headings)
    headings[str(column)] = key


def clear_tree_heading_tag(tree: tk.Misc, column: str) -> None:
    headings = getattr(tree, _HEADING_ATTR, None)
    if isinstance(headings, dict):
        headings.pop(str(column), None)


def apply(root: tk.Misc, translations: Mapping[str, str]) -> int:
    """Walk ``root`` and update every tagged widget. Returns update count."""
    updated = 0
    stack: list[tk.Misc] = [root]
    while stack:
        widget = stack.pop()
        try:
            children = list(widget.winfo_children())
        except tk.TclError:
            continue
        stack.extend(reversed(children))

        marked = getattr(widget, _ATTR, None)
        if isinstance(marked, tuple) and len(marked) == 2:
            option, key = marked
            text = translations.get(str(key))
            if text is not None:
                try:
                    widget.configure(**{str(option): text})
                    updated += 1
                except tk.TclError:
                    pass

        tab_keys = getattr(widget, _NOTEBOOK_ATTR, None)
        if isinstance(tab_keys, (tuple, list)):
            try:
                tabs = list(widget.tabs())  # type: ignore[attr-defined]
            except (tk.TclError, AttributeError):
                tabs = []
            for index, key in enumerate(tab_keys):
                if index >= len(tabs):
                    break
                text = translations.get(str(key))
                if text is None:
                    continue
                try:
                    widget.tab(tabs[index], text=text)  # type: ignore[attr-defined]
                    updated += 1
                except tk.TclError:
                    pass

        headings = getattr(widget, _HEADING_ATTR, None)
        if isinstance(headings, dict):
            for column, key in headings.items():
                text = translations.get(str(key))
                if text is None:
                    continue
                try:
                    widget.heading(column, text=text)  # type: ignore[attr-defined]
                    updated += 1
                except tk.TclError:
                    pass
    return updated


def tagged_key(widget: Any) -> str | None:
    marked = getattr(widget, _ATTR, None)
    if isinstance(marked, tuple) and len(marked) == 2:
        return str(marked[1])
    return None
