"""Click inventory slots and scrollbar arrows on a game screenshot.

Coordinates are pixels of the opened image. A full client capture matches
client pixels. Order is row-major, 8 rows by 4 columns, then the scroll-up
arrow and the scroll-down arrow.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROWS = 8
COLS = 4
SLOT_COUNT = ROWS * COLS

def default_save_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "Engine" / "data" / "supply" / "inventory_grid.json"


def point_name(index: int) -> str:
    if index < SLOT_COUNT:
        row = index // COLS + 1
        col = index % COLS + 1
        return f"{row}행 {col}열"
    if index == SLOT_COUNT:
        return "스크롤 위"
    return "스크롤 아래"


def slot_of(index: int) -> Optional[tuple[int, int]]:
    if index < 0 or index >= SLOT_COUNT:
        return None
    return index // COLS + 1, index % COLS + 1


class GridCalibrator(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("보급 인벤 칸 좌표")
        self.geometry("1280x840")
        self.minsize(900, 640)

        self._image = None
        self._photo = None
        self._image_id: Optional[int] = None
        self._image_path: Optional[Path] = None
        self._points: list[Optional[tuple[int, int]]] = [None] * (SLOT_COUNT + 2)
        self._current = 0
        self._scale = 1.0
        self._origin = (0.0, 0.0)
        self._pan_last: Optional[tuple[int, int]] = None
        self._save_path = default_save_path()
        self._busy = False

        self.status_var = tk.StringVar(value="스크린샷을 여세요.")
        self.path_var = tk.StringVar(value=str(self._save_path))
        self._build()
        self._select(0)

    def _build(self) -> None:
        bar = ttk.Frame(self, padding=6)
        bar.pack(fill="x")
        ttk.Button(bar, text="그림 열기", command=self.open_image).pack(side="left")
        ttk.Button(bar, text="저장", command=self.save).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="불러오기", command=self.load).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="선택 지우기", command=self.clear_current).pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="전부 지우기", command=self.clear_all).pack(side="left", padx=(6, 0))
        ttk.Label(bar, textvariable=self.path_var).pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        side = ttk.Frame(body, padding=(6, 0, 6, 6), width=220)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        ttk.Label(side, text="클릭 순서").pack(anchor="w")
        self.listbox = tk.Listbox(side, exportselection=False, activestyle="none")
        self.listbox.pack(fill="both", expand=True, pady=(4, 0))
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)
        for index in range(SLOT_COUNT + 2):
            self.listbox.insert("end", self._row_text(index))

        canvas_wrap = ttk.Frame(body)
        canvas_wrap.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(canvas_wrap, bg="#1b1b1b", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_left_click)
        self.canvas.bind("<Enter>", lambda _e: self.canvas.focus_set())
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonRelease-3>", self._on_pan_end)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())

        hint = ttk.Label(
            self,
            padding=(8, 4),
            text="왼쪽 클릭으로 현재 점을 찍습니다. 오른쪽 드래그로 그림을 옮기고, 휠로 확대합니다.",
        )
        hint.pack(fill="x")
        ttk.Label(self, textvariable=self.status_var, padding=(8, 0, 8, 8)).pack(fill="x")
        self.bind("<BackSpace>", lambda _e: self.clear_current())

    def _row_text(self, index: int) -> str:
        point = self._points[index]
        name = point_name(index)
        if point is None:
            return f"{name}    —"
        return f"{name}    {point[0]}, {point[1]}"

    def _refresh_list_row(self, index: int) -> None:
        self._busy = True
        try:
            self.listbox.delete(index)
            self.listbox.insert(index, self._row_text(index))
            if self._current == index:
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(index)
                self.listbox.see(index)
        finally:
            self._busy = False

    def _select(self, index: int) -> None:
        self._current = max(0, min(SLOT_COUNT + 1, index))
        self._busy = True
        try:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(self._current)
            self.listbox.see(self._current)
        finally:
            self._busy = False
        self.status_var.set(f"다음: {point_name(self._current)}  —  슬롯 중심 또는 화살표 한가운데를 클릭")
        self._redraw()

    def _on_list_select(self, _event: object) -> None:
        if self._busy:
            return
        picked = self.listbox.curselection()
        if not picked or int(picked[0]) == self._current:
            return
        self._select(int(picked[0]))

    def open_image(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="게임 화면 스크린샷",
            filetypes=[
                ("이미지", "*.png *.jpg *.jpeg *.bmp *.webp"),
                ("모든 파일", "*.*"),
            ],
        )
        if not path:
            return
        self._load_image(Path(path))

    def _load_image(self, path: Path) -> None:
        try:
            from PIL import Image
        except ImportError:
            messagebox.showerror("보급 인벤 칸 좌표", "Pillow가 없습니다.", parent=self)
            return
        try:
            image = Image.open(path).convert("RGB")
        except OSError as exc:
            messagebox.showerror("보급 인벤 칸 좌표", str(exc), parent=self)
            return
        self._image = image
        self._image_path = path
        self.update_idletasks()
        self.after_idle(self._fit)
        self.status_var.set(f"{path.name}  {image.width}×{image.height}  ·  {point_name(self._current)}")

    def _fit(self) -> None:
        if self._image is None:
            return
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        scale = min(width / self._image.width, height / self._image.height)
        scale = max(0.05, min(scale, 8.0))
        self._scale = scale
        self._origin = (
            (width - self._image.width * scale) / 2,
            (height - self._image.height * scale) / 2,
        )
        self._redraw()

    def _to_canvas(self, x: float, y: float) -> tuple[float, float]:
        ox, oy = self._origin
        return ox + x * self._scale, oy + y * self._scale

    def _to_image(self, x: float, y: float) -> Optional[tuple[int, int]]:
        if self._image is None:
            return None
        ox, oy = self._origin
        ix = (x - ox) / self._scale
        iy = (y - oy) / self._scale
        if ix < 0 or iy < 0 or ix >= self._image.width or iy >= self._image.height:
            return None
        return int(round(ix)), int(round(iy))

    def _redraw(self) -> None:
        self.canvas.delete("all")
        self._image_id = None
        self._photo = None
        if self._image is None:
            self.canvas.create_text(
                24,
                24,
                anchor="nw",
                fill="#d0d0d0",
                text="그림 열기로 아까와 같은 게임 화면 파일을 여세요.",
            )
            return
        from PIL import Image, ImageTk

        width = max(1, int(round(self._image.width * self._scale)))
        height = max(1, int(round(self._image.height * self._scale)))
        resized = self._image.resize((width, height), Image.Resampling.BILINEAR)
        self._photo = ImageTk.PhotoImage(resized)
        ox, oy = self._origin
        self._image_id = self.canvas.create_image(ox, oy, anchor="nw", image=self._photo)
        for index, point in enumerate(self._points):
            if point is None:
                continue
            cx, cy = self._to_canvas(point[0], point[1])
            color = "#ffcc33" if index < SLOT_COUNT else "#5cdb7a"
            if index == SLOT_COUNT + 1:
                color = "#ff7a45"
            width_px = 3 if index == self._current else 2
            self.canvas.create_oval(
                cx - 6, cy - 6, cx + 6, cy + 6, outline=color, width=width_px
            )
            self.canvas.create_text(cx + 8, cy - 10, anchor="sw", fill=color, text=point_name(index))
        current = self._points[self._current]
        if current is not None:
            cx, cy = self._to_canvas(current[0], current[1])
            self.canvas.create_oval(cx - 10, cy - 10, cx + 10, cy + 10, outline="#ffffff", width=1)

    def _on_left_click(self, event: tk.Event) -> None:
        point = self._to_image(event.x, event.y)
        if point is None:
            self.status_var.set("그림 안을 클릭하세요.")
            return
        index = self._current
        self._points[index] = point
        self._refresh_list_row(index)
        nxt = index + 1 if index < SLOT_COUNT + 1 else index
        self._select(nxt)
        self.status_var.set(f"{point_name(index)}  {point[0]}, {point[1]}")

    def _on_pan_start(self, event: tk.Event) -> None:
        self._pan_last = (event.x, event.y)

    def _on_pan_move(self, event: tk.Event) -> None:
        if self._pan_last is None or self._image is None:
            return
        dx = event.x - self._pan_last[0]
        dy = event.y - self._pan_last[1]
        self._pan_last = (event.x, event.y)
        ox, oy = self._origin
        self._origin = (ox + dx, oy + dy)
        self._redraw()

    def _on_pan_end(self, _event: tk.Event) -> None:
        self._pan_last = None

    def _on_wheel(self, event: tk.Event) -> None:
        if self._image is None or event.delta == 0:
            return
        factor = 1.1 if event.delta > 0 else 1 / 1.1
        new_scale = max(0.05, min(8.0, self._scale * factor))
        ix = (event.x - self._origin[0]) / self._scale
        iy = (event.y - self._origin[1]) / self._scale
        self._scale = new_scale
        self._origin = (event.x - ix * new_scale, event.y - iy * new_scale)
        self._redraw()

    def clear_current(self) -> None:
        self._points[self._current] = None
        self._refresh_list_row(self._current)
        self._select(self._current)

    def clear_all(self) -> None:
        self._points = [None] * (SLOT_COUNT + 2)
        for index in range(SLOT_COUNT + 2):
            self._refresh_list_row(index)
        self._select(0)

    def _payload(self) -> dict:
        slots = []
        for index in range(SLOT_COUNT):
            point = self._points[index]
            row, col = slot_of(index)
            slots.append(
                {
                    "row": row,
                    "col": col,
                    "x": None if point is None else point[0],
                    "y": None if point is None else point[1],
                }
            )
        up = self._points[SLOT_COUNT]
        down = self._points[SLOT_COUNT + 1]
        image = self._image
        return {
            "image": None if self._image_path is None else str(self._image_path),
            "image_width": None if image is None else image.width,
            "image_height": None if image is None else image.height,
            "slots": slots,
            "scroll_up_position": None if up is None else [up[0], up[1]],
            "scroll_down_position": None if down is None else [down[0], down[1]],
        }

    def save(self) -> None:
        missing = [point_name(i) for i, point in enumerate(self._points) if point is None]
        if missing:
            go = messagebox.askyesno(
                "보급 인벤 칸 좌표",
                "아직 없는 점: " + ", ".join(missing[:6]) + (" …" if len(missing) > 6 else "") + "\n그대로 저장할까요?",
                parent=self,
            )
            if not go:
                return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="칸 좌표 저장",
            initialfile=self._save_path.name,
            initialdir=str(self._save_path.parent),
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self._payload(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._save_path = target
        self.path_var.set(str(target))
        self.status_var.set(f"저장했습니다. {target}")

    def load(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="칸 좌표 불러오기",
            initialdir=str(self._save_path.parent) if self._save_path.parent.is_dir() else None,
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("보급 인벤 칸 좌표", str(exc), parent=self)
            return
        self._apply_payload(data)
        self._save_path = Path(path)
        self.path_var.set(str(self._save_path))
        image = data.get("image")
        if isinstance(image, str) and Path(image).is_file():
            self._load_image(Path(image))
        else:
            self._redraw()
        self.status_var.set(f"불러왔습니다. {path}")

    def _apply_payload(self, data: dict) -> None:
        slots = data.get("slots")
        if isinstance(slots, list):
            for index, slot in enumerate(slots[:SLOT_COUNT]):
                if not isinstance(slot, dict):
                    continue
                x, y = slot.get("x"), slot.get("y")
                if isinstance(x, int) and isinstance(y, int):
                    self._points[index] = (x, y)
                else:
                    self._points[index] = None
        up = data.get("scroll_up_position")
        down = data.get("scroll_down_position")
        self._points[SLOT_COUNT] = _pair(up)
        self._points[SLOT_COUNT + 1] = _pair(down)
        for index in range(SLOT_COUNT + 2):
            self._refresh_list_row(index)
        self._select(self._first_empty())

    def _first_empty(self) -> int:
        for index, point in enumerate(self._points):
            if point is None:
                return index
        return 0


def _pair(value: object) -> Optional[tuple[int, int]]:
    if (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], int)
        and isinstance(value[1], int)
    ):
        return value[0], value[1]
    return None


def main() -> None:
    GridCalibrator().mainloop()
