# -*- coding: utf-8 -*-
"""
control.test_input — 실제 보드 입력 주입 진단 (사용자 실행용)

Pico 를 USB 로 꽂은 '직후'에 실행하세요. (CDC 데이터가 오래 켜두면 불안정할 수 있음)
  python -m control.test_input COM5

  * 마우스 이동/클릭과 키보드 타이핑을 메모장에서 확인하고 결과를 출력한다.
"""

import argparse
import ctypes
import subprocess
import sys
import time


def cursor_pos():
    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    p = P()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
    return (p.x, p.y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", help="지령(data) 포트, 예: COM5")
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    sys.path.insert(0, ".")
    from control import ControlClient, SerialTransport
    from control.feedback import FeedbackController, local_cursor

    u = ctypes.windll.user32

    # 메모장 실행 + 포커스
    subprocess.Popen(["notepad.exe"])
    time.sleep(2.0)
    hwnd = u.FindWindowW("Notepad", None)
    u.ShowWindow(hwnd, 3)
    time.sleep(0.3)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    edit = u.FindWindowExW(hwnd, 0, "Edit", None)
    print("notepad:", hwnd, "edit:", edit, "fg:", u.GetForegroundWindow() == hwnd)

    c = ControlClient(SerialTransport(args.port, args.baud))
    try:
        # --- 마우스 ---
        a = cursor_pos()
        c.move_rel(120, 0)
        time.sleep(0.4)
        b = cursor_pos()
        print("[MOUSE] %s -> %s  %s" % (a, b, "OK" if a != b else "FAIL"))

        # --- 마우스 클릭으로 편집영역 포커스 ---
        fc = FeedbackController(c, local_cursor(), settle=0.012)
        ok, pos, n = fc.move_abs(500, 300, tolerance=4, max_iter=20)
        time.sleep(0.2)
        c.click(1, 40)
        time.sleep(0.4)

        # --- 키보드 ---
        c.type_text("hello 123")
        time.sleep(1.0)
        buf = ctypes.create_unicode_buffer(2048)
        u.GetWindowTextW(edit, buf, 2048)
        print("[KEYBOARD] notepad text: %r  %s"
              % (buf.value, "OK" if buf.value else "FAIL"))
    finally:
        try:
            c.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
