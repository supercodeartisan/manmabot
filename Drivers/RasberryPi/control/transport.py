# -*- coding: utf-8 -*-
"""
control.transport — 결합용 전송 계층 (교체 가능)

모든 전송은 아래 최소 인터페이스만 구현하면 되므로, 임의의 모듈과 자유롭게 결합 가능:
    send(data: bytes)
    recv(timeout: float|None) -> bytes|None
    close()

기본 제공:
    MemoryTransport   : 같은 프로세스/스레드 내 (테스트, 지연측정, 모듈 결합)
    SerialTransport   : USB CDC / UART (라즈베리파이 <-> PC 에 가장 적합)
    SocketTransport   : TCP (TCP_NODELAY 로 지연 최소화)

저지연 원칙: recv timeout 을 작게, send 는 즉시 1회 write, 버퍼링 최소.
"""

import glob
import os
import socket
import threading
import time
from collections import deque


class Transport(object):
    def send(self, data):        # type: (bytes) -> None
        raise NotImplementedError

    def recv(self, timeout=None):  # type: (float|None) -> bytes|None
        raise NotImplementedError

    def close(self):
        pass


# ---------------------------------------------------------------- 메모리
class MemoryTransport(Transport):
    """단방향 큐. pair() 로 양방향 쌍을 만들어 in-process 테스트/결합에 사용.
    이벤트 기반이라 sleep 하한 없이 즉시 깨어난다(지연측정 정확도 향상)."""
    def __init__(self):
        self._q = deque()
        self._lock = threading.Lock()
        self._ev = threading.Event()
        self._closed = False

    @staticmethod
    def pair():
        a, b = MemoryTransport(), MemoryTransport()
        a.peer = b
        b.peer = a
        return a, b

    def send(self, data):
        if self._closed or not hasattr(self, "peer"):
            return
        with self.peer._lock:
            self.peer._q.append(data)
        self.peer._ev.set()

    def recv(self, timeout=None):
        end = None if timeout is None else time.time() + timeout
        while True:
            with self._lock:
                if self._q:
                    data = self._q.popleft()
                    if not self._q:
                        self._ev.clear()
                    return data
            if self._closed:
                return None
            if end is None:
                self._ev.wait(0.05)
            else:
                remaining = end - time.time()
                if remaining <= 0:
                    return None
                self._ev.wait(remaining)

    def close(self):
        self._closed = True


# ---------------------------------------------------------------- 시리얼
class SerialTransport(Transport):
    """pyserial 기반. 라즈베리파이 usb_cdc.data 포트 또는 UART."""
    def __init__(self, port, baudrate=115200, timeout=0.01, rtscts=False):
        import serial  # pyserial
        # Do not toggle DTR/RTS: CircuitPython CDC treats that as a soft-reset
        # and tears down HID mid-session (abs mouse looks "broken").
        try:
            self.serial = serial.Serial(
                port=port, baudrate=baudrate, timeout=timeout,
                write_timeout=1.0, rtscts=rtscts, dsrdtr=False,
            )
        except TypeError:
            self.serial = serial.Serial(
                port=port, baudrate=baudrate, timeout=timeout,
                write_timeout=1.0, rtscts=rtscts,
            )
        try:
            self.serial.dtr = False
            self.serial.rts = False
        except Exception:
            pass
        try:
            self.serial.reset_input_buffer()
        except Exception:
            pass

    def send(self, data):
        self.serial.write(data)

    def recv(self, timeout=None):
        if timeout is not None:
            self.serial.timeout = timeout
        data = self.serial.read(4096)   # timeout 만큼 대기 후 가용분 반환
        return data or None

    def close(self):
        try:
            self.serial.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 소켓(TCP)
class SocketTransport(Transport):
    def __init__(self, sock):
        self.sock = sock
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # 지연 최소화
        except Exception:
            pass
        self.sock.settimeout(None)

    def send(self, data):
        self.sock.sendall(data)

    def recv(self, timeout=None):
        self.sock.settimeout(timeout)
        try:
            data = self.sock.recv(65536)
        except socket.timeout:
            return None
        if not data:
            raise ConnectionError("peer closed")
        return data

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def tcp_connect(host, port, timeout=5.0):
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(None)
    return SocketTransport(s)


class TcpListener(object):
    """서버측: accept() 로 SocketTransport 를 돌려준다."""
    def __init__(self, host="0.0.0.0", port=9999, backlog=1):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(backlog)

    def accept(self):
        conn, addr = self.sock.accept()
        return SocketTransport(conn), addr

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------- UDP
class UdpTransport(Transport):
    """최저 지연(비연결). 손실 허용 시 사용. 신뢰성이 필요하면 TCP/시리얼 권장."""
    def __init__(self, bind=None, peer=None, local_addr=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if bind:
            self.sock.bind(bind)
        self.peer = peer
        self.sock.settimeout(None)

    def send(self, data):
        if self.peer is None:
            raise ValueError("UDP peer 미설정")
        self.sock.sendto(data, self.peer)

    def recv(self, timeout=None):
        self.sock.settimeout(timeout)
        try:
            data, addr = self.sock.recvfrom(65536)
        except socket.timeout:
            return None
        if self.peer is None:
            self.peer = addr
        return data

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def list_serial_ports():
    """사용 가능한 시리얼 포트 목록 (pyserial 우선, 없으면 레지스트리/glob)."""
    try:
        from serial.tools import list_ports as lp
        return [p.device for p in lp.comports()]
    except Exception:
        pass
    ports = []
    if os.name == "nt":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
            i = 0
            while True:
                try:
                    _, val, _ = winreg.EnumValue(k, i)
                    ports.append(val)
                    i += 1
                except OSError:
                    break
        except Exception:
            pass
    else:
        ports += sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
                        + glob.glob("/dev/tty.usbmodem*"))
    return ports

