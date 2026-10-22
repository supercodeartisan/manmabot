# -*- coding: utf-8 -*-
"""
control.pi_server — 라즈베리파이(리눅스) 측 실행기: 지령 수신 -> 하드웨어 입력 주입

사용 예
  # TCP 로 대기 (다른 PC 에서 접속)
  python -m control.pi_server --tcp 9999 --screen 1920x1080

  # 시리얼(USB CDC/UART)
  python -m control.pi_server --serial /dev/ttyACM0

  # 절대좌표 포인터(EV_ABS) 로
  python -m control.pi_server --tcp 9999 --absolute

  # 하드웨어 없이 수신만 확인(로그)
  python -m control.pi_server --tcp 9999 --null

사전 준비(라즈베리파이)
  sudo modprobe uinput
  pip install evdev            (또는 sudo apt install python3-evdev)
  sudo 로 실행하거나 /dev/uinput udev 규칙 추가
"""

import argparse
import sys


def _parse_screen(s):
    a, b = s.lower().replace(" ", "").split("x")
    return int(a), int(b)


def main():
    ap = argparse.ArgumentParser(description="control 라즈베리파이 수신 서버")
    ap.add_argument("--tcp", type=int, help="TCP 포트로 수신 대기")
    ap.add_argument("--serial", help="시리얼 포트 (예: /dev/ttyACM0, COM5)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--screen", default="1920x1080", help="화면 크기 WxH (절대좌표 변환)")
    ap.add_argument("--absolute", action="store_true", help="uinput 절대 포인터(EV_ABS)")
    ap.add_argument("--null", action="store_true", help="하드웨어 없이 수신 로그만")
    args = ap.parse_args()

    w, h = _parse_screen(args.screen)

    if args.null:
        from .backend import NullBackend
        backend = NullBackend(screen=(w, h),
                              on_action=lambda it: print("[recv]", it, flush=True))
    else:
        from .backends_linux import UinputBackend
        backend = UinputBackend(screen=(w, h), absolute=args.absolute)

    if args.tcp:
        from .transport import TcpListener
        from .server import ControlServer
        lst = TcpListener(port=args.tcp)
        print("TCP 대기중 :%d (screen=%dx%d, absolute=%s)"
              % (args.tcp, w, h, args.absolute), flush=True)
        while True:
            tr, addr = lst.accept()
            print("연결됨:", addr, flush=True)
            ControlServer(tr, backend).run()
    elif args.serial:
        from .transport import SerialTransport
        from .server import ControlServer
        tr = SerialTransport(args.serial, args.baud)
        print("시리얼 %s 대기중" % args.serial, flush=True)
        ControlServer(tr, backend).run()
    else:
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
