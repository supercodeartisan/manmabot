# -*- coding: utf-8 -*-
"""
control.protocol — 컴퓨터(PC) <-> 라즈베리파이 공용 저지연 바이너리 프로토콜

프레임(리틀엔디언), 고정 헤더 12 byte:
  +--------+--------+---------+------+-------+--------+-------+---------+
  | magic0 | magic1 | version | type |  seq  | length | crc16 | payload |
  |  0xC0  |  0xDE  |    1    |  u8  |  u32  |   u16  |  u16  |  N byte |
  +--------+--------+---------+------+-------+--------+-------+---------+
  crc16 = CRC16-CCITT(header[0:10] + payload)

설계 목표
  * 최소 지연 : 고정 헤더 + 즉시 write, 기본 단방향(ACK 없음), SYNC 로 선택적 확정
  * 안정성    : CRC16, 시퀀스 번호, 파서가 magic 스캔으로 자동 재동기화
  * 결합성    : type/페이로드를 struct 로 정의 -> 새 명령 타입 추가가 매우 쉬움
"""

import struct

MAGIC0 = 0xC0
MAGIC1 = 0xDE
VERSION = 1
HEADER_LEN = 12
_HEADER = struct.Struct("<BBBB I H H")  # magic0,magic1,version,type,seq,length,crc
_BAD = bytes((MAGIC0, MAGIC1))

# ---------------- 메시지 타입 ----------------
T_PING        = 0x01  # payload: Q     (클라이언트 시각)
T_PONG        = 0x02  # payload: Q Q   (에코 시각, 보드 시각)
T_MOUSE_ABS   = 0x10  # payload: H H   (x, y  화면 픽셀좌표)
T_MOUSE_REL   = 0x11  # payload: h h   (dx, dy)
T_MOUSE_BTN   = 0x12  # payload: B B H (버튼마스크, 동작, 유지ms)
T_MOUSE_WHEEL = 0x13  # payload: b     (휠)
T_KEY         = 0x20  # payload: B B B H (HID키코드, 수정자, 동작, 유지ms)
T_KEY_TEXT    = 0x21  # payload: utf-8
T_TYPE        = 0x22  # payload: H(cps) + utf-8   (건별 타이핑 속도 지정)
T_SET_SCREEN  = 0x30  # payload: H H   (화면 너비, 높이)
T_SYNC        = 0x31  # payload: 없음 또는 H H (커서 x,y 재동기화)
T_RESET       = 0x32  # payload: 없음  → microcontroller.reset() (boot.py 재실행)
T_GET_MODE    = 0x33  # payload: 없음  / 응답: utf-8 "ABS"|"REL"

ACT_UP, ACT_DOWN, ACT_PRESS = 0, 1, 2
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x01, 0x02, 0x04

_EVT = {
    T_PING: "<Q", T_PONG: "<QQ", T_MOUSE_ABS: "<HH", T_MOUSE_REL: "<hh",
    T_MOUSE_BTN: "<BBH", T_MOUSE_WHEEL: "<b", T_KEY: "<BBBH", T_SET_SCREEN: "<HH",
    T_SYNC: "<HH",
}

# ---------------- CRC16-CCITT (테이블) ----------------
_CRC_TABLE = []
for _i in range(256):
    _c = _i << 8
    for _ in range(8):
        _c = ((_c << 1) ^ 0x1021) & 0xFFFF if (_c & 0x8000) else ((_c << 1) & 0xFFFF)
    _CRC_TABLE.append(_c)


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[((crc >> 8) ^ b) & 0xFF]
    return crc


# ---------------- 인코딩 ----------------
def encode(msg_type, seq, payload=b""):
    """완성된 한 프레임(bytes)을 만든다."""
    head = _HEADER.pack(MAGIC0, MAGIC1, VERSION, msg_type & 0xFF,
                        seq & 0xFFFFFFFF, len(payload), 0)
    crc = crc16(head[:10] + payload)
    return head[:10] + struct.pack("<H", crc) + payload


def pack(msg_type, *args):
    """메시지 페이로드를 만든다. (T_KEY_TEXT/T_TYPE 은 문자열을 직접 넣는다)"""
    if msg_type == T_KEY_TEXT:
        s = args[0]
        return s.encode("utf-8") if isinstance(s, str) else bytes(s)
    if msg_type == T_TYPE:
        cps, s = args
        b = s.encode("utf-8") if isinstance(s, str) else bytes(s)
        return struct.pack("<H", int(cps)) + b
    if msg_type == T_SYNC:
        if not args:
            return b""
        return struct.pack("<HH", int(args[0]) & 0xFFFF, int(args[1]) & 0xFFFF)
    return struct.pack(_EVT[msg_type], *args)


def unpack(msg_type, payload):
    if msg_type == T_KEY_TEXT:
        return (payload.decode("utf-8", "replace"),)
    if msg_type == T_TYPE:
        (cps,) = struct.unpack_from("<H", payload, 0)
        return (cps, payload[2:].decode("utf-8", "replace"))
    if msg_type == T_SYNC:
        if len(payload) >= 4:
            return struct.unpack_from("<HH", payload, 0)
        return ()
    return struct.unpack_from(_EVT[msg_type], payload, 0)


# ---------------- 스트림 파서 ----------------
class FrameParser:
    """바이트 스트림에서 프레임을 추출. 손상 프레임은 세어 두고 자동 재동기화."""
    def __init__(self):
        self._buf = bytearray()
        self.frames_ok = 0
        self.frames_bad = 0

    def feed(self, data):
        if data:
            self._buf += data
        out = []
        while len(self._buf) >= HEADER_LEN:
            if self._buf[0] != MAGIC0 or self._buf[1] != MAGIC1:
                idx = self._buf.find(_BAD, 1)
                if idx < 0:
                    del self._buf[:-1]
                    break
                del self._buf[:idx]
                continue
            _m0, _m1, ver, mtype, seq, length, crc = _HEADER.unpack_from(self._buf, 0)
            if len(self._buf) < HEADER_LEN + length:
                break
            payload = bytes(self._buf[HEADER_LEN:HEADER_LEN + length])
            if crc16(self._buf[:10] + payload) == crc and ver == VERSION:
                out.append((mtype, seq, payload))
                self.frames_ok += 1
            else:
                self.frames_bad += 1
            del self._buf[:HEADER_LEN + length]
        return out


def now_us():
    import time
    return int(time.time() * 1_000_000)
