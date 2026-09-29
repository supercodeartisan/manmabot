"""Shared UI control behavior."""
from __future__ import annotations


def disable_slider_mousewheel(slider) -> None:
    """Keep wheel scrolling from changing a slider under the pointer."""

    def block_wheel(_event):
        return "break"

    def bind_tree(widget) -> None:
        for sequence in (
            "<MouseWheel>",
            "<Control-MouseWheel>",
            "<Button-4>",
            "<Button-5>",
            "<Control-Button-4>",
            "<Control-Button-5>",
        ):
            try:
                widget.bind(sequence, block_wheel)
            except Exception:
                pass
        try:
            children = widget.winfo_children()
        except Exception:
            children = ()
        for child in children:
            bind_tree(child)

    bind_tree(slider)
