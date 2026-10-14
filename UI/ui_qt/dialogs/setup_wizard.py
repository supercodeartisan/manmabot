"""First-run setup wizard (Qt) — welcome → drivers → character → loot → map → review."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from i18n.localized_names import dungeon_tag, map_display_name, route_point_display_name
from i18n.strings import normalize_game_language, ui_strings
from session.probes import is_dungeon_map_id, list_farms_for_map, list_map_choices
from ui.hangul_sort import hangul_sort_key
from settings.profile import CHARACTER_IDS, Profile, save_profile
from ui.loot_modes import LOOT_MODES
from ui_qt.dialogs.driver_setup_dialog import show_driver_setup
from ui_qt.theme import tokens


class SetupWizard(QDialog):
    STEPS = 6

    def __init__(
        self,
        parent: QWidget | None,
        *,
        profile: Profile,
        on_apply: Callable[[Profile], None],
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_apply = on_apply
        self.on_log = on_log
        self.profile = Profile.from_dict(profile.to_dict())
        self.s = ui_strings(self.profile.language)
        self.step = 0
        self._char_group: QButtonGroup | None = None
        self._lang_group: QButtonGroup | None = None
        self._loot_group: QButtonGroup | None = None
        self._map_group: QButtonGroup | None = None
        self._sliders: dict[str, QSlider] = {}

        self.setWindowTitle(self.s.wizard_title)
        self.resize(520, 620)
        self.setMinimumSize(480, 480)
        self.setModal(True)

        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body_host = QWidget()
        self.body = QVBoxLayout(self.body_host)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.body_host)
        root.addWidget(scroll, stretch=1)

        nav = QHBoxLayout()
        self.btn_back = QPushButton(self.s.wizard_back)
        self.btn_back.clicked.connect(self._back)
        nav.addWidget(self.btn_back)
        self.progress = QLabel("")
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self.progress, stretch=1)
        self.btn_next = QPushButton(self.s.wizard_continue)
        self.btn_next.clicked.connect(self._next)
        nav.addWidget(self.btn_next)
        root.addLayout(nav)
        self._render()

    def reject(self) -> None:
        QMessageBox.information(self, self.s.setup, self.s.wizard_block_close)

    def _clear_body(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render(self) -> None:
        self._clear_body()
        self.progress.setText(
            self.s.wizard_step.format(cur=self.step + 1, total=self.STEPS)
        )
        self.btn_back.setEnabled(self.step > 0)
        self.btn_next.setText(
            self.s.wizard_finish if self.step == self.STEPS - 1 else self.s.wizard_continue
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
        label = QLabel(self.s.wizard_welcome)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("font-size: 24px; font-weight: 700; margin-top: 80px;")
        self.body.addWidget(label)

    def _step_drivers(self) -> None:
        title = QLabel(self.s.drivers_setup)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.body.addWidget(title)
        hint = QLabel(self.s.drivers_setup_hint)
        hint.setWordWrap(True)
        self.body.addWidget(hint)
        btn = QPushButton(self.s.drivers_setup)
        btn.clicked.connect(self._open_driver_setup)
        self.body.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)
        restart = QLabel(self.s.driver_restart_hint)
        restart.setWordWrap(True)
        restart.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        self.body.addWidget(restart)

    def _open_driver_setup(self) -> None:
        show_driver_setup(
            self,
            language=self.profile.language,
            require_ready=False,
            on_log=self.on_log,
        )

    def _step_character(self) -> None:
        title = QLabel(self.s.character)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.body.addWidget(title)
        self._char_group = QButtonGroup(self)
        for key in CHARACTER_IDS:
            radio = QRadioButton(self.s.char_titles.get(key, key))
            radio.setChecked(key == self.profile.character)
            radio.setProperty("value", key)
            self._char_group.addButton(radio)
            self.body.addWidget(radio)
        lang_title = QLabel(self.s.game_language)
        lang_title.setStyleSheet("font-size: 16px; font-weight: 600; margin-top: 12px;")
        self.body.addWidget(lang_title)
        self._lang_group = QButtonGroup(self)
        current = normalize_game_language(self.profile.game_language)
        for code, label in (("ko", self.s.game_lang_ko), ("zh", self.s.game_lang_zh)):
            radio = QRadioButton(label)
            radio.setChecked(code == current)
            radio.setProperty("value", code)
            self._lang_group.addButton(radio)
            self.body.addWidget(radio)
        hint = QLabel(self.s.game_language_hint)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        self.body.addWidget(hint)

    def _pct_slider(self, key: str, label: str, value_ratio: float) -> QSlider:
        caption = QLabel(f"{label}: {int(round(value_ratio * 100))}%")
        self.body.addWidget(caption)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(5, 95)
        slider.setValue(int(round(value_ratio * 100)))
        slider.valueChanged.connect(
            lambda value, lab=caption, text=label: lab.setText(f"{text}: {int(value)}%")
        )
        self.body.addWidget(slider)
        self._sliders[key] = slider
        return slider

    def _step_loot(self) -> None:
        title = QLabel(self.s.wizard_loot_survival)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.body.addWidget(title)
        self._loot_group = QButtonGroup(self)
        for key in LOOT_MODES:
            meta = self.s.loot_labels.get(key) or {"title": key}
            radio = QRadioButton(str(meta.get("title") or key))
            radio.setChecked(key == self.profile.loot_mode)
            radio.setProperty("value", key)
            self._loot_group.addButton(radio)
            self.body.addWidget(radio)
        adena = self._pct_slider(
            "adena", self.s.loot_adena_weight, self.profile.loot_adena_weight_ratio
        )
        self._adena_note = QLabel(
            self.s.loot_weight_note.format(pct=int(adena.value()))
        )
        self._adena_note.setWordWrap(True)
        self._adena_note.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        self.body.addWidget(self._adena_note)
        adena.valueChanged.connect(
            lambda value: self._adena_note.setText(
                self.s.loot_weight_note.format(pct=int(value))
            )
        )
        self._pct_slider("hp_pot", self.s.drink_hp, self.profile.hp_potion_ratio)
        self._pct_slider("hp_esc", self.s.escape_hp, self.profile.hp_escape_ratio)

    def _step_map(self) -> None:
        title = QLabel(self.s.wizard_map_title)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.body.addWidget(title)
        body = QLabel(self.s.wizard_map_body)
        body.setWordWrap(True)
        self.body.addWidget(body)
        choices = list(list_map_choices(self.profile.language))
        choices.sort(key=lambda item: hangul_sort_key(item[1]))
        if not choices:
            missing = QLabel(self.s.start_fail["map_missing"])
            missing.setStyleSheet("color: #dc2626;")
            self.body.addWidget(missing)
            self._map_group = None
            return
        ids = {mid for mid, _n, _d in choices}
        current = (
            self.profile.active_map if self.profile.active_map in ids else choices[0][0]
        )
        self._map_group = QButtonGroup(self)
        for mid, name, dungeon in choices:
            tag = f" · {dungeon_tag(self.profile.language)}" if dungeon else ""
            radio = QRadioButton(f"{name} ({mid}){tag}")
            radio.setChecked(mid == current)
            radio.setProperty("value", mid)
            self._map_group.addButton(radio)
            self.body.addWidget(radio)

    def _select_all_farms(self) -> None:
        if is_dungeon_map_id(self.profile.active_map):
            self.profile.selected_farms = []
            return
        names, _err = list_farms_for_map(self.profile.active_map)
        self.profile.selected_farms = list(names)

    def _step_review(self) -> None:
        title = QLabel(self.s.wizard_review)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.body.addWidget(title)
        if is_dungeon_map_id(self.profile.active_map):
            farms = self.s.farms_unsupported_dungeon
        else:
            farms = (
                ", ".join(
                    route_point_display_name(name, self.profile.language)
                    for name in self.profile.selected_farms
                )
                or "—"
            )
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
        label = QLabel(text)
        label.setWordWrap(True)
        self.body.addWidget(label)

    def _group_value(self, group: QButtonGroup | None) -> str | None:
        if group is None:
            return None
        button = group.checkedButton()
        if button is None:
            return None
        return str(button.property("value") or "")

    def _collect(self) -> bool:
        if self.step == 2:
            character = self._group_value(self._char_group)
            if character:
                self.profile.character = character
            game_lang = self._group_value(self._lang_group)
            if game_lang:
                self.profile.game_language = normalize_game_language(game_lang)
        if self.step == 3:
            loot = self._group_value(self._loot_group)
            if loot:
                self.profile.loot_mode = loot
            self.profile.loot_adena_weight_ratio = (
                float(self._sliders["adena"].value()) / 100.0
            )
            self.profile.hp_potion_ratio = float(self._sliders["hp_pot"].value()) / 100.0
            self.profile.hp_escape_ratio = float(self._sliders["hp_esc"].value()) / 100.0
            self.profile.mp_escape_enabled = False
        if self.step == 4:
            mid = self._group_value(self._map_group)
            if mid:
                self.profile.active_map = mid
            if not self.profile.active_map:
                QMessageBox.warning(
                    self, self.s.map_select, self.s.start_fail["map_missing"]
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
            self.on_apply(self.profile)
            self.accept()
            return
        self.step += 1
        self._render()
