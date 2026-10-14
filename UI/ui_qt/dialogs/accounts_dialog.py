"""Accounts manager — parity with classic ``ScheduleWindow.open_accounts``."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from settings.accounts import Account, AccountStore, AccountStoreError
from settings.profile import Profile, save_profile
from settings.server_list import server_names_list
from ui_qt.editors.form_helpers import configure_select_rows
from ui_qt.theme import tokens
from ui_qt.theme.apply import mark_accent


def _plain_field(widget: QWidget) -> None:
    """Force white field chrome (avoid Windows blue autofill / highlight fill)."""
    palette = widget.palette()
    palette.setColor(QPalette.ColorRole.Base, QColor(tokens.SURFACE))
    palette.setColor(QPalette.ColorRole.Text, QColor(tokens.TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens.ACCENT_SOFT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens.TEXT))
    widget.setPalette(palette)
    widget.setStyleSheet(
        f"background: {tokens.SURFACE}; color: {tokens.TEXT}; "
        f"border: 1px solid {tokens.BORDER}; border-radius: 4px; padding: 3px 6px;"
    )

_DEFAULT_PURPLE_PATH = r"C:\Program Files (x86)\NC\Purple\PurpleLauncher.exe"
_DEFAULT_GAME_PATH = r"C:\Program Files (x86)\NC\Lineage Classic\LC.exe"

_ACCOUNT_COLUMNS = (
    ("display_name", "display_name", 120),
    ("server", "server", 100),
    ("character_number", "character_order", 108),
    ("username", "username", 210),
    ("password", "password", 84),
    ("region", "region", 72),
    ("locale", "server_language", 124),
    ("character_type", "character_type", 108),
    ("purple_path", "purple_path", 140),
    ("game_path", "game_path", 140),
)


def _label_for(ids: dict[str, str], code: str) -> str:
    for label, item_id in ids.items():
        if item_id == str(code):
            return label
    return str(code)


class AccountEditorDialog(QDialog):
    """New / edit account form — same fields as classic nested editor."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        strings: dict[str, str],
        language: str,
        store: AccountStore,
        account: Account | None = None,
        profile: Profile | None = None,
    ) -> None:
        super().__init__(parent)
        self.t = strings
        self.language = language
        self.store = store
        self.account = account
        self.profile = profile
        self.setWindowTitle(self.t.get("account", "Account"))
        self.setModal(True)
        self.setMinimumWidth(520)
        self.resize(560, 480)

        self.region_ids = {
            self.t.get("region_korea", "Korea"): "Korea",
            self.t.get("region_china", "China"): "China",
        }
        self.locale_ids = {
            self.t.get("locale_korean", "Korean"): "ko",
            self.t.get("locale_simplified_chinese", "Simplified Chinese"): "zh-CN",
        }
        self.character_ids = {
            self.t.get("royal", "Royal"): "royal",
            self.t.get("knight", "Knight"): "knight",
            self.t.get("elf", "Elf"): "elf",
            self.t.get("mage", "Mage"): "mage",
        }

        if account and account.locale in ("ko", "zh-CN"):
            default_locale = account.locale
        else:
            default_locale = "zh-CN" if language == "zh" else "ko"
        default_region = "China" if default_locale == "zh-CN" else "Korea"
        raw_slot = int(account.character_number) if account else 1
        if raw_slot not in (1, 2, 3):
            raw_slot = 1
        character_type = (
            account.character_type
            if account and account.character_type in self.character_ids.values()
            else "royal"
        )
        purple_path = (
            account.purple_launcher_path
            if account and account.purple_launcher_path
            else _DEFAULT_PURPLE_PATH
        )
        game_path = (
            account.game_path if account and account.game_path else _DEFAULT_GAME_PATH
        )

        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        self.display_name = QLineEdit(
            account.display_name if account else ""
        )
        self.username = QLineEdit(account.username if account else "")
        self.password = QLineEdit(account.password if account else "")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        pwd_row = QHBoxLayout()
        pwd_row.setContentsMargins(0, 0, 0, 0)
        pwd_row.setSpacing(6)
        pwd_row.addWidget(self.password, stretch=1)
        self._pwd_shown = False
        eye = QPushButton(self.t.get("show", "Show"))
        eye.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        eye.clicked.connect(self._toggle_password)
        self._pwd_eye = eye
        pwd_row.addWidget(eye)
        pwd_wrap = QWidget()
        pwd_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        pwd_wrap.setLayout(pwd_row)

        self.region = QComboBox()
        for label in self.region_ids:
            self.region.addItem(label, self.region_ids[label])
        self.region.setCurrentIndex(
            max(0, self.region.findData(default_region))
        )

        self.locale = QComboBox()
        for label in self.locale_ids:
            self.locale.addItem(label, self.locale_ids[label])
        self.locale.setCurrentIndex(
            max(0, self.locale.findData(default_locale))
        )

        self.server = QComboBox()
        self.server.setEditable(False)
        self._reload_servers(
            default_locale,
            account.server if account else "",
        )

        self.slot_group = QButtonGroup(self)
        slot_row = QHBoxLayout()
        slot_wrap = QWidget()
        for slot in (1, 2, 3):
            radio = QRadioButton(str(slot))
            radio.setChecked(slot == raw_slot)
            self.slot_group.addButton(radio, slot)
            slot_row.addWidget(radio)
        slot_row.addStretch(1)
        slot_wrap.setLayout(slot_row)

        self.character_type = QComboBox()
        for label in self.character_ids:
            self.character_type.addItem(label, self.character_ids[label])
        self.character_type.setCurrentIndex(
            max(0, self.character_type.findData(character_type))
        )

        self.purple_path = QLineEdit(purple_path)
        self.game_path = QLineEdit(game_path)

        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow(self.t.get("display_name", "Display name"), self.display_name)
        form.addRow(self.t.get("username", "Username"), self.username)
        form.addRow(self.t.get("password", "Password"), pwd_wrap)
        form.addRow(self.t.get("region", "Region"), self.region)
        form.addRow(self.t.get("server_language", "Server language"), self.locale)
        form.addRow(self.t.get("server", "Server"), self.server)
        form.addRow(self.t.get("character_order", "Slot"), slot_wrap)
        form.addRow(self.t.get("character_type", "Class"), self.character_type)
        form.addRow(
            self.t.get("purple_path", "Purple path"),
            self._path_row(self.purple_path, self.t.get("purple_path", "Purple path")),
        )
        form.addRow(
            self.t.get("game_path", "Game path"),
            self._path_row(self.game_path, self.t.get("game_path", "Game path")),
        )
        for field in (
            self.display_name,
            self.username,
            self.password,
            self.purple_path,
            self.game_path,
            self.region,
            self.locale,
            self.server,
            self.character_type,
        ):
            _plain_field(field)

        self.region.currentIndexChanged.connect(self._region_changed)
        self.locale.currentIndexChanged.connect(self._locale_changed)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        action = QPushButton(
            self.t.get("account_add", "Add")
            if account is None
            else self.t.get("save", "Save")
        )
        mark_accent(action)
        action.clicked.connect(self._save)
        cancel = QPushButton(self.t.get("cancel", "Cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(action)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    def _path_row(self, edit: QLineEdit, title: str) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, stretch=1)
        browse = QPushButton(self.t.get("browse", "Browse"))
        browse.clicked.connect(lambda: self._browse(edit, title))
        row.addWidget(browse)
        return wrap

    def _browse(self, edit: QLineEdit, title: str) -> None:
        current = Path(str(edit.text() or "")).expanduser()
        initial = current.parent if current.parent.exists() else Path.home()
        selected, _ = QFileDialog.getOpenFileName(
            self,
            title,
            str(initial),
            f"{self.t.get('executables', 'Executable files')} (*.exe);;"
            f"{self.t.get('all_files', 'All files')} (*.*)",
        )
        if selected:
            edit.setText(selected)

    def _toggle_password(self) -> None:
        self._pwd_shown = not self._pwd_shown
        self.password.setEchoMode(
            QLineEdit.EchoMode.Normal
            if self._pwd_shown
            else QLineEdit.EchoMode.Password
        )
        if hasattr(self, "_pwd_eye"):
            self._pwd_eye.setText(
                self.t.get("hide", "Hide") if self._pwd_shown else self.t.get("show", "Show")
            )

    def _reload_servers(self, locale: str, current: str = "") -> None:
        servers = server_names_list(locale)
        if current and current not in servers:
            servers = [current, *servers]
        self.server.blockSignals(True)
        self.server.clear()
        self.server.addItems(servers)
        if current and current in servers:
            self.server.setCurrentText(current)
        elif servers:
            self.server.setCurrentIndex(0)
        self.server.blockSignals(False)

    def _region_changed(self) -> None:
        region = str(self.region.currentData() or "Korea")
        locale = "zh-CN" if region == "China" else "ko"
        self.locale.blockSignals(True)
        self.locale.setCurrentIndex(max(0, self.locale.findData(locale)))
        self.locale.blockSignals(False)
        self._reload_servers(locale, self.server.currentText())

    def _locale_changed(self) -> None:
        locale = str(self.locale.currentData() or "ko")
        region = "China" if locale == "zh-CN" else "Korea"
        self.region.blockSignals(True)
        self.region.setCurrentIndex(max(0, self.region.findData(region)))
        self.region.blockSignals(False)
        self._reload_servers(locale, self.server.currentText())

    def _save(self) -> None:
        slot = self.slot_group.checkedId()
        if slot < 1:
            slot = 1
        values = {
            "display_name": self.display_name.text().strip(),
            "username": self.username.text().strip(),
            "password": self.password.text(),
            "region": str(self.region.currentData() or "Korea"),
            "locale": str(self.locale.currentData() or "ko"),
            "server": self.server.currentText().strip(),
            "character_number": slot,
            "character_type": str(self.character_type.currentData() or "royal"),
            "purple_launcher_path": self.purple_path.text().strip(),
            "game_path": self.game_path.text().strip(),
        }
        try:
            if self.account is None:
                saved = Account.create(**values)
                self.store.add(saved)
            else:
                saved = Account(
                    account_id=self.account.account_id,
                    click_mode=self.account.click_mode,
                    **values,
                )
                self.store.update(saved)
            if self.profile is not None and self.profile.selected_account_id is None:
                self.profile.selected_account_id = saved.account_id
                save_profile(self.profile)
            self.accept()
        except Exception as exc:
            QMessageBox.warning(
                self, self.t.get("title", "Manmabot"), str(exc)
            )


class AccountsDialog(QDialog):
    """Full account list + New / Edit / Delete / Save."""

    def __init__(
        self,
        strings: dict[str, str],
        parent: QWidget | None = None,
        *,
        profile: Profile | None = None,
        language: str = "en",
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.t = strings
        self.profile = profile
        self.language = language
        self.on_changed = on_changed or (lambda: None)
        self.store = AccountStore()
        self._recovery_prompted = False
        self.setWindowTitle(self.t.get("manage_accounts", "Accounts"))
        self.resize(1180, 460)
        self.setMinimumSize(920, 320)
        self.setModal(True)

        self.region_ids = {
            self.t.get("region_korea", "Korea"): "Korea",
            self.t.get("region_china", "China"): "China",
        }
        self.locale_ids = {
            self.t.get("locale_korean", "Korean"): "ko",
            self.t.get("locale_simplified_chinese", "Simplified Chinese"): "zh-CN",
        }
        self.character_ids = {
            self.t.get("royal", "Royal"): "royal",
            self.t.get("knight", "Knight"): "knight",
            self.t.get("elf", "Elf"): "elf",
            self.t.get("mage", "Mage"): "mage",
        }

        root = QVBoxLayout(self)
        self.table = QTableWidget(0, len(_ACCOUNT_COLUMNS))
        self.table.setHorizontalHeaderLabels(
            [self.t.get(heading, heading) for _col, heading, _w in _ACCOUNT_COLUMNS]
        )
        self.table.verticalHeader().setVisible(False)
        configure_select_rows(self.table)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(lambda *_: self._edit_selected())
        for index, (_col, _heading, width) in enumerate(_ACCOUNT_COLUMNS):
            self.table.setColumnWidth(index, width)
        root.addWidget(self.table, stretch=1)

        row = QHBoxLayout()
        new_btn = QPushButton(self.t.get("new", "New"))
        edit_btn = QPushButton(self.t.get("edit_account", "Edit"))
        delete_btn = QPushButton(self.t.get("delete", "Delete"))
        new_btn.clicked.connect(lambda: self._edit_account(None))
        edit_btn.clicked.connect(self._edit_selected)
        delete_btn.clicked.connect(self._delete_selected)
        row.addWidget(new_btn)
        row.addWidget(edit_btn)
        row.addWidget(delete_btn)
        row.addStretch(1)
        save_btn = QPushButton(self.t.get("save", "Save"))
        mark_accent(save_btn)
        save_btn.clicked.connect(self._save_and_close)
        row.addWidget(save_btn)
        root.addLayout(row)

        self.reload()

    def reload(self) -> None:
        self.table.setRowCount(0)
        try:
            accounts = self.store.load()
        except AccountStoreError:
            if self._recovery_prompted:
                return
            self._recovery_prompted = True
            if QMessageBox.question(
                self,
                self.t.get("account_unlock_title", "Accounts locked"),
                self.t.get(
                    "account_unlock_reset",
                    "Reset inaccessible account store?",
                ),
            ) != QMessageBox.StandardButton.Yes:
                return
            try:
                backup = self.store.backup_and_reset_inaccessible()
                if self.profile is not None:
                    self.profile.selected_account_id = None
                    save_profile(self.profile)
                QMessageBox.information(
                    self,
                    self.t.get("account_unlock_title", "Accounts locked"),
                    self.t.get(
                        "account_unlock_reset_done",
                        "Backed up to {path}",
                    ).format(path=str(backup) if backup else ""),
                )
                accounts = self.store.load()
                self.on_changed()
            except Exception as exc:
                QMessageBox.warning(
                    self, self.t.get("title", "Manmabot"), str(exc)
                )
                return
        except Exception as exc:
            QMessageBox.warning(self, self.t.get("title", "Manmabot"), str(exc))
            return

        for account in accounts:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                account.display_name or account.username,
                account.server,
                str(account.character_number),
                account.username,
                "••••••" if account.password else "",
                _label_for(self.region_ids, account.region),
                _label_for(self.locale_ids, account.locale),
                _label_for(self.character_ids, account.character_type),
                account.purple_launcher_path or "",
                account.game_path or "",
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(str(text))
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, account.account_id)
                self.table.setItem(row, col, item)
        if self.table.rowCount() and not self.table.selectionModel().selectedRows():
            self.table.selectRow(0)

    def _selected_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole) or "") or None

    def _edit_account(self, account: Account | None) -> None:
        dialog = AccountEditorDialog(
            self,
            strings=self.t,
            language=self.language,
            store=self.store,
            account=account,
            profile=self.profile,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.reload()
            self.on_changed()

    def _edit_selected(self) -> None:
        account_id = self._selected_id()
        if not account_id:
            QMessageBox.information(
                self,
                self.t.get("title", "Manmabot"),
                self.t.get("select_account", "Select an account to edit."),
            )
            return
        try:
            account = self.store.get(account_id)
            if account is not None:
                self._edit_account(account)
        except Exception as exc:
            QMessageBox.warning(self, self.t.get("title", "Manmabot"), str(exc))

    def _delete_selected(self) -> None:
        account_id = self._selected_id()
        if not account_id:
            QMessageBox.information(
                self,
                self.t.get("title", "Manmabot"),
                self.t.get("select_account", "Select an account to edit."),
            )
            return
        try:
            self.store.delete(account_id)
            if self.profile is not None and self.profile.selected_account_id == account_id:
                self.profile.selected_account_id = None
                save_profile(self.profile)
            self.reload()
            self.on_changed()
        except Exception as exc:
            QMessageBox.warning(self, self.t.get("title", "Manmabot"), str(exc))

    def _save_and_close(self) -> None:
        try:
            self.store.save(self.store.load())
            self.on_changed()
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, self.t.get("title", "Manmabot"), str(exc))
