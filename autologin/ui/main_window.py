import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from launcher.bot_controller import BotAccount, close_all_purple
from launcher.elevate import is_admin, relaunch_as_admin
from .i18n import LANGUAGES, T, region_display, region_key_from_display
from .theme import (C, setup_style, make_button, set_button_enabled)
from .header import build_header
from .paths import build_paths
from .account_table import (build_account_table, validate_accounts)

EMAIL_RE = __import__("re").compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class MainWindow:
    LINEAGE_PATH = r"C:\Program Files (x86)\NC\Lineage Classic\LC.exe"

    @staticmethod
    def _discover_purple() -> str:
        """Prefer newest Purple.exe under Program Files (x86)\\NC\\Purple."""
        base = r"C:\Program Files (x86)\NC\Purple"
        fallback = r"C:\Program Files (x86)\NC\Purple\2.26.907.20\Purple.exe"
        try:
            if not os.path.isdir(base):
                return fallback if os.path.isfile(fallback) else ""
            best = ""
            for name in sorted(os.listdir(base), reverse=True):
                cand = os.path.join(base, name, "Purple.exe")
                if os.path.isfile(cand):
                    best = cand
                    break
            launcher = os.path.join(base, "PurpleLauncher.exe")
            if best:
                return best
            if os.path.isfile(launcher):
                return launcher
        except Exception:
            pass
        return fallback if os.path.isfile(fallback) else ""

    @property
    def PURPLE_PATH(self):
        return self._discover_purple()

    @property
    def CONFIG_PATH(self):
        # Frozen-safe: onedir -> _internal/launcher_config.json, onefile ->
        # persistent <exe_dir>/_data/launcher_config.json, source -> repo root.
        from launcher.auto_login import _launcher_config_path
        return _launcher_config_path()

    def __init__(self, root):
        self.root = root
        self.instances = []
        self.running = False
        self._launch_cancel = threading.Event()
        self._instances_lock = threading.Lock()

        self._cfg = self._load_config()
        self._accounts_data = list(self._cfg.get("accounts", []))
        self._editing = not self._accounts_data
        self._lang_disp = self._cfg.get("language", "English")
        if self._lang_disp not in LANGUAGES:
            self._lang_disp = "English"

        self.path_var = tk.StringVar(
            value=self._cfg.get("purple_path") or self.PURPLE_PATH)
        self.lineage_var = tk.StringVar(
            value=self._cfg.get("lineage_path") or self.LINEAGE_PATH)
        raw_mode = self._cfg.get("click_mode", "fixed") or "fixed"
        # hybrid/split -> UI "fixed" (golden coords); bot keeps purple/game modes
        ui_mode = "fixed" if str(raw_mode).lower() in (
            "hybrid", "split", "fixed") else "dynamic"
        self.search_mode_var = tk.StringVar(value=ui_mode)
        if self.search_mode_var.get() not in ("dynamic", "fixed"):
            self.search_mode_var.set("fixed")
        self.require_admin_var = tk.BooleanVar(
            value=bool(self._cfg.get("require_elevation", True)))
        self._setup_style()
        self._build_ui()
        self._restore_settings()
        saved = self._cfg.get("mode", "Single")
        if saved not in ("Single", "RecordTag"):
            saved = "Single"
        self._select_tab(saved)
        self._on_tab_changed()
        self.root.minsize(700, 1)

    @property
    def t(self):
        return T[LANGUAGES[self._lang_disp]]

    @property
    def _lang_code(self):
        return LANGUAGES[self._lang_disp]

    def _setup_style(self):
        setup_style(self.root)

    def _load_config(self):
        try:
            with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self, data):
        try:
            # Merge over the current config so unrecognized keys (e.g. the
            # bot's 'login' section) are preserved rather than wiped out.
            merged = dict(self._load_config())
            merged.update(data)
            with open(self.CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return False

    def _build_ui(self):
        tr = self.t
        self.root.title(tr["title"])
        self.root.configure(bg=C.BG)
        for w in self.root.winfo_children():
            w.destroy()

        elevated = is_admin()
        admin_status = tr["admin_yes"] if elevated else tr["admin_no"]
        self.lang_box, self._admin_lbl, self._elevate_btn = build_header(
            self.root, tr, self._lang_disp, self._on_language,
            admin_status=admin_status,
            on_elevate=None if elevated else self._on_elevate)

        body = tk.Frame(self.root, bg=C.BG)
        body.pack(fill="both", expand=True, padx=14, pady=(10, 0))

        build_paths(body, tr, self.path_var, self.lineage_var,
                    self._browse, self._browse_lineage)

        had_running = getattr(self, "running", False)
        search_row = tk.Frame(body, bg=C.BG)
        search_row.pack(fill="x", pady=(8, 0))
        tk.Label(search_row, text=tr["search_method"] + ":", bg=C.BG,
                 fg=C.TEXT, font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Radiobutton(
            search_row, text=tr["pos_dynamic"], value="dynamic",
            variable=self.search_mode_var, command=self._on_search_mode,
            bg=C.BG, fg=C.TEXT, selectcolor=C.SURFACE, activebackground=C.BG,
            activeforeground=C.TEXT, font=("Segoe UI", 9),
            highlightthickness=0).pack(side="left", padx=(10, 0))
        tk.Radiobutton(
            search_row, text=tr["pos_fixed"], value="fixed",
            variable=self.search_mode_var, command=self._on_search_mode,
            bg=C.BG, fg=C.TEXT, selectcolor=C.SURFACE, activebackground=C.BG,
            activeforeground=C.TEXT, font=("Segoe UI", 9),
            highlightthickness=0).pack(side="left", padx=(12, 0))

        admin_row = tk.Frame(body, bg=C.BG)
        admin_row.pack(fill="x", pady=(6, 0))
        tk.Checkbutton(
            admin_row, text=tr["require_admin"],
            variable=self.require_admin_var, command=self._on_require_admin,
            bg=C.BG, fg=C.TEXT, selectcolor=C.SURFACE, activebackground=C.BG,
            activeforeground=C.TEXT, font=("Segoe UI", 9),
            highlightthickness=0).pack(side="left")
        if not elevated:
            tk.Label(admin_row, text=tr["elevate_need"], bg=C.BG,
                     fg=C.DANGER, font=("Segoe UI", 8)).pack(
                         side="left", padx=(12, 0))

        tab_btn_row = tk.Frame(body, bg=C.BG)
        tab_btn_row.pack(fill="x", pady=(6, 0))

        self.notebook = ttk.Notebook(tab_btn_row)
        self.notebook.pack(side="left", fill="x", expand=True)

        bf = tk.Frame(tab_btn_row, bg=C.BG)
        bf.pack(side="right")
        self.start_btn = make_button(bf, tr["start_one"], self._start_all, "primary")
        self.start_btn.pack(side="left", padx=(0, 6))
        self.stop_btn = make_button(bf, tr["stop_one"], self._stop_all, "danger")
        self.stop_btn.pack(side="left")
        set_button_enabled(self.start_btn, not had_running, "primary")
        set_button_enabled(self.stop_btn, had_running, "danger")

        self.tab_single = ttk.Frame(self.root, style="TFrame")
        self.tab_record = ttk.Frame(self.root, style="TFrame")

        self.notebook.add(self.tab_single, text=f" {tr['modes']['Single']} ")
        self.notebook.add(self.tab_record, text=f" {tr['modes']['RecordTag']} ")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._tab_content = tk.Frame(body, bg=C.BG)
        self._tab_content.pack(fill="both", expand=True, pady=(6, 10))

        self._build_single_tab()

        self.root.update_idletasks()
        self.root.minsize(700, self.root.winfo_reqheight())
        self.root.geometry("")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    # tab builders
    # ------------------------------------------------------------------ #
    def _build_single_tab(self):
        for w in self._tab_content.winfo_children():
            w.destroy()
        tr = self.t
        hint = tk.Frame(self._tab_content, bg=C.BG)
        hint.pack(fill="x", pady=(6, 3))
        tk.Label(hint, text=tr["single_hint"], bg=C.BG, fg=C.TEXT,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(hint, text=tr["single_desc"], bg=C.BG, fg=C.TEXT_DIM,
                 font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))
        self.account_rows, self._acc_status = build_account_table(
            self._tab_content, 1, tr, self._accounts_data, self._editing,
            self._lang_code, on_save=self._on_save, on_edit=self._on_edit)

    def _build_record_tab(self):
        for w in self._tab_content.winfo_children():
            w.destroy()
        tr = self.t
        hint = tk.Frame(self._tab_content, bg=C.BG)
        hint.pack(fill="x", pady=(6, 3))
        tk.Label(hint, text=tr["record_hint"], bg=C.BG, fg=C.TEXT,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(hint, text=tr["record_desc"], bg=C.BG, fg=C.TEXT_DIM,
                 font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))
        self.account_rows, self._acc_status = build_account_table(
            self._tab_content, 1, tr, self._accounts_data, self._editing,
            self._lang_code, on_save=self._on_save, on_edit=self._on_edit)

    # ------------------------------------------------------------------ #
    # tab navigation
    # ------------------------------------------------------------------ #
    def _current_tab(self):
        sel = self.notebook.select()
        for name, tab in [("Single", self.tab_single),
                          ("RecordTag", self.tab_record)]:
            if sel == str(tab):
                return name
        return "Single"

    def _select_tab(self, name):
        if name not in ("Single", "RecordTag"):
            name = "Single"
        tab = {"Single": self.tab_single,
               "RecordTag": self.tab_record}[name]
        self.notebook.select(tab)

    def _on_tab_changed(self, _e=None):
        cur_h = self.root.winfo_height()
        mode = self._current_tab()
        tr = self.t
        self.start_btn.configure(text=tr["start_one"])
        self.stop_btn.configure(text=tr["stop_one"])
        if mode == "RecordTag":
            self._build_record_tab()
        else:
            self._build_single_tab()
        self.root.update_idletasks()
        new_h = self.root.winfo_reqheight()
        if cur_h > new_h:
            self.root.minsize(700, cur_h)
            self.root.geometry(f"700x{cur_h}")
        else:
            self.root.minsize(700, new_h)
            self.root.geometry("")

    def _on_search_mode(self):
        self._save_config(self._settings_payload())

    def _on_require_admin(self):
        self._save_config(self._settings_payload())

    def warn_not_elevated(self):
        """Called once from main when auto-elevate was declined/skipped."""
        if is_admin():
            return
        try:
            messagebox.showwarning(self.t["admin_no"], self.t["elevate_need"])
        except Exception:
            pass

    def _on_elevate(self, confirm=True):
        """Header / Start: relaunch this UI elevated, then exit."""
        if is_admin():
            return
        if confirm and not messagebox.askyesno(
                self.t["elevate_btn"], self.t["elevate_ask"]):
            return
        self._save_config(self._settings_payload())
        if relaunch_as_admin():
            try:
                self.root.destroy()
            except Exception:
                pass
            sys.exit(0)
        messagebox.showwarning(self.t["elevate_btn"], self.t["elevate_failed"])

    # ------------------------------------------------------------------ #
    # language / save / edit
    # ------------------------------------------------------------------ #
    def _on_language(self, _e=None):
        prev = self._current_tab()
        self._lang_disp = self.lang_box.get()
        cfg = self._load_config()
        cfg["language"] = self._lang_disp
        self._save_config(cfg)
        self._build_ui()
        self._select_tab(prev)
        self._on_tab_changed()

    def _on_edit(self):
        self._editing = True
        if self._current_tab() == "RecordTag":
            self._build_record_tab()
        else:
            self._build_single_tab()

    def _validate_accounts(self):
        tr = self.t
        errors = validate_accounts(self.account_rows, tr, self._lang_code)
        if hasattr(self, "_acc_status") and self._acc_status.winfo_exists():
            self._acc_status.configure(
                text="  \u2022  ".join(f"#{i+1}: {m}" for i, _, m in errors))
        return not errors

    def _on_save(self):
        if not self._validate_accounts():
            return
        collected = [{"id": r["id"].get().strip(),
                      "pw": r["pw"].get(),
                      "region": region_key_from_display(
                          self._lang_code, r["region"].get()),
                      "server": r["server"].get().strip()}
                     for r in self.account_rows]
        self._accounts_data = collected
        payload = self._settings_payload({"accounts": collected})
        if self._save_config(payload):
            self._editing = False
            if self._current_tab() == "RecordTag":
                self._build_record_tab()
            else:
                self._build_single_tab()
            self._log(self.t["saved"])

    # ------------------------------------------------------------------ #
    def _settings_payload(self, extra=None):
        mode = self._current_tab()
        if mode not in ("Single", "RecordTag"):
            mode = "Single"
        data = {
            "purple_path": self.path_var.get().strip(),
            "lineage_path": self.lineage_var.get().strip(),
            "language": self._lang_disp,
            "mode": mode,
            "click_mode": self.search_mode_var.get() or "dynamic",
            "require_elevation": bool(self.require_admin_var.get()),
            "accounts": self._accounts_data,
        }
        if extra:
            data.update(extra)
        return data

    def _restore_settings(self):
        self.path_var.set(self._cfg.get("purple_path") or self.PURPLE_PATH)
        self.lineage_var.set(
            self._cfg.get("lineage_path") or self.LINEAGE_PATH)
        click_mode = self._cfg.get("click_mode", "fixed") or "fixed"
        # hybrid was coerced to dynamic before — that broke fixed-position login.
        if str(click_mode).lower() in ("hybrid", "split", "fixed"):
            click_mode = "fixed"
        elif click_mode not in ("dynamic", "fixed"):
            click_mode = "fixed"
        self.search_mode_var.set(click_mode)
        self.require_admin_var.set(
            bool(self._cfg.get("require_elevation", True)))

    def _browse(self):
        path = filedialog.askopenfilename(title="Select Purple.exe",
                                          filetypes=[("Executable", "*.exe")])
        if path:
            self.path_var.set(path)
            self._save_config(self._settings_payload({"purple_path": path}))

    def _browse_lineage(self):
        path = filedialog.askopenfilename(
            title="Select Lineage Classic exe",
            filetypes=[("Executable", "*.exe")])
        if path:
            self.lineage_var.set(path)
            self._save_config(self._settings_payload({"lineage_path": path}))

    def _get_count(self):
        return 1

    def _get_interval(self):
        return 0

    def _log(self, msg):
        print(msg, flush=True)

    # ------------------------------------------------------------------ #
    def _start_all(self):
        purple = self.path_var.get().strip()
        if not purple or not os.path.isfile(purple):
            messagebox.showerror("Error", self.t["err_purple"])
            return
        if self.require_admin_var.get() and not is_admin():
            if messagebox.askyesno(
                    self.t["elevate_btn"],
                    self.t["elevate_required_start"] + "\n\n"
                    + self.t["elevate_ask"]):
                self._on_elevate(confirm=False)
            return
        mode = self._current_tab()
        record_tag = (mode == "RecordTag")
        missing = [i + 1 for i, r in enumerate(self.account_rows[:1])
                   if not r["id"].get().strip()]
        if missing:
            messagebox.showwarning(
                "Accounts", self.t["warn_fill"].format(
                    ids=", #".join(map(str, missing))))
            return
        self._save_config(self._settings_payload())
        count = 1
        interval = 0

        self.running = True
        set_button_enabled(self.start_btn, False, "primary")
        set_button_enabled(self.stop_btn, True, "danger")

        self._launch_cancel.clear()
        threading.Thread(target=self._staggered_launch,
                         args=(purple, count, interval, record_tag),
                         daemon=True).start()

    def _staggered_launch(self, purple, count, interval, record_tag=False):
        accounts = getattr(self, "_accounts_data", [])
        if count == 1:
            leftover = close_all_purple()
            if leftover:
                self._log("Single: closed leftover Purple so only one "
                          "window is used (%s)" % leftover)
                time.sleep(0.6)
        prev_bot = None
        for i in range(count):
            if self._launch_cancel.is_set():
                return
            if prev_bot is not None:
                waited = 0.0
                while not prev_bot.unlock_done.is_set():
                    if self._launch_cancel.wait(0.25):
                        return
                    waited += 0.25
                    if waited > 40:
                        break
            account = dict(accounts[i] if i < len(accounts) else {})
            account["click_mode"] = self.search_mode_var.get() or "dynamic"
            auto_login = bool(account.get("id")) and bool(account.get("pw"))
            bot = BotAccount(i+1, purple, on_log=self._log,
                             account=account, auto_login=auto_login,
                             record_tag=record_tag,
                             exclusive_purple=(count == 1))
            with self._instances_lock:
                if self._launch_cancel.is_set():
                    return
                self.instances.append(bot)
            bot.start()
            prev_bot = bot
            if interval > 0 and i < count - 1:
                mins = f"{interval//60}m" if interval >= 60 else ""
                secs = f"{interval%60}s" if interval % 60 or not mins else ""
                self._log(self.t["next_in"].format(t=f"{mins}{secs}"))
                waited = 0.0
                while waited < interval:
                    if self._launch_cancel.wait(0.25):
                        return
                    waited += 0.25

        settle = 1.5 + (count-1) * (0 if interval <= 1 else 1)
        time.sleep(settle)
        if self._launch_cancel.is_set():
            return
        with self._instances_lock:
            snapshot = list(self.instances)
        running = [b.idx for b in snapshot if b.state == "running"]
        blocked = [b.idx for b in snapshot if b.state == "purple_blocked"]
        if running:
            self._log(self.t["running"].format(ids=running, n=len(running)))
        if blocked:
            self._log(self.t["blocked"].format(ids=blocked))

    def _stop_all(self):
        self._launch_cancel.set()
        with self._instances_lock:
            instances = list(self.instances)
            self.instances.clear()
        for inst in instances:
            inst.stop(kill_purple=True)
        self.running = False
        set_button_enabled(self.start_btn, True, "primary")
        set_button_enabled(self.stop_btn, False, "danger")
        self._log(self.t["stopped"])

    def _on_close(self):
        if self.running:
            self._stop_all()
        self.root.destroy()
