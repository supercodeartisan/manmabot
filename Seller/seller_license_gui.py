"""Seller license console — create keys, fulfill OOB requests, reset (no cmd).

Seller machine only. Requires SellerData/. Never ship this tool to customers.
Responsive layout: scroll + splitter + expanding list/detail panes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Product root = parents[1] (Seller/ → product)
_PRODUCT = Path(__file__).resolve().parents[1]
for p in (_PRODUCT / "Engine", _PRODUCT / "UI", _PRODUCT):
    text = str(p)
    if text not in sys.path:
        sys.path.insert(0, text)


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSplitter,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )

    from crypto.seller_cli import fulfill_ops, license_ops, signing
    from crypto.seller_cli.store import SellerStore, default_seller_root

    def _wrap_buttons(*buttons: QPushButton) -> QWidget:
        """Horizontal button row that stays usable when the window shrinks."""
        host = QWidget()
        lay = QHBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for btn in buttons:
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            lay.addWidget(btn)
        lay.addStretch(1)
        return host

    class SellerLicenseWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("ZF — Seller License Tool")
            self.setMinimumSize(640, 520)
            self.resize(960, 720)
            self.store = SellerStore(default_seller_root())
            self._last_key = ""
            self._last_response: Path | None = None

            outer = QVBoxLayout(self)
            outer.setContentsMargins(10, 10, 10, 10)
            outer.setSpacing(8)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            outer.addWidget(scroll, stretch=1)

            body = QWidget()
            scroll.setWidget(body)
            root = QVBoxLayout(body)
            root.setContentsMargins(4, 4, 4, 4)
            root.setSpacing(12)

            info = QLabel(
                f"<b>SellerData:</b> {self.store.root}<br>"
                "Customer never receives this folder. "
                "Create → send key · Fulfill → send response JSON only."
            )
            info.setWordWrap(True)
            info.setTextFormat(Qt.TextFormat.RichText)
            info.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
            root.addWidget(info)

            # --- 1) Create ---
            create_box = QGroupBox("1) Create license key for a customer")
            create_box.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
            )
            cl = QVBoxLayout(create_box)
            cl.setSpacing(8)

            form = QFormLayout()
            form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
            )
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setLabelAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            cek_row = QWidget()
            cek_lay = QHBoxLayout(cek_row)
            cek_lay.setContentsMargins(0, 0, 0, 0)
            self.cek_combo = QComboBox()
            self.cek_combo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self.btn_refresh_cek = QPushButton("Refresh")
            self.btn_refresh_cek.clicked.connect(self._reload_ceks)
            cek_lay.addWidget(self.cek_combo, stretch=1)
            cek_lay.addWidget(self.btn_refresh_cek)
            form.addRow("CEK epoch", cek_row)

            self.label_edit = QLineEdit()
            self.label_edit.setPlaceholderText("e.g. discord:alice / game:CharName")
            form.addRow("Account / username", self.label_edit)

            self.note_edit = QLineEdit()
            self.note_edit.setPlaceholderText("optional private note")
            form.addRow("Seller note", self.note_edit)
            cl.addLayout(form)

            self.btn_create = QPushButton("Create license key")
            self.btn_create.setMinimumHeight(36)
            self.btn_create.clicked.connect(self._on_create)
            cl.addWidget(self.btn_create)

            key_row = QWidget()
            key_lay = QHBoxLayout(key_row)
            key_lay.setContentsMargins(0, 0, 0, 0)
            self.key_out = QLineEdit()
            self.key_out.setReadOnly(True)
            self.key_out.setPlaceholderText("New MMB-… key appears here")
            self.key_out.setMinimumWidth(120)
            self.btn_copy_key = QPushButton("Copy key")
            self.btn_copy_key.clicked.connect(self._copy_key)
            key_lay.addWidget(self.key_out, stretch=1)
            key_lay.addWidget(self.btn_copy_key)
            cl.addWidget(key_row)

            self.meta_out = QLabel("")
            self.meta_out.setWordWrap(True)
            self.meta_out.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            cl.addWidget(self.meta_out)
            root.addWidget(create_box)

            # --- 2) Licenses (splitter: list | detail) ---
            lic_box = QGroupBox("2) Licenses (inspect / reset / rename)")
            lic_box.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            ll = QVBoxLayout(lic_box)
            ll.setSpacing(8)

            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.setChildrenCollapsible(False)
            splitter.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )

            left = QWidget()
            left_lay = QVBoxLayout(left)
            left_lay.setContentsMargins(0, 0, 0, 0)
            left_lay.setSpacing(6)
            self.lic_list = QListWidget()
            self.lic_list.setMinimumWidth(220)
            self.lic_list.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self.lic_list.currentItemChanged.connect(self._on_list_selection)
            left_lay.addWidget(self.lic_list, stretch=1)

            label_row = QWidget()
            label_lay = QHBoxLayout(label_row)
            label_lay.setContentsMargins(0, 0, 0, 0)
            self.edit_label = QLineEdit()
            self.edit_label.setPlaceholderText("account/username for selected license")
            self.btn_save_label = QPushButton("Save label")
            self.btn_save_label.clicked.connect(self._on_save_label)
            label_lay.addWidget(self.edit_label, stretch=1)
            label_lay.addWidget(self.btn_save_label)
            left_lay.addWidget(label_row)

            left_lay.addWidget(
                _wrap_buttons(
                    self._mk_btn("Reload list", self._reload_licenses),
                    self._mk_btn("Inspect", self._on_inspect),
                    self._mk_btn("Reset binding (PC change)", self._on_reset),
                    self._mk_btn("Export CSV", self._on_export_csv),
                )
            )
            splitter.addWidget(left)

            right = QWidget()
            right_lay = QVBoxLayout(right)
            right_lay.setContentsMargins(0, 0, 0, 0)
            right_lay.addWidget(QLabel("Inspect / details"))
            self.inspect_view = QTextEdit()
            self.inspect_view.setReadOnly(True)
            self.inspect_view.setMinimumWidth(200)
            self.inspect_view.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self.inspect_view.setPlaceholderText(
                "Select a license and click Inspect (or double-click)."
            )
            right_lay.addWidget(self.inspect_view, stretch=1)
            splitter.addWidget(right)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 2)
            splitter.setSizes([560, 360])

            ll.addWidget(splitter, stretch=1)
            root.addWidget(lic_box, stretch=1)

            self.lic_list.itemDoubleClicked.connect(lambda _i: self._on_inspect())

            # --- 3) Fulfill ---
            ful_box = QGroupBox("3) Fulfill customer activation request")
            ful_box.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
            )
            fl = QVBoxLayout(ful_box)
            fl.setSpacing(8)
            ful_hint = QLabel(
                "Select the activation_request.json the customer sent, "
                "then send them the response file only."
            )
            ful_hint.setWordWrap(True)
            fl.addWidget(ful_hint)
            fl.addWidget(
                _wrap_buttons(
                    self._mk_btn("Select request file…", self._on_fulfill),
                    self._mk_btn("Open response folder", self._open_response_folder),
                    self._mk_btn("Copy response path", self._copy_response_path),
                )
            )
            self.resp_label = QLabel("Response: (none yet)")
            self.resp_label.setWordWrap(True)
            self.resp_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            fl.addWidget(self.resp_label)
            root.addWidget(ful_box)

            # Sticky status under scroll
            self.status = QLabel("")
            self.status.setWordWrap(True)
            self.status.setMinimumHeight(28)
            outer.addWidget(self.status)

            self._reload_ceks()
            self._reload_licenses()
            self._show_signing()

        @staticmethod
        def _mk_btn(text: str, slot) -> QPushButton:
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            return btn

        def _on_list_selection(self, current, _previous) -> None:
            if current is None:
                return
            label = current.data(Qt.ItemDataRole.UserRole + 1) or ""
            self.edit_label.setText(str(label))

        def closeEvent(self, event) -> None:  # noqa: N802
            try:
                self.store.close()
            except Exception:
                pass
            super().closeEvent(event)

        def _set_status(self, text: str, *, error: bool = False) -> None:
            self.status.setStyleSheet("color: #b91c1c;" if error else "")
            self.status.setText(text)

        def _show_signing(self) -> None:
            try:
                info = signing.inspect_signing(self.store)
                self._set_status(
                    f"Signing kid: {info.get('current_kid')} | "
                    f"product: {self.store.config().get('product_id')}"
                )
            except Exception as exc:
                self._set_status(f"Signing: {exc}", error=True)

        def _reload_ceks(self) -> None:
            self.cek_combo.clear()
            rows = self.store.db().conn.execute(
                "SELECT cek_id, product_id, created_at FROM cek_vault ORDER BY created_at DESC"
            ).fetchall()
            if not rows:
                self.cek_combo.addItem("(no CEK — run pack build / cek create first)", "")
                return
            for row in rows:
                label = f"{row['cek_id']}  ({row['created_at']})"
                self.cek_combo.addItem(label, row["cek_id"])

        def _reload_licenses(self) -> None:
            self.lic_list.clear()
            rows = self.store.db().conn.execute(
                """
                SELECT l.license_id, l.status, l.cek_id, l.created_at,
                       l.customer_label, b.device_id
                FROM licenses l
                LEFT JOIN bindings b ON b.license_id = l.license_id
                ORDER BY l.created_at DESC
                """
            ).fetchall()
            for row in rows:
                bound = "bound" if row["device_id"] else "free"
                who = (row["customer_label"] or "").strip() or "(no label)"
                text = (
                    f"{who}  |  {row['license_id'][:8]}…  {row['status']}  {bound}"
                )
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, row["license_id"])
                item.setData(Qt.ItemDataRole.UserRole + 1, row["customer_label"] or "")
                self.lic_list.addItem(item)

        def _selected_license_id(self) -> str | None:
            item = self.lic_list.currentItem()
            if item is None:
                return None
            return item.data(Qt.ItemDataRole.UserRole)

        def _on_create(self) -> None:
            from crypto.seller_cli import artifact as artifact_ops

            cek_id = self.cek_combo.currentData()
            if not cek_id:
                self._set_status("Select a CEK epoch first.", error=True)
                return
            label = self.label_edit.text().strip()
            note = self.note_edit.text().strip()
            if not label:
                self._set_status(
                    "Enter Account / username before creating "
                    "(so you can find this key later).",
                    error=True,
                )
                return
            try:
                info = license_ops.create_license(
                    self.store,
                    cek_id=cek_id,
                    customer_label=label,
                    seller_note=note,
                )
                artifact_ops.generate_artifact(
                    self.store,
                    license_id=info["license_id"],
                    license_key=info["license_key"],
                )
            except Exception as exc:
                self._set_status(f"Create failed: {exc}", error=True)
                QMessageBox.warning(self, "Create", str(exc))
                return
            self._last_key = info["license_key"]
            self.key_out.setText(self._last_key)
            self.meta_out.setText(
                f"label={label}  license_id={info['license_id']}  "
                f"artifact=SellerData/artifacts/{info['license_id']}.json"
            )
            try:
                QGuiApplication.clipboard().setText(self._last_key)
            except Exception:
                pass
            self._reload_licenses()
            self._set_status(
                f"License for [{label}] created. Key copied — send to that customer only."
            )

        def _copy_key(self) -> None:
            key = self.key_out.text().strip() or self._last_key
            if not key:
                self._set_status("No key to copy.", error=True)
                return
            QGuiApplication.clipboard().setText(key)
            self._set_status("License key copied.")

        def _on_save_label(self) -> None:
            lid = self._selected_license_id()
            if not lid:
                self._set_status("Select a license in the list.", error=True)
                return
            label = self.edit_label.text().strip()
            try:
                info = license_ops.set_customer_label(
                    self.store, lid, customer_label=label
                )
            except Exception as exc:
                self._set_status(str(exc), error=True)
                return
            self.inspect_view.setPlainText(json.dumps(info, indent=2, sort_keys=True))
            self._reload_licenses()
            self._set_status(f"Label saved: {label or '(cleared)'}")

        def _on_inspect(self) -> None:
            lid = self._selected_license_id()
            if not lid:
                self._set_status("Select a license in the list.", error=True)
                return
            try:
                info = license_ops.inspect_license(self.store, lid)
            except Exception as exc:
                self._set_status(str(exc), error=True)
                return
            self.edit_label.setText(info.get("customer_label") or "")
            art = self.store.root / "artifacts" / f"{lid}.json"
            extra = ""
            if art.is_file():
                try:
                    blob = json.loads(art.read_text(encoding="utf-8"))
                    extra = f"\n\n# artifact key on disk: {blob.get('license_key', '')}"
                except Exception:
                    extra = f"\n\n# artifact file: {art}"
            self.inspect_view.setPlainText(
                json.dumps(info, indent=2, sort_keys=True) + extra
            )

        def _on_export_csv(self) -> None:
            import csv

            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export license ledger CSV",
                str(self.store.root / "license_ledger.csv"),
                "CSV (*.csv)",
            )
            if not path:
                return
            rows = self.store.db().conn.execute(
                """
                SELECT l.customer_label, l.seller_note, l.license_id, l.status,
                       l.cek_id, l.created_at, b.device_id, b.bound_at
                FROM licenses l
                LEFT JOIN bindings b ON b.license_id = l.license_id
                ORDER BY l.created_at DESC
                """
            ).fetchall()
            with open(path, "w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(
                    [
                        "customer_label",
                        "seller_note",
                        "license_id",
                        "status",
                        "bound",
                        "cek_id",
                        "created_at",
                        "bound_at",
                        "artifact_key",
                    ]
                )
                for row in rows:
                    art = self.store.root / "artifacts" / f"{row['license_id']}.json"
                    key = ""
                    if art.is_file():
                        try:
                            key = json.loads(art.read_text(encoding="utf-8")).get(
                                "license_key", ""
                            )
                        except Exception:
                            key = ""
                    w.writerow(
                        [
                            row["customer_label"] or "",
                            row["seller_note"] or "",
                            row["license_id"],
                            row["status"],
                            "yes" if row["device_id"] else "no",
                            row["cek_id"],
                            row["created_at"],
                            row["bound_at"] or "",
                            key,
                        ]
                    )
            self._set_status(f"Exported ledger: {path}")
            QMessageBox.information(self, "Export", f"Saved:\n{path}")

        def _on_reset(self) -> None:
            lid = self._selected_license_id()
            if not lid:
                self._set_status("Select a license in the list.", error=True)
                return
            ok = QMessageBox.question(
                self,
                "Reset binding",
                f"Clear device binding for\n{lid}\n\n"
                "Customer must create a NEW activation request afterwards.",
            )
            if ok != QMessageBox.StandardButton.Yes:
                return
            try:
                info = license_ops.reset_license(
                    self.store, lid, reason="seller-ui", admin_id=os.getlogin()
                )
            except Exception as exc:
                self._set_status(f"Reset failed: {exc}", error=True)
                QMessageBox.warning(self, "Reset", str(exc))
                return
            self.inspect_view.setPlainText(json.dumps(info, indent=2, sort_keys=True))
            self._reload_licenses()
            self._set_status("Binding reset. Ask customer for a new request file.")

        def _on_fulfill(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Customer activation_request.json",
                str(Path.home()),
                "JSON (*.json);;All (*.*)",
            )
            if not path:
                return
            try:
                result = fulfill_ops.fulfill(self.store, path)
            except Exception as exc:
                self._set_status(f"Fulfill failed: {exc}", error=True)
                QMessageBox.warning(self, "Fulfill", str(exc))
                return
            self._last_response = Path(result["path"])
            self.resp_label.setText(f"Response: {result['path']}")
            try:
                QGuiApplication.clipboard().setText(str(self._last_response))
            except Exception:
                pass
            self._reload_licenses()
            self._set_status(
                "Fulfill OK. Send the response JSON to the customer (not SellerData)."
            )
            QMessageBox.information(
                self,
                "Fulfill",
                f"Response written:\n{result['path']}\n\n"
                "Send this file to the customer.",
            )

        def _open_response_folder(self) -> None:
            folder = (
                self._last_response.parent
                if self._last_response
                else self.store.root / "artifacts"
            )
            folder.mkdir(parents=True, exist_ok=True)
            try:
                os.startfile(str(folder))  # noqa: S606
            except Exception as exc:
                self._set_status(str(exc), error=True)

        def _copy_response_path(self) -> None:
            if not self._last_response or not self._last_response.is_file():
                self._set_status("No response file yet.", error=True)
                return
            QGuiApplication.clipboard().setText(str(self._last_response))
            self._set_status("Response path copied.")

    app = QApplication.instance() or QApplication(sys.argv)
    try:
        from ui_qt.theme import apply_classic_qt_theme

        apply_classic_qt_theme(app, "en")
    except Exception:
        pass
    win = SellerLicenseWindow()
    win.show()
    return int(app.exec())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, str(exc)[:2000], "Seller License Tool", 0x10)
        except Exception:
            pass
        raise SystemExit(1)
