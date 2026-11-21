"""Customer license activation UI (OOB request / response — no cmd).

UI languages: Korean and Simplified Chinese only (no English).
Visual style matches the main ZF schedule console (classic Qt theme).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
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
from ui_qt.theme import apply_classic_qt_theme, font_roles_for_window, mark_accent, tokens

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
        "step_key": "1. 키 · 요청",
        "step_response": "2. 응답 적용",
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
        "step_key": "1. 密钥 · 请求",
        "step_response": "2. 应用响应",
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


def _chrome_card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("chrome")
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    return frame


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
        self.setMinimumSize(560, 520)
        self.resize(600, 560)
        self._activated = False
        self._last_request: Path | None = None
        self._lang = ui_language(language or _resolve_language())
        self._t = _COPY[self._lang]

        try:
            from settings.map_previews import brand_icon_path

            logo = brand_icon_path()
            if logo is not None:
                self.setWindowIcon(QIcon(str(logo)))
        except Exception:
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(10)

        # --- Header (schedule-console style) ---
        header = _chrome_card()
        header_lay = QVBoxLayout(header)
        header_lay.setContentsMargins(12, 10, 12, 10)
        header_lay.setSpacing(6)

        top = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {tokens.TEXT};"
        )
        top.addWidget(self.title_label, stretch=1)
        self.lang_caption = QLabel()
        self.lang_caption.setObjectName("muted")
        self.lang_combo = QComboBox()
        self.lang_combo.setMinimumWidth(110)
        self.lang_combo.addItem("한국어", "ko")
        self.lang_combo.addItem("简体中文", "zh")
        self.lang_combo.setCurrentIndex(0 if self._lang == "ko" else 1)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        top.addWidget(self.lang_caption)
        top.addWidget(self.lang_combo)
        header_lay.addLayout(top)

        self.hint_label = QLabel()
        self.hint_label.setObjectName("muted")
        self.hint_label.setWordWrap(True)
        header_lay.addWidget(self.hint_label)
        root.addWidget(header)

        # --- Step 1: key + request ---
        key_card = _chrome_card()
        key_lay = QVBoxLayout(key_card)
        key_lay.setContentsMargins(12, 10, 12, 10)
        key_lay.setSpacing(8)
        self.step_key_label = QLabel()
        self.step_key_label.setStyleSheet(
            f"font-weight: 700; color: {tokens.ACCENT_TEXT};"
        )
        key_lay.addWidget(self.step_key_label)
        self.key_caption = QLabel()
        key_lay.addWidget(self.key_caption)
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("MMB-…")
        self.key_edit.setClearButtonEnabled(True)
        key_lay.addWidget(self.key_edit)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.btn_request = QPushButton()
        mark_accent(self.btn_request)
        self.btn_request.clicked.connect(self._on_create_request)
        self.btn_open = QPushButton()
        self.btn_open.clicked.connect(self._on_open_folder)
        self.btn_copy = QPushButton()
        self.btn_copy.clicked.connect(self._on_copy_path)
        row1.addWidget(self.btn_request)
        row1.addWidget(self.btn_open)
        row1.addWidget(self.btn_copy)
        row1.addStretch(1)
        key_lay.addLayout(row1)

        self.path_label = QLabel()
        self.path_label.setObjectName("muted")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        key_lay.addWidget(self.path_label)
        root.addWidget(key_card)

        # --- Step 2: seller response ---
        resp_card = _chrome_card()
        resp_lay = QVBoxLayout(resp_card)
        resp_lay.setContentsMargins(12, 10, 12, 10)
        resp_lay.setSpacing(8)
        self.step_response_label = QLabel()
        self.step_response_label.setStyleSheet(
            f"font-weight: 700; color: {tokens.ACCENT_TEXT};"
        )
        resp_lay.addWidget(self.step_response_label)
        self.response_caption = QLabel()
        resp_lay.addWidget(self.response_caption)

        row2 = QHBoxLayout()
        self.btn_browse = QPushButton()
        mark_accent(self.btn_browse)
        self.btn_browse.clicked.connect(self._on_browse_response)
        row2.addWidget(self.btn_browse)
        row2.addStretch(1)
        resp_lay.addLayout(row2)

        self.paste = QTextEdit()
        self.paste.setFixedHeight(72)
        resp_lay.addWidget(self.paste)
        self.btn_paste = QPushButton()
        mark_accent(self.btn_paste)
        self.btn_paste.clicked.connect(self._on_apply_paste)
        resp_lay.addWidget(self.btn_paste)
        root.addWidget(resp_card)

        root.addStretch(1)

        # --- Status strip + quit (console parity) ---
        strip = QFrame()
        strip.setObjectName("statusStrip")
        strip_lay = QHBoxLayout(strip)
        strip_lay.setContentsMargins(8, 4, 8, 4)
        strip_lay.setSpacing(8)
        self.status = QLabel("")
        self.status.setObjectName("statusChip")
        self.status.setWordWrap(True)
        strip_lay.addWidget(self.status, stretch=1)
        self.btn_quit = QPushButton()
        self.btn_quit.clicked.connect(self.reject)
        strip_lay.addWidget(self.btn_quit)
        root.addWidget(strip)

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
        self.step_key_label.setText(self._tr("step_key"))
        self.step_response_label.setText(self._tr("step_response"))
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
        app = QApplication.instance()
        if app is not None:
            body, section, _title = font_roles_for_window(600, 560)
            apply_classic_qt_theme(
                app,
                self._lang,
                self,
                font_size=body,
                section_size=section,
                restyle=True,
            )

    @property
    def activated(self) -> bool:
        return self._activated

    def _set_status(self, text: str, *, error: bool = False) -> None:
        if error:
            bg, fg = "#fde8e8", "#b91c1c"
        else:
            bg, fg = tokens.STRIP["off"]
        self.status.setStyleSheet(
            f"background: {bg}; color: {fg}; padding: 3px 10px; border: none;"
        )
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

    body, section, _title = font_roles_for_window(600, 560)
    try:
        apply_classic_qt_theme(app, language, font_size=body, section_size=section)
    except Exception:
        pass

    dlg = LicenseActivationDialog(language=language)
    try:
        apply_classic_qt_theme(
            app, language, dlg, font_size=body, section_size=section, restyle=False
        )
    except Exception:
        pass
    result = dlg.exec()
    ok = dlg.activated and TICKET_PATH.is_file() and ENVELOPE_PATH.is_file()
    _ = created, result
    return ok
