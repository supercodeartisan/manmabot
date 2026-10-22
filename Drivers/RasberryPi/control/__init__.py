# -*- coding: utf-8 -*-
"""
control — 컴퓨터의 지령에 따라 라즈베리파이에서 '하드웨어 준위' 마우스/키보드 입력을
실시간 시뮬레이션하는 저지연·고결합 모듈.

빠른 사용 예:

    # --- 컴퓨터 측 ---
    from control import ControlClient, tcp_connect
    c = ControlClient(tcp_connect("192.168.0.10", 9999))
    c.set_screen(1920, 1080)
    c.move_click(300, 200, hold_ms=25)      # 좌표 이동 후 클릭
    c.key(0x04)                              # 'a'
    print("RTT(ms):", c.ping(samples=5))

    # --- 라즈베리파이 측 ---
    from control import ControlServer, TcpListener, UinputBackend
    srv = ControlServer(TcpListener(port=9999).accept()[0], UinputBackend())
    srv.run()          # 백그라운드 스레드에서 실행해도 됨

가장 중요한 3요소
  * 저지연 : protocol(고정 12B 헤더) + transport(즉시 write, TCP_NODELAY) + server(무블로킹, hold 예약)
  * 안정성 : CRC16 + 시퀀스 + 프레임 자동 재동기화 + ping() 으로 품질 상시 확인
  * 결합성 : Transport / HidBackend / 핸들러 를 모두 주입·등록식으로 교체 가능
"""

from . import protocol
from .protocol import (
    ACT_UP, ACT_DOWN, ACT_PRESS, BTN_LEFT, BTN_RIGHT, BTN_MIDDLE,
    T_PING, T_PONG, T_MOUSE_ABS, T_MOUSE_REL, T_MOUSE_BTN, T_MOUSE_WHEEL,
    T_KEY, T_KEY_TEXT, T_SET_SCREEN, T_SYNC, FrameParser, encode, pack, unpack, crc16,
)
from .transport import (
    Transport, MemoryTransport, SerialTransport, SocketTransport,
    UdpTransport, TcpListener, tcp_connect,
)
from .backend import HidBackend, NullBackend, AbsoluteTracker
from .server import ControlServer
from .client import ControlClient
from .feedback import (
    CursorReader, NullCursor, WindowsCursor, X11Cursor, RemoteCursor,
    TargetAgent, FeedbackController, local_cursor,
)
from .guard import InputGuard, GuardedController, guard_client

__all__ = [
    "protocol", "encode", "pack", "unpack", "crc16", "FrameParser",
    "T_PING", "T_PONG", "T_MOUSE_ABS", "T_MOUSE_REL", "T_MOUSE_BTN", "T_MOUSE_WHEEL",
    "T_KEY", "T_KEY_TEXT", "T_SET_SCREEN", "T_SYNC",
    "ACT_UP", "ACT_DOWN", "ACT_PRESS", "BTN_LEFT", "BTN_RIGHT", "BTN_MIDDLE",
    "Transport", "MemoryTransport", "SerialTransport", "SocketTransport",
    "UdpTransport", "TcpListener", "tcp_connect",
    "HidBackend", "NullBackend", "AbsoluteTracker",
    "ControlServer", "ControlClient",
    "CursorReader", "NullCursor", "WindowsCursor", "X11Cursor", "RemoteCursor",
    "TargetAgent", "FeedbackController", "local_cursor",
    "InputGuard", "GuardedController", "guard_client",
]

__version__ = "1.0.0"
