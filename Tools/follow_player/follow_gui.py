"""Small window: pick a nearby player, follow them, hunt when close.

Home starts, pauses, or resumes. Spinbox edits are copied into the live
session immediately, including while paused, so the window stays open.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Optional

from follow_player.follow_session import FollowParams, FollowSession

_BG = "#f4f1ea"
_INK = "#1f2328"
_MUTED = "#5c6570"
_ACCENT = "#2f6f4e"


class FollowWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("따라 사냥")
        self.root.configure(bg=_BG)
        self.root.geometry("460x640")
        self.root.minsize(420, 560)
        self._rows: list[dict[str, Any]] = []
        self._alive = True
        self._home_at = 0.0
        self._hotkey_handles: list[Any] = []
        self.session = FollowSession(
            on_status=self._post_status,
            on_players=self._post_players,
            on_log=self._post_log,
            on_running=self._post_running,
        )
        self.follow_var = tk.IntVar(value=9)
        self.approach_var = tk.IntVar(value=2)
        self.attack_var = tk.IntVar(value=7)
        self.poll_var = tk.DoubleVar(value=0.5)
        self.target_var = tk.StringVar(value="선택한 플레이어 없음")
        self.state_var = tk.StringVar(value="대기")
        self.status_var = tk.StringVar(value="갱신으로 주변 플레이어를 읽으세요")
        self._build()
        for var in (self.follow_var, self.approach_var, self.attack_var, self.poll_var):
            var.trace_add("write", self._sync_params)
        self._bind_home()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=_BG)
        style.configure("TLabel", background=_BG, foreground=_INK, font=("Malgun Gothic", 10))
        style.configure("Title.TLabel", background=_BG, foreground=_INK, font=("Malgun Gothic", 16, "bold"))
        style.configure("Muted.TLabel", background=_BG, foreground=_MUTED, font=("Malgun Gothic", 9))
        style.configure("TButton", font=("Malgun Gothic", 10))
        style.configure("Run.TLabel", background=_BG, foreground=_ACCENT, font=("Malgun Gothic", 11, "bold"))

        pad = ttk.Frame(self.root, padding=14)
        pad.pack(fill=tk.BOTH, expand=True)

        ttk.Label(pad, text="따라 사냥", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            pad,
            text="보면 쏘고 줍습니다. 나를 치거나 따라가는 플레이어를 치는 몬스터를 먼저 칩니다.",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(2, 10))

        list_row = ttk.Frame(pad)
        list_row.pack(fill=tk.BOTH, expand=True)
        self.list = tk.Listbox(
            list_row,
            height=10,
            activestyle="dotbox",
            exportselection=False,
            font=("Malgun Gothic", 10),
            bg="#fffdf8",
            fg=_INK,
            selectbackground="#d7ebdd",
            selectforeground=_INK,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#d0cbc2",
        )
        scroll = ttk.Scrollbar(list_row, orient=tk.VERTICAL, command=self.list.yview)
        self.list.configure(yscrollcommand=scroll.set)
        self.list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.list.bind("<<ListboxSelect>>", self._on_select)

        buttons = ttk.Frame(pad)
        buttons.pack(fill=tk.X, pady=(8, 4))
        ttk.Button(buttons, text="갱신", command=self._on_refresh).pack(side=tk.LEFT)
        ttk.Button(buttons, text="중지", command=self._on_stop).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(buttons, textvariable=self.state_var, style="Run.TLabel").pack(side=tk.RIGHT)

        ttk.Label(pad, textvariable=self.target_var).pack(anchor=tk.W, pady=(4, 8))

        form = ttk.Frame(pad)
        form.pack(fill=tk.X)
        self._spin(form, 0, "따라가기", self.follow_var, 1, 40, "타일 이상 멀어지면 이동")
        self._spin(form, 1, "접근 반경", self.approach_var, 1, 8, "타일 안의 빈 칸으로")
        self._spin(form, 2, "공격 허용", self.attack_var, 1, 40, "이 안의 몬스터 공격, 목표 근처 아이템은 이동 줍기")
        self._spin(
            form,
            3,
            "확인 간격",
            self.poll_var,
            0.2,
            5.0,
            "초마다 거리 확인",
            increment=0.1,
            fmt="%.1f",
        )

        ttk.Label(
            pad,
            text="Home  시작 / 정지 / 재개  (게임 창이 앞에 있어도 동작)",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(10, 4))
        ttk.Label(pad, textvariable=self.status_var, wraplength=420).pack(anchor=tk.W)

        self.log = tk.Text(
            pad,
            height=7,
            font=("Malgun Gothic", 9),
            bg="#fffdf8",
            fg=_MUTED,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#d0cbc2",
            wrap=tk.WORD,
        )
        self.log.pack(fill=tk.BOTH, expand=False, pady=(8, 0))
        self.log.configure(state=tk.DISABLED)

    def _spin(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        var: tk.Variable,
        lo: float,
        hi: float,
        hint: str,
        *,
        increment: float = 1,
        fmt: str = "%.0f",
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=3)
        box = tk.Spinbox(
            parent,
            from_=lo,
            to=hi,
            increment=increment,
            textvariable=var,
            width=6,
            format=fmt,
            font=("Malgun Gothic", 10),
            justify=tk.RIGHT,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#d0cbc2",
            buttonbackground=_BG,
        )
        box.grid(row=row, column=1, sticky=tk.W, padx=(8, 8))
        ttk.Label(parent, text=hint, style="Muted.TLabel").grid(row=row, column=2, sticky=tk.W)

    def _sync_params(self, *_args: object) -> None:
        if not self._alive:
            return
        params = FollowParams(
            follow_tiles=self._int_or(self.follow_var, 9),
            approach_tiles=self._int_or(self.approach_var, 2),
            attack_tiles=self._int_or(self.attack_var, 7),
            poll_s=self._float_or(self.poll_var, 0.5),
            target_ent=self._selected_ent(),
            target_name=self._selected_name(),
            target_track_id=self._selected_track(),
        )
        self.session.set_params(params)

    def _int_or(self, var: tk.Variable, default: int) -> int:
        try:
            return int(var.get())
        except (tk.TclError, ValueError, TypeError):
            return default

    def _float_or(self, var: tk.Variable, default: float) -> float:
        try:
            return float(var.get())
        except (tk.TclError, ValueError, TypeError):
            return default

    def _selected_index(self) -> Optional[int]:
        sel = self.list.curselection()
        if not sel:
            return None
        index = int(sel[0])
        if index < 0 or index >= len(self._rows):
            return None
        return index

    def _selected_ent(self) -> str:
        index = self._selected_index()
        if index is None:
            return self.session.snapshot_params().target_ent
        return str(self._rows[index].get("ent") or "")

    def _selected_name(self) -> str:
        index = self._selected_index()
        if index is None:
            return self.session.snapshot_params().target_name
        return str(self._rows[index].get("name") or "")

    def _selected_track(self) -> Optional[int]:
        index = self._selected_index()
        if index is None:
            return self.session.snapshot_params().target_track_id
        try:
            return int(self._rows[index].get("track_id"))
        except (TypeError, ValueError):
            return None

    def _on_select(self, _event: object = None) -> None:
        index = self._selected_index()
        if index is None:
            return
        row = self._rows[index]
        dist = row.get("dist")
        dist_s = "?" if dist is None else f"{int(dist)}타일"
        self.target_var.set(f"대상  {row.get('name')}   {dist_s}")
        self._sync_params()

    def _on_refresh(self) -> None:
        self._sync_params()
        self.status_var.set("주변 플레이어 읽는 중…")
        self.session.request_refresh()

    def _on_stop(self) -> None:
        self.session.stop()
        self.state_var.set("중지")
        self.status_var.set("중지")

    def _bind_home(self) -> None:
        """Global Home, so the game can stay focused."""
        try:
            import keyboard
        except Exception as exc:
            self._append_log(f"전역 Home 사용 불가: {exc}")
            self.root.bind_all("<Home>", self._on_home)
            return
        try:
            handle = keyboard.add_hotkey("home", self._home_from_hook, suppress=False)
            self._hotkey_handles.append(handle)
            self._append_log("Home은 게임 창이 앞에 있어도 정지/재개합니다")
        except Exception as exc:
            self._append_log(f"전역 Home 등록 실패: {exc}")
            self.root.bind_all("<Home>", self._on_home)

    def _home_from_hook(self) -> None:
        if not self._alive:
            return
        self.root.after(0, self._on_home)

    def _unbind_home(self) -> None:
        if not self._hotkey_handles:
            return
        try:
            import keyboard
        except Exception:
            self._hotkey_handles.clear()
            return
        for handle in self._hotkey_handles:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:
                pass
        self._hotkey_handles.clear()

    def _on_home(self, _event: object = None) -> str:
        now = time.perf_counter()
        if now - self._home_at < 0.4:
            return "break"
        self._home_at = now
        self._sync_params()
        self.session.toggle()
        return "break"

    def _post_status(self, text: str) -> None:
        self.root.after(0, lambda text=text: self._set_status(text))

    def _set_status(self, text: str) -> None:
        if self._alive:
            self.status_var.set(text)

    def _post_log(self, text: str) -> None:
        self.root.after(0, lambda text=text: self._append_log(text))

    def _append_log(self, text: str) -> None:
        if not self._alive:
            return
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text.rstrip() + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _post_players(self, rows: list[dict[str, Any]]) -> None:
        self.root.after(0, lambda rows=list(rows): self._fill_players(rows))

    def _fill_players(self, rows: list[dict[str, Any]]) -> None:
        if not self._alive:
            return
        keep = self.session.snapshot_params().target_ent
        self._rows = rows
        self.list.delete(0, tk.END)
        select_at = None
        for index, row in enumerate(rows):
            dist = row.get("dist")
            dist_s = "?" if dist is None else f"{int(dist):>3}타일"
            tile = row.get("tile")
            tile_s = "" if not tile else f"  ({int(tile[0])},{int(tile[1])})"
            self.list.insert(tk.END, f"{dist_s}   {row.get('name')}{tile_s}")
            if keep and row.get("ent") == keep:
                select_at = index
        if select_at is not None:
            self.list.selection_set(select_at)
            self.list.activate(select_at)
            self.list.see(select_at)
            self._on_select()
        elif not rows:
            self.target_var.set("주변 플레이어 없음")

    def _post_running(self, running: bool, paused: bool) -> None:
        self.root.after(0, lambda running=running, paused=paused: self._set_running(running, paused))

    def _set_running(self, running: bool, paused: bool) -> None:
        if not self._alive:
            return
        if not running:
            if self.state_var.get() != "중지":
                self.state_var.set("대기")
            return
        self.state_var.set("정지" if paused else "실행")

    def _on_close(self) -> None:
        self._alive = False
        self._unbind_home()
        try:
            self.session.close()
        except Exception:
            pass
        self.root.destroy()


def run_follow_player() -> int:
    root = tk.Tk()
    FollowWindow(root)
    root.mainloop()
    return 0
