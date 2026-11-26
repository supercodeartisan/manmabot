"""Startup gate: MMB2 packs require OOB license artifacts (UI, no cmd)."""

from __future__ import annotations

from pathlib import Path

from session.licensed_runtime import ENVELOPE_PATH, TICKET_PATH, pack_magic
from session.paths import manmabot_root


def mmb2_packs_present(engine: Path | None = None) -> bool:
    root = engine or manmabot_root()
    for name in ("data.pack", "analysis_text.pack"):
        if pack_magic(root / name) == "mmb2":
            return True
    return False


def license_artifacts_present() -> bool:
    return TICKET_PATH.is_file() and ENVELOPE_PATH.is_file()


def license_required() -> bool:
    """True when customer MMB2 packs are present but not yet activated."""
    return mmb2_packs_present() and not license_artifacts_present()


def ensure_license_ui() -> bool:
    """
    If MMB2 needs activation, show the license dialog.
    Returns True when it is OK to continue (licensed or no MMB2).
    Returns False if the user quit without activating.
    """
    if not license_required():
        return True
    try:
        from ui_qt.dialogs.license_activation_dialog import run_license_activation_dialog
    except Exception as exc:
        raise RuntimeError(
            "MMB2 packs require license activation, but the license UI could not load: "
            f"{exc}. Use: python -m session.oob_activation …"
        ) from exc
    return bool(run_license_activation_dialog())
