"""First-run setup wizard (v1 — no account step)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from manmabot_v1.probes import (
    is_dungeon_map_id,
    list_farms_for_map,
    list_map_choices,
)
from manmabot_v1.profile import Profile, save_profile
from manmabot_v1.strings import normalize_game_language, ui_strings
from manmabot_v1.localized_names import (
    dungeon_tag,
    map_display_name,
    route_point_display_name,
)
from manmabot_v1.ui.character_picker import pack_character_choices
from manmabot_v1.ui.controls import disable_slider_mousewheel
from manmabot_v1.ui.driver_setup import show_driver_setup
from manmabot_v1.ui.loot_picker import pack_loot_choices


class SetupWizard(ctk.CTkToplevel):
    STEPS = 6  # welcome, drivers, character, loot, map, review

    def __init__(self, master) -> None:
        super().__init__(master)
        self.master_app = master
        self.s = ui_strings(master.profile.language)
        self.title(self.s.wizard_title)
        self.geometry("520x620")
        self.minsize(480, 480)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._block_close)

        self.profile = (
            Profile.from_dict(master.profile.to_dict())
            if hasattr(master, "profile")
            else Profile()
        )

        self.step = 0
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=16, pady=(16, 0))
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=16, pady=8)
        self.btn_back = ctk.CTkButton(
            nav, text=self.s.wizard_back, width=100, command=self._back
        )
        self.btn_back.pack(side="left")
        self.progress = ctk.CTkLabel(nav, text="")
        self.progress.pack(side="left", expand=True)
        self.btn_next = ctk.CTkButton(
            nav, text=self.s.wizard_continue, width=120, command=self._next
        )
        self.btn_next.pack(side="right")
        self._render()

    def _block_close(self) -> None:
        messagebox.showinfo(
            self.s.setup,
            self.s.wizard_block_close,
            parent=self,
        )

    def _clear_body(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()

    def _render(self) -> None:
        self._clear_body()
        self.progress.configure(
            text=self.s.wizard_step.format(cur=self.step + 1, total=self.STEPS)
        )
        self.btn_back.configure(state="normal" if self.step > 0 else "disabled")
        self.btn_next.configure(
            text=(
                self.s.wizard_finish
                if self.step == self.STEPS - 1
                else self.s.wizard_continue
            )
        )
        {
            0: self._step_welcome,
            1: self._step_drivers,
            2: self._step_character,
            3: self._step_loot,
            4: self._step_map,
            5: self._step_review,
        }[self.step]()

    def _step_welcome(self) -> None:
        ctk.CTkLabel(
            self.body,
            text=self.s.wizard_welcome,
            font=ctk.CTkFont(size=28, weight="bold"),
        ).pack(anchor="center", pady=(80, 8))

    def _step_drivers(self) -> None:
        ctk.CTkLabel(
            self.body,
            text=self.s.drivers_setup,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", pady=(24, 8))
        ctk.CTkLabel(
            self.body,
            text=self.s.drivers_setup_hint,
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))
        ctk.CTkButton(
            self.body,
            text=self.s.drivers_setup,
            width=200,
            command=self._open_driver_setup,
        ).pack(anchor="w", pady=8)
        ctk.CTkLabel(
            self.body,
            text=self.s.driver_restart_hint,
            text_color="gray",
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=8)

    def _open_driver_setup(self) -> None:
        show_driver_setup(self, require_ready=False)
        try:
            self.grab_set()
            self.lift()
        except Exception:
            pass

    def _step_character(self) -> None:
        ctk.CTkLabel(
            self.body, text=self.s.character, font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", pady=8)
        self.char_var = tk.StringVar(value=self.profile.character)
        self._char_portrait_refs = pack_character_choices(
            self.body,
            variable=self.char_var,
            strings=self.s,
            show_portraits=False,
            show_blurbs=False,
            padx=0,
            wraplength=320,
        )
        ctk.CTkLabel(
            self.body,
            text=self.s.game_language,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", pady=(16, 8))
        self.game_lang_var = tk.StringVar(
            value=normalize_game_language(self.profile.game_language)
        )
        for code, label in (
            ("ko", self.s.game_lang_ko),
            ("zh", self.s.game_lang_zh),
        ):
            ctk.CTkRadioButton(
                self.body,
                text=label,
                variable=self.game_lang_var,
                value=code,
            ).pack(anchor="w", pady=2)
        ctk.CTkLabel(
            self.body,
            text=self.s.game_language_hint,
            wraplength=420,
            justify="left",
            text_color="gray",
        ).pack(anchor="w", pady=4)

    def _pct_slider(self, label: str, value_ratio: float) -> tk.DoubleVar:
        """Slider 5–95 with a live ``Label: 55%`` caption."""
        var = tk.DoubleVar(value=value_ratio * 100)
        lab = ctk.CTkLabel(self.body, text=f"{label}: {int(round(var.get()))}%")
        lab.pack(anchor="w", pady=(12, 0))

        def on_change(_=None) -> None:
            lab.configure(text=f"{label}: {int(round(float(var.get())))}%")

        slider = ctk.CTkSlider(
            self.body, from_=5, to=95, variable=var, command=on_change
        )
        slider.pack(fill="x")
        disable_slider_mousewheel(slider)
        return var

    def _step_loot(self) -> None:
        ctk.CTkLabel(
            self.body,
            text=self.s.wizard_loot_survival,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", pady=8)
        self.loot_var = tk.StringVar(value=self.profile.loot_mode)
        self._loot_icon_refs = pack_loot_choices(
            self.body,
            variable=self.loot_var,
            strings=self.s,
            icon_box=(96, 96),
            wraplength=180,
        )
        self.adena_weight = self._pct_slider(
            self.s.loot_adena_weight, self.profile.loot_adena_weight_ratio
        )
        self.loot_weight_lab = ctk.CTkLabel(
            self.body,
            text=self.s.loot_weight_note.format(
                pct=int(round(float(self.adena_weight.get())))
            ),
            wraplength=420,
            text_color="gray",
        )
        self.loot_weight_lab.pack(anchor="w", pady=4)
        adena_cmd = self.adena_weight.trace_add

        def _adena_note(*_args) -> None:
            self.loot_weight_lab.configure(
                text=self.s.loot_weight_note.format(
                    pct=int(round(float(self.adena_weight.get())))
                )
            )

        adena_cmd("write", _adena_note)
        self.hp_pot = self._pct_slider(self.s.drink_hp, self.profile.hp_potion_ratio)
        self.hp_esc = self._pct_slider(self.s.escape_hp, self.profile.hp_escape_ratio)

    def _step_map(self) -> None:
        ctk.CTkLabel(
            self.body,
            text=self.s.wizard_map_title,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", pady=8)
        ctk.CTkLabel(
            self.body, text=self.s.wizard_map_body, wraplength=420, justify="left"
        ).pack(anchor="w")
        choices = list_map_choices(self.profile.language)
        if not choices:
            ctk.CTkLabel(
                self.body, text=self.s.start_fail["map_missing"], text_color="#ef4444"
            ).pack(anchor="w", pady=8)
            return
        ids = {mid for mid, _n, _d in choices}
        current = self.profile.active_map if self.profile.active_map in ids else choices[0][0]
        self.map_var = tk.StringVar(value=current)
        for mid, name, dungeon in choices:
            tag = f" · {dungeon_tag(self.profile.language)}" if dungeon else ""
            ctk.CTkRadioButton(
                self.body,
                text=f"{name} ({mid}){tag}",
                variable=self.map_var,
                value=mid,
            ).pack(anchor="w", pady=2)

    def _select_all_farms(self) -> None:
        if is_dungeon_map_id(self.profile.active_map):
            self.profile.selected_farms = []
            return
        names, _err = list_farms_for_map(self.profile.active_map)
        self.profile.selected_farms = list(names)

    def _step_review(self) -> None:
        ctk.CTkLabel(
            self.body, text=self.s.wizard_review, font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", pady=8)
        if is_dungeon_map_id(self.profile.active_map):
            farms = self.s.farms_unsupported_dungeon
        else:
            farms = ", ".join(
                route_point_display_name(name, self.profile.language)
                for name in self.profile.selected_farms
            ) or "—"
        text = self.s.wizard_review_body.format(
            character=self.s.char_titles.get(
                self.profile.character, self.profile.character
            ),
            game=(
                self.s.game_lang_zh
                if normalize_game_language(self.profile.game_language) == "zh"
                else self.s.game_lang_ko
            ),
            map=map_display_name(
                self.profile.active_map,
                self.profile.language,
                self.profile.active_map,
            ),
            loot=self.s.loot_labels[self.profile.loot_mode]["title"],
            farms=farms,
            pause=self.profile.hotkeys.get("pause_resume"),
            stop=self.profile.hotkeys.get("stop"),
            spells=self.s.wizard_spells_note,
        )
        ctk.CTkLabel(self.body, text=text, justify="left", wraplength=420).pack(
            anchor="w"
        )

    def _collect(self) -> bool:
        if self.step == 2:
            self.profile.character = self.char_var.get()
            if hasattr(self, "game_lang_var"):
                self.profile.game_language = normalize_game_language(
                    self.game_lang_var.get()
                )
        if self.step == 3:
            self.profile.loot_mode = self.loot_var.get()
            self.profile.loot_adena_weight_ratio = float(self.adena_weight.get()) / 100.0
            self.profile.hp_potion_ratio = float(self.hp_pot.get()) / 100.0
            self.profile.hp_escape_ratio = float(self.hp_esc.get()) / 100.0
            self.profile.mp_escape_enabled = False
        if self.step == 4:
            if hasattr(self, "map_var"):
                self.profile.active_map = self.map_var.get()
            if not self.profile.active_map:
                messagebox.showwarning(
                    self.s.map_select, self.s.start_fail["map_missing"], parent=self
                )
                return False
            self._select_all_farms()
        return True

    def _back(self) -> None:
        if self.step > 0:
            self.step -= 1
            self._render()

    def _next(self) -> None:
        if not self._collect():
            return
        if self.step >= self.STEPS - 1:
            self._select_all_farms()
            self.profile.wizard_completed = True
            save_profile(self.profile)
            self.master_app.apply_profile(self.profile)
            self.grab_release()
            self.destroy()
            return
        self.step += 1
        self._render()
