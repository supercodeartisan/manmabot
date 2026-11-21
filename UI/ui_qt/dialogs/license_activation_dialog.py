"""Customer license activation UI (OOB request / response — no cmd).

UI languages: Korean and Simplified Chinese only (no English).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from i18n.strings import detect_system_language, ui_language
from session.oob_activation import (
    REQUEST_PATH,
    apply_activation_response,
    create_activation_request,
)
from session.paths import USERDATA
from ui_qt.theme import tokens

# License window copy — ko / zh only.
_COPY: dict[str, dict[str, str]] = {
    "ko": {
        "title": "ZF — 라이선스",
        "heading": "라이선스 활성화",
        "hint": (
            "1) 판매자에게 받은 키를 입력하세요\n"
            "2) 요청 파일 만들기 → 그 파일을 판매자에게 보내세요\n"
            "3) 판매자가 보낸 응답 파일을 선택하세요\n"
            "완료 후 이 PC에서는 오프라인으로 사용할 수 있습니다."
        ),
        "language": "언어",
        "key_label": "라이선스 키",
        "btn_request": "요청 파일 만들기",
        "btn_open": "폴더 열기",
        "btn_copy": "경로 복사",
        "path_none": "요청 파일: (아직 없음)",
        "path_fmt": "요청 파일: {path}",
        "response_label": "판매자 응답",
        "btn_browse": "응답 파일 선택…",
        "paste_ph": "또는 MMB-RSP1.… 문자열을 붙여넣은 뒤 「붙여넣은 응답 적용」을 누르세요",
        "btn_paste": "붙여넣은 응답 적용",
        "btn_quit": "종료",
        "err_key": "올바른 라이선스 키(MMB-…)를 입력하세요.",
        "err_request": "요청 실패: {exc}",
        "ok_request": "요청 파일이 준비되었습니다. 판매자에게 보낸 뒤 응답을 선택하세요.",
        "err_folder": "폴더를 열 수 없습니다: {exc}",
        "err_no_request": "먼저 요청 파일을 만드세요.",
        "ok_copied": "요청 경로를 클립보드에 복사했습니다.",
        "err_apply": "적용 실패: {exc}",
        "msg_apply_title": "라이선스",
        "msg_apply_fail": "응답을 적용할 수 없습니다:\n{exc}",
        "ok_activated": "활성화되었습니다. ZF를 시작합니다…",
        "msg_ok_title": "라이선스",
        "msg_ok_body": "활성화 완료. 이제 이 PC에서 오프라인으로 사용할 수 있습니다.",
        "browse_title": "활성화 응답 파일 선택",
        "err_paste": "먼저 MMB-RSP1.… 응답을 붙여넣으세요.",
        "filter_json": "JSON (*.json);;모든 파일 (*.*)",
    },
    "zh": {
        "title": "ZF — 许可证",
        "heading": "许可证激活",
        "hint": (
            "1) 输入卖家提供的密钥\n"
            "2) 创建请求文件 → 发给卖家\n"
            "3) 选择卖家发回的响应文件\n"
            "完成后可在本机离线使用。"
        ),
        "language": "语言",
        "key_label": "许可证密钥",
        "btn_request": "创建请求文件",
        "btn_open": "打开文件夹",
        "btn_copy": "复制路径",
        "path_none": "请求文件：（尚未创建）",
        "path_fmt": "请求文件：{path}",
        "response_label": "卖家响应",
        "btn_browse": "选择响应文件…",
        "paste_ph": "或粘贴 MMB-RSP1.… 字符串后点击「应用粘贴的响应」",
        "btn_paste": "应用粘贴的响应",
        "btn_quit": "退出",
        "err_key": "请输入有效的许可证密钥（MMB-…）。",
        "err_request": "创建请求失败：{exc}",
        "ok_request": "请求文件已就绪。请发给卖家，然后选择响应文件。",
        "err_folder": "无法打开文件夹：{exc}",
        "err_no_request": "请先创建请求文件。",
        "ok_copied": "已复制请求路径到剪贴板。",
        "err_apply": "应用失败：{exc}",
        "msg_apply_title": "许可证",
        "msg_apply_fail": "无法应用响应：\n{exc}",
        "ok_activated": "已激活。正在启动 ZF…",
        "msg_ok_title": "许可证",
        "msg_ok_body": "激活成功。此后可在本机离线使用。",
        "browse_title": "选择激活响应文件",
        "err_paste": "请先粘贴 MMB-RSP1.… 响应。",
        "filter_json": "JSON (*.json);;所有文件 (*.*)",
    },
}


def _resolve_language() -> str:
    try:
        from settings.profile import load_profile

        return ui_language(load_profile().language)
    except Exception:
        return detect_system_language()


class LicenseActivationDialog(QDialog):
    """Modal: enter key → create request → apply seller response (ko/zh)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        language: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setMinimumWidth(520)
        self._activated = False
        self._last_request: Path | None = None
        self._lang = ui_language(language or _resolve_language())
        self._t = _COPY[self._lang]

        root = QVBoxLayout(self)

        lang_row = QHBoxLayout()
        self.lang_caption = QLabel()
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("한국어", "ko")
        self.lang_combo.addItem("简体中文", "zh")
        self.lang_combo.setCurrentIndex(0 if self._lang == "ko" else 1)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_row.addWidget(self.lang_caption)
        lang_row.addWidget(self.lang_combo)
        lang_row.addStretch(1)
        root.addLayout(lang_row)

        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(self.title_label)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        root.addWidget(self.hint_label)

        self.key_caption = QLabel()
        root.addWidget(self.key_caption)
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("MMB-…")
        self.key_edit.setClearButtonEnabled(True)
        root.addWidget(self.key_edit)

        row1 = QHBoxLayout()
        self.btn_request = QPushButton()
        self.btn_request.clicked.connect(self._on_create_request)
        self.btn_open = QPushButton()
        self.btn_open.clicked.connect(self._on_open_folder)
        self.btn_copy = QPushButton()
        self.btn_copy.clicked.connect(self._on_copy_path)
        row1.addWidget(self.btn_request)
        row1.addWidget(self.btn_open)
        row1.addWidget(self.btn_copy)
        root.addLayout(row1)

        self.path_label = QLabel()
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self.path_label)

        self.response_caption = QLabel()
        root.addWidget(self.response_caption)
        row2 = QHBoxLayout()
        self.btn_browse = QPushButton()
        self.btn_browse.clicked.connect(self._on_browse_response)
        row2.addWidget(self.btn_browse)
        row2.addStretch(1)
        root.addLayout(row2)

        self.paste = QTextEdit()
        self.paste.setFixedHeight(72)
        root.addWidget(self.paste)
        self.btn_paste = QPushButton()
        self.btn_paste.clicked.connect(self._on_apply_paste)
        root.addWidget(self.btn_paste)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        root.addWidget(self.status)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_quit = QPushButton()
        self.btn_quit.clicked.connect(self.reject)
        bottom.addWidget(self.btn_quit)
        root.addLayout(bottom)

        if REQUEST_PATH.is_file():
            self._last_request = REQUEST_PATH

        self._apply_strings()

    def _tr(self, key: str, **kwargs: object) -> str:
        text = self._t.get(key, key)
        if kwargs:
            return text.format(**kwargs)
        return text

    def _apply_strings(self) -> None:
        self._t = _COPY[self._lang]
        self.setWindowTitle(self._tr("title"))
        self.lang_caption.setText(self._tr("language"))
        self.title_label.setText(self._tr("heading"))
        self.hint_label.setText(self._tr("hint"))
        self.key_caption.setText(self._tr("key_label"))
        self.btn_request.setText(self._tr("btn_request"))
        self.btn_open.setText(self._tr("btn_open"))
        self.btn_copy.setText(self._tr("btn_copy"))
        if self._last_request and self._last_request.is_file():
            self.path_label.setText(self._tr("path_fmt", path=str(self._last_request)))
        else:
            self.path_label.setText(self._tr("path_none"))
        self.response_caption.setText(self._tr("response_label"))
        self.btn_browse.setText(self._tr("btn_browse"))
        self.paste.setPlaceholderText(self._tr("paste_ph"))
        self.btn_paste.setText(self._tr("btn_paste"))
        self.btn_quit.setText(self._tr("btn_quit"))

    def _on_language_changed(self, _index: int) -> None:
        data = self.lang_combo.currentData()
        self._lang = ui_language(str(data) if data else "ko")
        self._apply_strings()

    @property
    def activated(self) -> bool:
        return self._activated

    def _set_status(self, text: str, *, error: bool = False) -> None:
        color = "#b91c1c" if error else tokens.TEXT_MUTED
        self.status.setStyleSheet(f"color: {color};")
        self.status.setText(text)

    def _on_create_request(self) -> None:
        key = self.key_edit.text().strip()
        if not key.startswith("MMB-"):
            self._set_status(self._tr("err_key"), error=True)
            return
        try:
            info = create_activation_request(license_key=key)
        except Exception as exc:
            self._set_status(self._tr("err_request", exc=exc), error=True)
            return
        self._last_request = Path(info["path"])
        self.path_label.setText(self._tr("path_fmt", path=info["path"]))
        self._set_status(self._tr("ok_request"))
        try:
            QGuiApplication.clipboard().setText(str(info["path"]))
        except Exception:
            pass

    def _on_open_folder(self) -> None:
        target = self._last_request.parent if self._last_request else (USERDATA / "license")
        target.mkdir(parents=True, exist_ok=True)
        try:
            import os

            os.startfile(str(target))  # noqa: S606 — Windows explorer
        except Exception as exc:
            self._set_status(self._tr("err_folder", exc=exc), error=True)

    def _on_copy_path(self) -> None:
        path = self._last_request or REQUEST_PATH
        if not path.is_file():
            self._set_status(self._tr("err_no_request"), error=True)
            return
        QGuiApplication.clipboard().setText(str(path))
        self._set_status(self._tr("ok_copied"))

    def _apply_response(self, path_or_wire: str) -> None:
        try:
            apply_activation_response(path_or_wire)
        except Exception as exc:
            self._set_status(self._tr("err_apply", exc=exc), error=True)
            QMessageBox.warning(
                self,
                self._tr("msg_apply_title"),
                self._tr("msg_apply_fail", exc=exc),
            )
            return
        self._activated = True
        self._set_status(self._tr("ok_activated"))
        QMessageBox.information(
            self,
            self._tr("msg_ok_title"),
            self._tr("msg_ok_body"),
        )
        self.accept()

    def _on_browse_response(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("browse_title"),
            str(USERDATA),
            self._tr("filter_json"),
        )
        if path:
            self._apply_response(path)

    def _on_apply_paste(self) -> None:
        text = self.paste.toPlainText().strip()
        if not text:
            self._set_status(self._tr("err_paste"), error=True)
            return
        self._apply_response(text)


def run_license_activation_dialog() -> bool:
    """
    Show the license dialog. Returns True if ticket/envelope are ready afterwards.
    Creates a QApplication if needed (before the main schedule window).
    """
    from session.licensed_runtime import ENVELOPE_PATH, TICKET_PATH

    language = _resolve_language()
    app = QApplication.instance()
    created = False
    if app is None:
        app = QApplication(sys.argv)
        created = True
        try:
            from ui_qt.theme import apply_classic_qt_theme

            apply_classic_qt_theme(app, language)
        except Exception:
            pass

    dlg = LicenseActivationDialog(language=language)
    result = dlg.exec()
    ok = dlg.activated and TICKET_PATH.is_file() and ENVELOPE_PATH.is_file()
    _ = created, result
    return ok
