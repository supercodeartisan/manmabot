"""Tk GUI to walk to a supply tile and run the drop loop."""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from common.bootstrap import bootstrap

bootstrap()

from ui.design_system import TEXT_MUTED, apply_classic_style

from supply.inventory import ordered_items, read_bag
from supply.runner import SupplyRequest, run_supply
from supply.session import SupplyItem, SupplySession
from supply import windows as ui


def _is_elevated() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_elevated() -> bool:
    """UAC relaunch via elevate_supply_practice (bundled pythonw preferred)."""
    if os.name != "nt":
        return False
    try:
        from supply.elevate_supply_practice import main as elevate_main

        return elevate_main() == 0
    except Exception:
        try:
            import ctypes

            repo = Path(__file__).resolve().parents[2]
            script = Path(__file__).resolve().parent / "run_supply_practice.py"
            for name in ("pythonw.exe", "python.exe"):
                cand = repo / "python" / name
                if cand.is_file():
                    py = cand
                    break
            else:
                py = Path(sys.executable).resolve()
            rc = int(
                ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "runas",
                    str(py),
                    f'"{script}"',
                    str(repo),
                    1,
                )
                or 0
            )
            return rc > 32
        except Exception:
            return False


def require_admin_or_exit() -> None:
    """UAC once at start so enter_chat_cli_admin.exe inherits elevation (no extra prompts)."""
    if _is_elevated():
        return
    if not _relaunch_elevated():
        try:
            import tkinter.messagebox as mb

            mb.showerror(
                "Supply Practice",
                "관리자 권한이 필요합니다.\n"
                "UAC에서 허용한 뒤 다시 실행하세요.\n"
                "(enter_chat_cli_admin / Interception)",
            )
        except Exception:
            pass
        raise SystemExit(1)
    raise SystemExit(0)


class SupplyPracticeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Supply Practice (Administrator)")
        self.geometry("980x720")
        self.minsize(820, 560)
        apply_classic_style(self)

        self._busy = False
        self._cancel = False
        self._elevated = True
        self._session = SupplySession()

        self.world_x = tk.StringVar(self, value="0")
        self.world_y = tk.StringVar(self, value="0")
        self.item_id = tk.StringVar(self, value="")
        self.item_name = tk.StringVar(self, value="")
        self.item_qty = tk.StringVar(self, value="1")
        self.walk_first = tk.BooleanVar(self, value=True)
        self.status_var = tk.StringVar(self, value="Ready")

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="보급 타일 (게임/nav 좌표)", style="Chrome.TLabel").pack(side="left")
        ttk.Entry(top, textvariable=self.world_x, width=8).pack(side="left", padx=4)
        ttk.Entry(top, textvariable=self.world_y, width=8).pack(side="left", padx=4)
        ttk.Checkbutton(top, text="먼저 이동", variable=self.walk_first).pack(side="left", padx=8)

        mid = ttk.Frame(self, padding=8)
        mid.pack(fill="x")
        ttk.Label(mid, text="아이템 id", style="Chrome.TLabel").pack(side="left")
        ttk.Entry(mid, textvariable=self.item_id, width=8).pack(side="left", padx=4)
        ttk.Label(mid, text="이름", style="Chrome.TLabel").pack(side="left")
        ttk.Entry(mid, textvariable=self.item_name, width=18).pack(side="left", padx=4)
        ttk.Label(mid, text="수량", style="Chrome.TLabel").pack(side="left")
        ttk.Entry(mid, textvariable=self.item_qty, width=6).pack(side="left", padx=4)
        ttk.Button(mid, text="목록에 추가", command=self._add_item).pack(side="left", padx=6)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=1)
        body.add(right, weight=1)

        ttk.Label(left, text="보급 목록", style="Chrome.TLabel").pack(anchor="w")
        self.req_list = tk.Listbox(left, height=12, exportselection=False)
        self.req_list.pack(fill="both", expand=True, pady=4)
        ttk.Button(left, text="선택 삭제", command=self._remove_item).pack(anchor="w")

        ttk.Label(right, text="로그", style="Chrome.TLabel").pack(anchor="w")
        self.log = tk.Text(right, height=16, wrap="word")
        self.log.pack(fill="both", expand=True, pady=4)

        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="가방 읽기", command=self._read_bag).pack(side="left")
        ttk.Button(bar, text="창 상태", command=self._read_ui).pack(side="left", padx=4)
        ttk.Button(bar, text="보급 실행", command=self._run).pack(side="left", padx=8)
        ttk.Button(bar, text="중지", command=self._stop).pack(side="left")
        ttk.Label(bar, textvariable=self.status_var, foreground=TEXT_MUTED).pack(side="right")

        bottom = ttk.Frame(self, padding=8)
        bottom.pack(fill="both", expand=True)
        ttk.Label(bottom, text="기록 / failed", style="Chrome.TLabel").pack(anchor="w")
        self.result = tk.Text(bottom, height=10, wrap="word")
        self.result.pack(fill="both", expand=True)

        self._items: list[SupplyItem] = []

    def _append_log(self, msg: str) -> None:
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _add_item(self) -> None:
        raw_id = self.item_id.get().strip()
        name = self.item_name.get().strip()
        try:
            qty = int(self.item_qty.get().strip() or "0")
        except ValueError:
            messagebox.showerror("Supply", "수량이 숫자가 아닙니다.", parent=self)
            return
        item_id = int(raw_id) if raw_id.isdigit() else None
        if item_id is None and not name:
            messagebox.showerror("Supply", "아이템 id 또는 이름을 넣으세요.", parent=self)
            return
        if qty <= 0:
            messagebox.showerror("Supply", "수량은 1 이상이어야 합니다.", parent=self)
            return
        item = SupplyItem(item_id=item_id, name=name, qty=qty)
        self._items.append(item)
        label = f"id={item_id} name={name or '-'} qty={qty}"
        self.req_list.insert("end", label)

    def _remove_item(self) -> None:
        sel = self.req_list.curselection()
        if not sel:
            return
        idx = int(sel[0])
        self.req_list.delete(idx)
        del self._items[idx]

    def _read_bag(self) -> None:
        snap = read_bag()
        rows = ordered_items(snap)
        self._append_log(f"bag items={len(rows)}")
        for row in rows[:40]:
            self._append_log(
                f"  slot={row.get('slot')} id={row.get('id')} "
                f"count={row.get('count')} name={row.get('name')}"
            )

    def _read_ui(self) -> None:
        self._append_log(ui.describe())

    def _stop(self) -> None:
        self._cancel = True
        self._set_status("stopping…")
        self._append_log("stop pressed")

    def _run(self) -> None:
        if self._busy:
            return
        try:
            wx = int(self.world_x.get().strip())
            wy = int(self.world_y.get().strip())
        except ValueError:
            messagebox.showerror("Supply", "월드 좌표가 숫자가 아닙니다.", parent=self)
            return
        # The list is the run. The name box is only a single line when the
        # list is empty. A leftover name (괴물눈고기) must not skip the
        # queued stacks: each of those needs its own Shift-drag before the
        # quantity field appears.
        if self._items:
            items = list(self._items)
            raw_id = self.item_id.get().strip()
            name = self.item_name.get().strip()
            if name or raw_id:
                self._append_log(
                    f"이름 칸은 무시하고 보급 목록 {len(items)}줄을 순서대로 드래그합니다."
                )
        else:
            raw_id = self.item_id.get().strip()
            name = self.item_name.get().strip()
            if not name and not raw_id:
                messagebox.showerror("Supply", "보급 목록이 비었습니다.", parent=self)
                return
            try:
                qty = int(self.item_qty.get().strip() or "0")
            except ValueError:
                messagebox.showerror("Supply", "수량이 숫자가 아닙니다.", parent=self)
                return
            item_id = int(raw_id) if raw_id.isdigit() else None
            if qty <= 0:
                messagebox.showerror("Supply", "수량은 1 이상이어야 합니다.", parent=self)
                return
            items = [SupplyItem(item_id=item_id, name=name, qty=qty)]
        for item in items:
            self._append_log(
                f"request id={item.item_id} name={item.name or '-'} qty={item.qty}"
            )
        req = SupplyRequest(
            world_x=wx,
            world_y=wy,
            items=items,
            walk_first=bool(self.walk_first.get()),
        )
        self._busy = True
        self._cancel = False
        self._set_status("running…")
        self.result.delete("1.0", "end")

        def work() -> None:
            try:
                sess = run_supply(
                    req,
                    session=self._session,
                    log=lambda m: self.after(0, self._append_log, m),
                    cancel=lambda: self._cancel,
                )
                text = (
                    f"failed={sess.summary()['failed']}\n"
                    f"records={sess.summary()['records']}\n"
                )
                self.after(0, self.result.insert, "end", text)
                self.after(0, self._set_status, "done")
            except Exception as exc:
                self.after(0, self._append_log, f"ERROR {exc}")
                self.after(0, self._set_status, "error")
            finally:
                self._busy = False

        threading.Thread(target=work, name="supply-run", daemon=True).start()

    def _on_close(self) -> None:
        self._cancel = True
        self.destroy()


def run_supply_practice() -> int:
    require_admin_or_exit()
    app = SupplyPracticeApp()
    app.mainloop()
    return 0
