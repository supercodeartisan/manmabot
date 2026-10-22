# -*- coding: utf-8 -*-
"""
control.feedback — 커서 위치 피드백으로 절대좌표 정확도를 '보장'하는 폐루프 (1방안)

배경
  표준 마우스는 상대이동만 가능해서, 절대좌표 지령을 줘도 OS 가속/외부개입으로
  목표에 정확히 도달하지 못할 수 있다. -> 매 이동마다 '실제 커서 위치'를 읽어
  (목표 - 실제) 델타를 다시 보내 오차를 0 으로 수렴시킨다.

구성
  CursorReader   : 커서 위치를 읽는 추상화
      WindowsCursor / X11Cursor / NullCursor / RemoteCursor
  TargetAgent    : 보드가 '다른 대상 PC'에 꽂힌 경우, 그 대상에서 위치를 보고
  FeedbackController : ControlClient + CursorReader 를 묶어 정확 이동 제공

결합성
  * CursorReader / ControlClient 둘 다 주입식 -> 임의 파이프라인에 결합
"""

import os
import socket
import subprocess
import sys
import threading
import time


# ----------------------------------------------------------- 커서 위치 읽기
class CursorReader(object):
    def position(self):
        raise NotImplementedError


class NullCursor(CursorReader):
    """테스트/시뮬레이션용. pos 를 직접 설정."""
    def __init__(self, pos=(0, 0)):
        self.pos = tuple(pos)

    def position(self):
        return self.pos


class WindowsCursor(CursorReader):
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        self._POINT = wintypes.POINT
        self._user32 = ctypes.windll.user32
        self._user32.SetProcessDPIAware()

    def position(self):
        p = self._POINT()
        self._user32.GetCursorPos(self._ctypes.byref(p))
        return (int(p.x), int(p.y))


class X11Cursor(CursorReader):
    """xdotool 필요:  sudo apt install xdotool"""
    def __init__(self, tool="xdotool"):
        self.tool = tool

    def position(self):
        out = subprocess.check_output([self.tool, "getmouselocation", "--shell"])
        vals = {}
        for line in out.decode().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                vals[k] = v
        return (int(vals["X"]), int(vals["Y"]))


class RemoteCursor(CursorReader):
    """다른 대상 PC 의 TargetAgent 에게 커서 위치를 물어본다."""
    def __init__(self, host, port=9001, timeout=3.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._f = self.sock.makefile("rb")

    def position(self):
        self.sock.sendall(b"P\n")
        line = self._f.readline().decode().strip()
        x, y = line.split(",")
        return (int(x), int(y))

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def local_cursor():
    """현재 OS 의 커서 리더를 자동 선택."""
    if sys.platform.startswith("win"):
        return WindowsCursor()
    if sys.platform == "darwin":
        raise RuntimeError("macOS 커서 읽기는 미지원입니다. RemoteCursor 또는 NullCursor 사용")
    if os.environ.get("DISPLAY"):
        return X11Cursor()
    raise RuntimeError("커서를 읽을 수 없습니다(Wayland/헤드리스). RemoteCursor 사용 권장")


# ----------------------------------------------------------- 대상 측 에이전트
class TargetAgent(object):
    """보드가 꽂힌 '대상 PC'에서 실행. 커서 위치를 요청에 응답한다.
       프로토콜: b'P\\n' -> b'x,y\\n'  (극도로 단순/저지연)."""
    def __init__(self, reader=None, host="0.0.0.0", port=9001):
        self.reader = reader or local_cursor()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(4)
        self._stop = False

    def serve_forever(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            f = conn.makefile("rb")
            while not self._stop:
                line = f.readline()
                if not line:
                    break
                if line.strip() == b"P":
                    x, y = self.reader.position()
                    conn.sendall(("%d,%d\n" % (x, y)).encode())
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def stop(self):
        self._stop = True
        try:
            self.sock.close()
        except Exception:
            pass


# ----------------------------------------------------------- 폐루프 컨트롤러
class FeedbackController(object):
    def __init__(self, client, cursor=None, settle=0.05):
        self.client = client
        self.cursor = cursor or local_cursor()
        self.settle = settle          # HID 반영 대기(초)
        self.last_error = None

    def move_abs_fast(self, x, y, tolerance=2, timeout_s=None, correct=None):
        """Preferred aim for Manmabot farm: ABS one-shot (+ REL fallback).

        Do not use the multi-step P-loop below for bot combat/loot aim.
        """
        ok, pos, ms, corr = self.client.move_abs_aim(
            x,
            y,
            tolerance=tolerance,
            timeout_s=timeout_s,
            correct=correct,
        )
        self.last_error = (x - pos[0], y - pos[1])
        return ok, pos, max(1, int(round(ms)))

    def move_abs(self, x, y, tolerance=2, max_iter=20, max_step=120, factor=0.5):
        """실제 커서가 (x,y) ± tolerance 안에 들어올 때까지 폐루프 보정.
           비례(P) 제어 + 단계 상한으로 가속 환경에서도 안정 수렴한다.
           반환: (성공여부, 최종위치, 반복횟수)

           봇 조준에는 ``move_abs_fast`` / ``client.move_abs_aim`` 을 쓰라.
           이 P-루프(factor=0.5)는 반복×settle 로 150ms+ 가 나오기 쉽다.
           """
        for i in range(max_iter):
            ax, ay = self.cursor.position()
            dx, dy = x - ax, y - ay
            self.last_error = (dx, dy)
            if abs(dx) <= tolerance and abs(dy) <= tolerance:
                return True, (ax, ay), i
            cx = int(dx * factor)
            cy = int(dy * factor)
            if max_step:
                cx = max(-max_step, min(max_step, cx))
                cy = max(-max_step, min(max_step, cy))
            if cx == 0 and dx != 0:
                cx = 1 if dx > 0 else -1
            if cy == 0 and dy != 0:
                cy = 1 if dy > 0 else -1
            self.client.move_rel(cx, cy)
            time.sleep(self.settle)
        return False, self.cursor.position(), max_iter

    def move_click(self, x, y, mask=None, hold_ms=30, **kw):
        from .protocol import BTN_LEFT
        ok, pos, n = self.move_abs(x, y, **kw)
        self.client.click(mask if mask is not None else BTN_LEFT, hold_ms)
        return ok, pos, n

    # 나머지 API 는 클라이언트로 위임 (결합 편의)
    def __getattr__(self, name):
        return getattr(self.client, name)


# ----------------------------------------------------------- CLI (대상 에이전트)
def _main():
    import argparse
    ap = argparse.ArgumentParser(description="control.feedback 대상 에이전트")
    ap.add_argument("--agent", action="store_true", help="커서 위치 보고 에이전트 실행")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9001)
    args = ap.parse_args()
    if args.agent:
        ag = TargetAgent(host=args.host, port=args.port)
        print("TargetAgent 실행중 %s:%d (Ctrl-C 종료)" % (args.host, args.port), flush=True)
        try:
            ag.serve_forever()
        except KeyboardInterrupt:
            ag.stop()
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
