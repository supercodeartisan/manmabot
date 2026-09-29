"""Launch this tool from its own folder. Copy the folder anywhere."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _check_deps() -> None:
    missing: list[str] = []
    for mod, pip in (
        ("numpy", "numpy"),
        ("cv2", "opencv-python"),
        ("mss", "mss"),
        ("PIL", "pillow"),
    ):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip)
    if missing:
        req = HERE / "requirements.txt"
        print("Missing packages:", ", ".join(missing))
        print("Install with:")
        print(f'  "{sys.executable}" -m pip install -r "{req}"')
        raise SystemExit(1)


def main() -> int:
    _check_deps()
    from gui import run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
