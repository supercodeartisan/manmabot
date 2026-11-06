# -*- coding: utf-8 -*-
"""
control.ui — 시퀀스 테스트 UI (한국어 / 中文 / English)

입력 '시각'과 마우스/건반 사건을 표로 정의하고 [실행]을 누르면,
그 시각에 맞춰 통신이 발생하며 화면 클릭/이동/끌기/키/핫키/텍스트 입력을 수행한다.

  * 마우스 : 화면좌표, 좌/우/가운데 클릭, 더블클릭, 끌기(드래그), 휠
  * 건반   : 키, 핫키(ctrl+c 등)
  * 텍스트 : 문자열 + 건별 타이핑 속도(cps)
  * 연결   : TCP / 시리얼 / 가상(하드웨어 없이 테스트)
  * 옵션   : 정확 절대좌표(폐루프 피드백), 사용자 간섭 시 자동 정지/재개

실행:  python -m control.ui
"""

import json
import threading
import time
import contextlib
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

from . import keys as K
from .client import ControlClient
from .i18n import I18n, LANGS
from .pointer import no_pointer_accel

STEP_KINDS = ["move", "click", "dclick", "drag", "wheel", "key", "hotkey", "text", "wait"]
BUTTON_MASK = {"b_left": 0x01, "b_right": 0x02, "b_middle": 0x04}

PARAM_SCHEMA = {
    "move": [("x", "int", 0), ("y", "int", 0)],
    "click": [("x", "int", 0), ("y", "int", 0), ("button", "choice", ["b_left", "b_right", "b_middle"]), ("hold", "int", 30)],
    "dclick": [("x", "int", 0), ("y", "int", 0), ("button", "choice", ["b_left", "b_right", "b_middle"])],
    "drag": [("x", "int", 0), ("y", "int", 0), ("x2", "int", 0), ("y2", "int", 0), ("duration", "int", 300)],
    "wheel": [("dy", "int", 0)],
    "key": [("key", "str", "enter")],
    "hotkey": [("hotkey", "str", "ctrl+c")],
    "text": [("text", "str", "hello"), ("cps", "int", 0)],
    "wait": [("duration", "int", 500)],
}
PARAM_LABEL = {"x": "x", "y": "y", "x2": "x2", "y2": "y2", "dy": "dy",
               "key": "key", "hotkey": "hotkey", "text": "text"}


class VirtualLink(object):
    """가상(인프로세스) 연결 — 하드웨어 없이 UI/시퀀스를 시험."""
    def __init__(self, on_action, screen=(1920, 1080)):
        from .transport import MemoryTransport
        from .server import ControlServer
        from .backend import NullBackend
        self.a, self.b = MemoryTransport.pair()
        self.backend = NullBackend(screen=screen, on_action=on_action)
        self.server = ControlServer(self.b, self.backend, poll=0.0005)
        self._stop = False
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()

    @property
    def client_transport(self):
        return self.a

    def _run(self):
        self.server.backend.begin()
        while not self._stop:
            self.server.step()

    def stop(self):
        self._stop = True


class App(object):
    def __init__(self, root):
        self.root = root
        self.T = I18n("ko")
        self.steps = []
        self.iid_step = {}
        self.pv = {}
        self.kind_disp = {}
        self.link = None
        self.client = None
        self.gc = None
        self.mode_var = tk.StringVar(value="virtual")
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.port_var = tk.StringVar(value="9999")
        self.sport_var = tk.StringVar(value="")
        self.screen_w = tk.StringVar(value="1920")
        self.screen_h = tk.StringVar(value="1080")
        self.feedback_var = tk.BooleanVar(value=True)
        self.guard_var = tk.BooleanVar(value=False)
        self.noaccel_var = tk.BooleanVar(value=True)
        self.pause_hold_var = tk.StringVar(value="1.0")
        self.resume_idle_var = tk.StringVar(value="3.0")
        self.lang_var = tk.StringVar(value="ko")
        self.t_var = tk.StringVar(value="0.0")
        self.kind_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value=self.T("st_disconnected"))
        self.prog_var = tk.DoubleVar(value=0.0)
        self.now_var = tk.StringVar(value=self.T("t_now", v=0.0))
        self._stop = threading.Event()
        self._build()
        self._rebuild_params()

    def _build(self):
        self.root.title(self.T("app_title"))
        self._build_conn()
        self._build_editor()
        self._build_run()
        self._build_log()

    def _build_conn(self):
        f = ttk.LabelFrame(self.root, text=self.T("conn_opts"), padding=8)
        f.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(f, text=self.T("mode")).grid(row=0, column=0, sticky="w")
        mode = ttk.Frame(f)
        mode.grid(row=0, column=1, sticky="w", padx=6)
        for code in ("tcp", "serial", "virtual"):
            ttk.Radiobutton(mode, text=self.T("mode_" + code), value=code,
                            variable=self.mode_var, command=self._on_mode).pack(side="left", padx=2)
        ttk.Label(f, text=self.T("hostport")).grid(row=0, column=2, sticky="e", padx=(12, 2))
        ttk.Entry(f, textvariable=self.host_var, width=13).grid(row=0, column=3)
        ttk.Entry(f, textvariable=self.port_var, width=6).grid(row=0, column=4, padx=(2, 0))
        ttk.Label(f, text=self.T("serial_port")).grid(row=0, column=5, sticky="e", padx=(12, 2))
        self.sport_cb = ttk.Combobox(f, textvariable=self.sport_var, width=10, values=[])
        self.sport_cb.grid(row=0, column=6, sticky="w")
        ttk.Button(f, text=self.T("find_port"), command=self._refresh_ports).grid(row=0, column=7, padx=4)
        ttk.Button(f, text=self.T("connect"), command=self._connect).grid(row=0, column=8, padx=6)
        ttk.Button(f, text=self.T("disconnect"), command=self._disconnect).grid(row=0, column=9, padx=2)

        ttk.Label(f, text=self.T("lang")).grid(row=0, column=10, sticky="e", padx=(14, 2))
        self.lang_cb = ttk.Combobox(f, width=8, state="readonly",
                                    values=[name for _, name in LANGS])
        self.lang_cb.set(dict(LANGS).get(self.lang_var.get(), "한국어"))
        self.lang_cb.grid(row=0, column=11, sticky="w")
        self.lang_cb.bind("<<ComboboxSelected>>", self._on_lang_pick)

        ttk.Label(f, text=self.T("screen_wh")).grid(row=1, column=0, sticky="w", pady=(6, 0))
        sw = ttk.Frame(f)
        sw.grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Entry(sw, textvariable=self.screen_w, width=6).pack(side="left")
        ttk.Label(sw, text="x").pack(side="left")
        ttk.Entry(sw, textvariable=self.screen_h, width=6).pack(side="left")
        ttk.Checkbutton(f, text=self.T("chk_feedback"), variable=self.feedback_var).grid(
            row=1, column=2, columnspan=3, sticky="w", padx=(12, 0), pady=(6, 0))
        ttk.Checkbutton(f, text=self.T("chk_guard"), variable=self.guard_var).grid(
            row=1, column=5, columnspan=2, sticky="w", padx=(12, 0), pady=(6, 0))
        ttk.Label(f, text=self.T("pause_s")).grid(row=1, column=7, sticky="e", pady=(6, 0))
        ttk.Entry(f, textvariable=self.pause_hold_var, width=5).grid(row=1, column=8, sticky="w", pady=(6, 0))
        ttk.Label(f, text=self.T("resume_s")).grid(row=1, column=9, sticky="e", pady=(6, 0))
        ttk.Entry(f, textvariable=self.resume_idle_var, width=5).grid(row=1, column=10, sticky="w", pady=(6, 0))
        ttk.Checkbutton(f, text=self.T("chk_noaccel"), variable=self.noaccel_var).grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(f, textvariable=self.status_var, foreground="#06c").grid(
            row=3, column=0, columnspan=12, sticky="w", pady=(6, 0))

    def _on_lang_pick(self, _evt=None):
        name = self.lang_cb.get()
        code = "ko"
        for c, n in LANGS:
            if n == name:
                code = c
        self.lang_var.set(code)
        self._set_lang(code)

    def _build_editor(self):
        f = ttk.LabelFrame(self.root, text=self.T("seq_title"), padding=8)
        f.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        tv = ttk.Treeview(f, columns=("t", "kind", "detail"), show="headings", height=8)
        tv.heading("t", text=self.T("col_time"))
        tv.heading("kind", text=self.T("col_kind"))
        tv.heading("detail", text=self.T("col_detail"))
        tv.column("t", width=70, anchor="center")
        tv.column("kind", width=90, anchor="center")
        tv.column("detail", width=540, anchor="w")
        tv.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(f, orient="vertical", command=tv.yview)
        sb.pack(side="left", fill="y")
        tv.configure(yscrollcommand=sb.set)
        self.tree = tv

        inp = ttk.Frame(self.root)
        inp.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(inp, text=self.T("time_s")).pack(side="left")
        ttk.Entry(inp, textvariable=self.t_var, width=6).pack(side="left", padx=(2, 8))
        ttk.Label(inp, text=self.T("kind")).pack(side="left")
        self.kind_disp = {self.T(k): k for k in STEP_KINDS}
        self.kind_cb = ttk.Combobox(inp, width=12, state="readonly",
                                    values=[self.T(k) for k in STEP_KINDS])
        self.kind_cb.set(self.T("click"))
        self.kind_cb.pack(side="left", padx=(2, 8))
        self.kind_cb.bind("<<ComboboxSelected>>", lambda e: self._rebuild_params())

        self.param_frame = ttk.Frame(self.root)
        self.param_frame.pack(fill="x", padx=8, pady=(4, 0))

        btns = ttk.Frame(self.root)
        btns.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Button(btns, text=self.T("add"), command=self._add_step).pack(side="left")
        ttk.Button(btns, text=self.T("del"), command=self._del_step).pack(side="left", padx=4)
        ttk.Button(btns, text=self.T("clear"), command=self._clear_steps).pack(side="left", padx=4)
        ttk.Button(btns, text=self.T("up"), width=3,
                   command=lambda: self._move_step(-1)).pack(side="left", padx=(12, 2))
        ttk.Button(btns, text=self.T("down"), width=3,
                   command=lambda: self._move_step(1)).pack(side="left")
        ttk.Button(btns, text=self.T("capture"),
                   command=self._capture_cursor).pack(side="left", padx=(12, 4))

    def _plabel(self, name):
        if name == "button":
            return self.T("p_button")
        if name == "hold":
            return self.T("p_hold")
        if name == "duration":
            return self.T("p_duration")
        if name == "cps":
            return self.T("p_cps")
        return PARAM_LABEL.get(name, name)

    def _rebuild_params(self):
        for w in self.param_frame.winfo_children():
            w.destroy()
        self.pv = {}
        kind = self.kind_disp.get(self.kind_cb.get(), "click")
        for name, typ, default in PARAM_SCHEMA[kind]:
            ttk.Label(self.param_frame, text=self._plabel(name)).pack(side="left", padx=(8, 2))
            if typ == "choice":
                var = tk.StringVar(value=self.T(default[0]))
                ttk.Combobox(self.param_frame, textvariable=var, width=8, state="readonly",
                             values=[self.T(x) for x in default]).pack(side="left")
            else:
                var = tk.StringVar(value=str(default))
                ttk.Entry(self.param_frame, textvariable=var,
                          width=16 if typ == "str" else 8).pack(side="left")
            self.pv[name] = var

    def _on_mode(self):
        pass

    def _refresh_ports(self):
        from .transport import list_serial_ports
        ports = list_serial_ports()
        self.sport_cb["values"] = ports
        if ports and not self.sport_var.get():
            self.sport_var.set(ports[0])

    def _set_lang(self, code):
        self.T.set(code)
        self.lang_var.set(code)
        for w in self.root.winfo_children():
            w.destroy()
        self._build()
        self._rebuild_params()
        self._refresh_tree()
        self._log("[lang] " + dict(LANGS).get(code, code))

    def _build_run(self):
        f = ttk.Frame(self.root)
        f.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Button(f, text=self.T("run"), command=self._run).pack(side="left")
        ttk.Button(f, text=self.T("stop"), command=self._stop_run).pack(side="left", padx=4)
        ttk.Button(f, text=self.T("save"), command=self._save).pack(side="left", padx=4)
        ttk.Button(f, text=self.T("load"), command=self._load).pack(side="left", padx=4)
        self.prog = ttk.Progressbar(f, mode="determinate", maximum=100)
        self.prog.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(f, textvariable=self.now_var).pack(side="right")

    def _build_log(self):
        f = ttk.LabelFrame(self.root, text=self.T("log_title"), padding=6)
        f.pack(fill="both", expand=True, padx=8, pady=(6, 8))
        self.log = scrolledtext.ScrolledText(f, height=9, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", str(msg) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _connect(self):
        self._disconnect()
        mode = self.mode_var.get()
        try:
            sw = int(float(self.screen_w.get()))
            sh = int(float(self.screen_h.get()))
        except Exception:
            sw, sh = 1920, 1080
        try:
            if mode == "virtual":
                self.link = VirtualLink(
                    on_action=lambda item: self._log("[recv] %s" % (item,)),
                    screen=(sw, sh))
                self.client = ControlClient(self.link.client_transport)
                self.status_var.set(self.T("st_virtual"))
            elif mode == "tcp":
                from .transport import tcp_connect
                self.client = ControlClient(tcp_connect(self.host_var.get(), int(self.port_var.get())))
                self.status_var.set(self.T("st_connected"))
            else:
                from .transport import SerialTransport
                self.client = ControlClient(SerialTransport(self.sport_var.get()))
                self.status_var.set(self.T("st_connected"))
            self.client.set_screen(sw, sh)

            real = (mode != "virtual")
            use_feedback = bool(self.feedback_var.get()) and real
            use_guard = bool(self.guard_var.get()) and real
            if use_guard:
                from .guard import guard_client
                from .feedback import local_cursor
                try:
                    cur = local_cursor()
                except Exception:
                    cur = None
                ph = float(self.pause_hold_var.get() or 1.0)
                ri = float(self.resume_idle_var.get() or 3.0)
                self.gc, _g = guard_client(self.client, cur, pause_hold=ph,
                                           resume_idle=ri, feedback=use_feedback)
                self.gc.start()
                self._log("[guard] feedback=%s pause=%.1fs resume=%.1fs" % (use_feedback, ph, ri))
            elif use_feedback:
                from .feedback import local_cursor, FeedbackController
                try:
                    cur = local_cursor()
                except Exception:
                    cur = None
                self.gc = FeedbackController(self.client, cur)
                self._log("[feedback] closed-loop absolute mode")
            self._log(self.status_var.get())
        except Exception as e:
            self.status_var.set("%s: %s" % (self.T("st_error"), e))
            self._log(self.status_var.get())
            self._disconnect()

    def _disconnect(self):
        try:
            if self.gc is not None:
                try:
                    self.gc.stop()
                except Exception:
                    pass
                self.gc = None
            if self.client is not None:
                try:
                    self.client.close()
                except Exception:
                    pass
                self.client = None
            if self.link is not None:
                try:
                    self.link.stop()
                except Exception:
                    pass
                self.link = None
        finally:
            self.status_var.set(self.T("st_disconnected"))

    def _mask_of(self, label):
        for key, mask in BUTTON_MASK.items():
            if self.T(key) == label:
                return mask
        return 0x01

    def _bname(self, mask):
        return self.T("b_left" if mask == 1 else "b_right" if mask == 2 else "b_middle")

    def _collect_step(self):
        kind = self.kind_disp.get(self.kind_cb.get(), "click")
        s = {"t": float(self.t_var.get()), "kind": kind}
        for name, typ, default in PARAM_SCHEMA[kind]:
            v = self.pv[name].get()
            if typ == "int":
                v = int(float(v))
            s[name] = v
        if kind in ("click", "dclick"):
            s["mask"] = self._mask_of(s.get("button"))
        if kind == "drag":
            s["mask"] = 0x01
        return s

    def _add_step(self):
        try:
            s = self._collect_step()
        except Exception:
            messagebox.showwarning(self.T("app_title"), self.T("msg_bad", f="number"))
            return
        self.steps.append(s)
        self._refresh_tree()

    def _del_step(self):
        sel = self.tree.selection()
        if not sel:
            return
        rm = set(id(self.iid_step[i]) for i in sel if i in self.iid_step)
        self.steps = [s for s in self.steps if id(s) not in rm]
        self._refresh_tree()

    def _clear_steps(self):
        self.steps = []
        self._refresh_tree()

    def _move_step(self, d):
        sel = self.tree.selection()
        if not sel or sel[0] not in self.iid_step:
            return
        st = self.iid_step[sel[0]]
        ordered = sorted(self.steps, key=lambda x: x["t"])
        i = ordered.index(st)
        j = i + d
        if 0 <= j < len(ordered):
            a, b = ordered[i], ordered[j]
            a["t"], b["t"] = b["t"], a["t"]   # 시각만 교환(값 보존)
            self._refresh_tree()

    def _summary(self, s):
        k = s["kind"]
        if k == "move":
            return "(%d, %d)" % (s["x"], s["y"])
        if k == "click":
            return "(%d, %d) %s %dms" % (s["x"], s["y"], self._bname(s.get("mask", 1)), s.get("hold", 0))
        if k == "dclick":
            return "(%d, %d) %s x2" % (s["x"], s["y"], self._bname(s.get("mask", 1)))
        if k == "drag":
            return "(%d,%d)->(%d,%d) %dms" % (s["x"], s["y"], s["x2"], s["y2"], s["duration"])
        if k == "wheel":
            return "dy=%d" % s["dy"]
        if k == "key":
            return s["key"]
        if k == "hotkey":
            return s["hotkey"]
        if k == "text":
            return repr(s["text"]) + ((" %dcps" % s["cps"]) if s.get("cps") else "")
        if k == "wait":
            return "%dms" % s["duration"]
        return ""

    def _refresh_tree(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.iid_step = {}
        for s in sorted(self.steps, key=lambda x: x["t"]):
            iid = self.tree.insert("", "end", values=(
                "%.2f" % s["t"], self.T("k_" + s["kind"]), self._summary(s)))
            self.iid_step[iid] = s

    def _capture_cursor(self):
        try:
            from .feedback import local_cursor
            x, y = local_cursor().position()
        except Exception as e:
            self._log("capture failed: %s" % e)
            return
        if "x" in self.pv:
            self.pv["x"].set(str(x))
        if "y" in self.pv:
            self.pv["y"].set(str(y))
        self._log("[capture] (%d, %d)" % (x, y))

    def _run(self):
        if self.gc is None and self.client is None:
            messagebox.showwarning(self.T("app_title"), self.T("msg_need_conn"))
            return
        if not self.steps:
            messagebox.showwarning(self.T("app_title"), self.T("msg_no_step"))
            return
        self._stop.clear()
        self.status_var.set(self.T("st_running"))
        steps = [dict(s) for s in sorted(self.steps, key=lambda x: x["t"])]
        threading.Thread(target=self._worker, args=(steps,), daemon=True).start()

    def _stop_run(self):
        self._stop.set()
        self.status_var.set(self.T("st_stopped"))

    def _set_prog(self, t, total):
        self.prog["value"] = min(100.0, t / total * 100.0)
        self.now_var.set(self.T("t_now", v=t))

    def _finish(self):
        self.prog["value"] = 100.0
        self.status_var.set(self.T("st_done"))

    def _worker(self, steps):
        client = self.gc if self.gc is not None else self.client
        self._log("[run] %d steps" % len(steps))
        ctx = no_pointer_accel() if self.noaccel_var.get() else contextlib.nullcontext()
        try:
            with ctx:
                self._run_steps(client, steps)
        finally:
            self.root.after(0, self._finish)

    def _run_steps(self, client, steps):
        start = time.perf_counter()
        total = max(1.0, steps[-1]["t"]) if steps else 1.0
        for s in steps:
            if self._stop.is_set():
                break
            while True:
                remain = (start + s["t"]) - time.perf_counter()
                if remain <= 0 or self._stop.is_set():
                    break
                time.sleep(min(remain, 0.004))
            if self._stop.is_set():
                break
            try:
                self._run_step(client, s)
                self.root.after(0, self._log, "  t=%.2f %s %s"
                                % (s["t"], self.T("k_" + s["kind"]), self._summary(s)))
            except Exception as e:
                self.root.after(0, self._log, "  ERR %s" % e)
            self.root.after(0, self._set_prog, s["t"], total)

    def _run_step(self, c, s):
        from .sequence import execute_step
        execute_step(c, s)

    def _save(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(self.steps, fp, ensure_ascii=False, indent=2)
        self._log(self.T("msg_saved"))

    def _load(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if not path:
            return
        with open(path, "r", encoding="utf-8") as fp:
            self.steps = list(json.load(fp))
        self._refresh_tree()
        self._log(self.T("msg_loaded"))

    def _load_demo(self, full=False):
        base = [
            {"t": 0.0, "kind": "move", "x": 300, "y": 200},
            {"t": 0.4, "kind": "move", "x": 700, "y": 300},
            {"t": 0.8, "kind": "move", "x": 500, "y": 450},
        ]
        if full:
            base += [
                {"t": 1.2, "kind": "click", "x": 500, "y": 450, "mask": 1, "hold": 30},
                {"t": 1.6, "kind": "hotkey", "hotkey": "ctrl+a"},
                {"t": 1.9, "kind": "text", "text": "hello control", "cps": 8},
            ]
        base.append({"t": 3.0, "kind": "wait", "duration": 200})
        self.steps = base
        self._refresh_tree()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="control 시퀀스 테스트 UI")
    ap.add_argument("--demo", action="store_true", help="내장 데모 시퀀스(이동만)")
    ap.add_argument("--demo-full", action="store_true", help="데모(클릭/핫키/텍스트 포함)")
    ap.add_argument("--load", help="시퀀스 JSON 파일")
    ap.add_argument("--conn", choices=["virtual", "tcp", "serial"], help="시작 시 자동 연결")
    ap.add_argument("--serial", help="시리얼 포트(예: COM5)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", default="9999")
    args = ap.parse_args()
    root = tk.Tk()
    app = App(root)
    if args.load:
        try:
            with open(args.load, "r", encoding="utf-8") as fp:
                app.steps = list(json.load(fp))
            app._refresh_tree()
        except Exception as e:
            app._log("load error: %s" % e)
    elif args.demo or args.demo_full:
        app._load_demo(full=args.demo_full)
    if args.conn:
        app.mode_var.set(args.conn)
        if args.serial:
            app.sport_var.set(args.serial)
        app.host_var.set(args.host)
        app.port_var.set(args.port)
        app._connect()
    root.mainloop()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())





