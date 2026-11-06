#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CircuitPython 자동 설치기  (RP2040 / RP2350 계열 보드)

지원 보드 예:
  - Raspberry Pi Pico / Pico W          (RP2040)
  - Raspberry Pi Pico 2 / Pico 2 W      (RP2350)
  - RP2040/RP2350 를 쓰는 그 밖의 보드 (--board 로 CircuitPython 보드 ID 지정)

동작 순서:
  1) BOOTSEL 부트로더 드라이브 자동 탐색 (INFO_UF2.TXT 기준)
  2) 보드 정보(Model/Board-ID)로 CircuitPython 보드 ID 추정
  3) circuitpython.org 에서 최신 안정판 .uf2 URL 확인 후 다운로드
  4) UF2 검증(매직 + 패밀리 ID)
  5) 부트로더 드라이브에 복사 -> 보드 자동 재부팅
  6) CIRCUITPY 드라이브 / 시리얼(COM) 포트가 나타날 때까지 대기

사용 예:
  python install_circuitpython.py
  python install_circuitpython.py --board raspberry_pi_pico2_w
  python install_circuitpython.py --uf2  .\\adafruit-circuitpython-...uf2
  python install_circuitpython.py --port COM4 --reboot-to-bootloader
  python install_circuitpython.py --dry-run
  python install_circuitpython.py --list
"""

import argparse
import glob
import os
import re
import shutil
import string
import sys
import tempfile
import time
import urllib.request

# --- 콘솔 인코딩 안전 처리 (한글/출력 리다이렉트 환경에서 크래시 방지) ---
def _setup_console_encoding():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_console_encoding()

APP = "CircuitPython Installer"
UA = {"User-Agent": "circuitpython-installer/1.0"}
CIRCUITPY_PAGE = "https://circuitpython.org/board/{board}/"

UF2_MAGIC0 = 0x0A324655
UF2_MAGIC1 = 0x9E5D5157
UF2_FAMILIES = {
    0xE48BFF56: "RP2040",
    0xE48BFF57: "RP2350 (ARM)",
    0xE48BFF58: "RP2350 (RISC-V)",
    0xE48BFF59: "RP2350 (ARM / CircuitPython)",
}

# 부트로더 패밀리 -> CircuitPython 보드 ID (기본: 무선 없는 모델이 W 보드에서도 부팅됨)
FAMILY_TO_BOARD = {
    "RP2350": "raspberry_pi_pico2",
    "RP2040": "raspberry_pi_pico",
}
KNOWN_BOARDS = {
    "raspberry_pi_pico": "Raspberry Pi Pico (RP2040)",
    "raspberry_pi_pico_w": "Raspberry Pi Pico W (RP2040 + WiFi)",
    "raspberry_pi_pico2": "Raspberry Pi Pico 2 (RP2350)",
    "raspberry_pi_pico2_w": "Raspberry Pi Pico 2 W (RP2350 + WiFi)",
}
VER_RE = re.compile(
    r"-(\d+)\.(\d+)\.(\d+)(?:-?(alpha|beta|rc)[.\-]?(\d+))?\.uf2$", re.I
)

_LOG_SINK = None
_PROGRESS_SINK = None


def log(msg=""):
    print(msg, flush=True)
    if _LOG_SINK is not None:
        try:
            _LOG_SINK(msg)
        except Exception:
            pass


def http_get(url, binary=False, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def http_download(url, dest, timeout=300, on_progress=None):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                if on_progress is not None:
                    try:
                        on_progress(done, total)
                    except Exception:
                        pass
                else:
                    sys.stdout.write("\r  다운로드 %3d%%  (%d KiB)" % (done * 100 // total, done // 1024))
                    sys.stdout.flush()
    if on_progress is None:
        log()


def parse_version(name):
    m = VER_RE.search(name)
    if not m:
        return None
    major, minor, micro = int(m.group(1)), int(m.group(2)), int(m.group(3))
    pre, prenum = m.group(4), int(m.group(5) or 0)
    if pre:
        order = {"rc": 3, "beta": 2, "alpha": 1}[pre.lower()]
        return (major, minor, micro, order, prenum)
    return (major, minor, micro, 4, 0)  # 정식판이 프리릴리스보다 큼


def latest_uf2_url(board, lang="en_US", allow_pre=False):
    html = http_get(CIRCUITPY_PAGE.format(board=board))
    urls = re.findall(r'https://downloads\.circuitpython\.org/[^\s"\'<>]+?\.uf2', html)
    cands = []
    for u in set(urls):
        if "/%s/" % lang not in u:
            continue
        name = u.rsplit("/", 1)[-1]
        if board not in name:
            continue
        v = parse_version(name)
        if v is None:
            continue
        if v[3] < 4 and not allow_pre:  # 프리릴리스 제외
            continue
        cands.append((v, u))
    if not cands:
        return None
    cands.sort()
    return cands[-1][1]


def candidate_mounts():
    mounts = []
    if os.name == "nt":
        for d in string.ascii_uppercase:
            root = "%s:\\" % d
            if os.path.isdir(root):
                mounts.append(root)
    else:
        for base in ("/Volumes", "/media", "/run/media", "/mnt"):
            if os.path.isdir(base):
                mounts += glob.glob(os.path.join(base, "*"))
                mounts += glob.glob(os.path.join(base, "*", "*"))
    seen, out = set(), []
    for m in mounts:
        m = os.path.abspath(m)
        if m not in seen and os.path.isdir(m):
            seen.add(m)
            out.append(m)
    return out


def find_bootloader_drive():
    """INFO_UF2.TXT 가 있는 드라이브 = RP2040/RP2350 BOOTSEL 부트로더."""
    for root in candidate_mounts():
        if os.path.isfile(os.path.join(root, "INFO_UF2.TXT")):
            return root
    return None


def find_circuitpy_drive():
    """boot_out.txt 가 있는 드라이브 = 실행 중인 CircuitPython."""
    for root in candidate_mounts():
        if os.path.isfile(os.path.join(root, "boot_out.txt")):
            return root
    return None


def read_info_uf2(root):
    try:
        with open(os.path.join(root, "INFO_UF2.TXT"), "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def guess_board(info_text):
    up = (info_text or "").upper()
    if "RP2350" in up:
        return FAMILY_TO_BOARD["RP2350"], "RP2350"
    if "RP2040" in up:
        return FAMILY_TO_BOARD["RP2040"], "RP2040"
    return None, None


def list_ports():
    try:
        from serial.tools import list_ports as lp
        return [p.device for p in lp.comports()]
    except Exception:
        pass
    ports = []
    if os.name == "nt":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
            i = 0
            while True:
                try:
                    _, val, _ = winreg.EnumValue(key, i)
                    ports.append(val)
                    i += 1
                except OSError:
                    break
        except Exception:
            pass
    else:
        ports += sorted(
            glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
            + glob.glob("/dev/tty.usbmodem*") + glob.glob("/dev/tty.usbserial*")
        )
    return ports


def reboot_to_bootloader(port):
    """실행 중인 CircuitPython/MicroPython 보드를 소프트웨어로 BOOTSEL 에 진입시킨다."""
    try:
        import serial
    except ImportError:
        log("  pyserial 이 없어 자동 BOOTSEL 진입을 건너뜁니다 (pip install pyserial).")
        return False
    log("  %s 포트로 BOOTSEL 재부팅 시도..." % port)
    try:
        s = serial.Serial(port, 115200, timeout=0.4, write_timeout=3)
    except Exception as e:
        log("    %s 포트를 열 수 없습니다: %s" % (port, e))
        log("    -> Thonny 등 포트를 점유한 프로그램을 종료한 뒤 다시 시도하세요.")
        return False

    def send(data, wait=0.5):
        try:
            s.write(data)
        except Exception:
            return
        time.sleep(wait)
        try:
            s.read(8192)
        except Exception:
            pass

    try:
        time.sleep(0.3)
        send(b"\x03\x03")   # 인터럽트 (Ctrl-C x2)
        send(b"\x02")       # raw REPL 이면 friendly REPL 로 탈출 (Ctrl-B)
        send(b"import microcontroller\r\n")
        send(b"microcontroller.on_next_reset(microcontroller.RunMode.BOOTLOADER)\r\n")
        send(b"microcontroller.reset()\r\n", 0.8)                 # CircuitPython
        send(b"import machine\r\nmachine.bootloader()\r\n", 0.5)   # MicroPython 폴백
    finally:
        try:
            s.close()
        except Exception:
            pass
    return True


def verify_uf2(path):
    with open(path, "rb") as f:
        head = f.read(32)
    if len(head) < 32:
        raise ValueError("파일이 너무 작습니다.")
    magic0 = int.from_bytes(head[0:4], "little")
    magic1 = int.from_bytes(head[4:8], "little")
    family = int.from_bytes(head[28:32], "little")
    if magic0 != UF2_MAGIC0 or magic1 != UF2_MAGIC1:
        raise ValueError("UF2 형식이 아닙니다(매직 불일치).")
    return family


def flash(drive, uf2_path):
    target = os.path.join(drive, os.path.basename(uf2_path))
    log("  %s 로 복사: %s" % (drive, os.path.basename(uf2_path)))
    shutil.copyfile(uf2_path, target)
    try:
        os.sync()
    except AttributeError:
        pass


def wait_for_circuitpy(timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = find_circuitpy_drive()
        if d:
            return d
        time.sleep(0.5)
    return None


def wait_for_new_port(before, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        new = [p for p in list_ports() if p not in before]
        if new:
            return new
        time.sleep(0.5)
    return []


def run_from_args(args):
    """CLI 인자를 받아 설치 절차를 수행한다(반환: 종료 코드)."""

    if args.list:
        log("알려진 CircuitPython 보드 ID:")
        for k, v in KNOWN_BOARDS.items():
            log("  %-24s %s" % (k, v))
        log("그 밖의 보드는 https://circuitpython.org/downloads 참고.")
        return 0

    log("== %s ==" % APP)

    # 1) 부트로더 드라이브 탐색
    drive = find_bootloader_drive()
    if drive:
        info = read_info_uf2(drive)
        log("[1] 부트로더 발견: %s" % drive)
        for line in info.splitlines():
            if line.strip():
                log("     " + line.strip())
    else:
        cp = find_circuitpy_drive()
        if cp and not args.force:
            log("[1] 이미 CircuitPython 설치됨: %s  (재설치: --force)" % cp)
            return 0
        if args.reboot_to_bootloader or args.port:
            port = args.port
            if not port:
                ports = list_ports()
                port = ports[0] if len(ports) == 1 else input("BOOTSEL 로 재부팅할 포트 입력: ").strip()
            reboot_to_bootloader(port)
            for _ in range(30):
                time.sleep(0.5)
                drive = find_bootloader_drive()
                if drive:
                    break
        if not drive:
            log("[1] BOOTSEL 부트로더를 찾지 못했습니다.")
            log("    -> BOOTSEL 버튼을 누른 채 USB를 꽂은 뒤 다시 실행하세요.")
            return 1
        info = read_info_uf2(drive)
        log("[1] 부트로더 발견: %s" % drive)

    # 2) 보드 결정
    if args.board:
        board = args.board
        log("[2] 보드(지정): %s" % board)
    else:
        board, fam = guess_board(info)
        if board:
            log("[2] 보드 추정: %s  (패밀리 %s)" % (board, fam))
            log("    * WiFi 필요하면 --board raspberry_pi_pico2_w / raspberry_pi_pico_w")
        else:
            log("[2] 자동 인식 실패")
            board = input("CircuitPython 보드 ID 입력 [raspberry_pi_pico2]: ").strip() or "raspberry_pi_pico2"

    # 3) UF2 확보
    if args.uf2:
        uf2_path = os.path.abspath(args.uf2)
        if not os.path.isfile(uf2_path):
            log("[3] 파일이 없습니다: %s" % uf2_path)
            return 1
        log("[3] 로컬 UF2 사용: %s" % uf2_path)
    else:
        log("[3] 최신 CircuitPython 확인 중... (%s / %s)" % (board, args.lang))
        url = latest_uf2_url(board, args.lang, args.pre)
        if not url:
            log("    '%s' 용 %s 펌웨어를 찾지 못했습니다. --board / --lang 확인." % (board, args.lang))
            return 1
        log("    " + url)
        uf2_path = os.path.join(tempfile.gettempdir(), url.rsplit("/", 1)[-1])
        http_download(url, uf2_path, on_progress=_PROGRESS_SINK)

    # 4) 검증
    try:
        family = verify_uf2(uf2_path)
    except ValueError as e:
        log("[4] UF2 검증 실패: %s" % e)
        return 1
    log("[4] UF2 OK — 패밀리 %s, %d bytes"
        % (UF2_FAMILIES.get(family, "0x%08X" % family), os.path.getsize(uf2_path)))

    if args.dry_run:
        log("[5] --dry-run: 플래시하지 않음")
        return 0

    # 5) 플래시
    before = set(list_ports())
    log("[5] 기록 중...")
    try:
        flash(drive, uf2_path)
    except OSError as e:
        log("    복사 실패: %s" % e)
        return 1
    log("    완료 — 보드가 자동 재부팅됩니다.")

    # 6) 대기
    log("[6] CIRCUITPY / 시리얼 포트 대기...")
    cpd = wait_for_circuitpy(args.timeout)
    newports = wait_for_new_port(before, 20)

    log("")
    log("== 결과 ==")
    log("  CIRCUITPY 드라이브 : %s" % (cpd or "인식 안 됨"))
    log("  시리얼 포트        : %s" % (", ".join(newports) if newports else "인식 안 됨"))
    if cpd:
        log("  Thonny 에서: Tools > Options > Interpreter > 'CircuitPython (generic)' + 포트 선택")
    log("  테스트: REPL 에  import sys; print(sys.version)")
    return 0 if cpd else 1


def build_arg_parser():
    ap = argparse.ArgumentParser(description="CircuitPython 자동 설치기 (RP2040/RP2350)")
    ap.add_argument("--board", help="CircuitPython 보드 ID (예: raspberry_pi_pico2_w)")
    ap.add_argument("--lang", default="en_US", help="펌웨어 언어 폴더 (기본 en_US)")
    ap.add_argument("--uf2", help="로컬 .uf2 파일을 사용")
    ap.add_argument("--port", help="BOOTSEL 자동 진입에 쓸 시리얼 포트 (예: COM4)")
    ap.add_argument("--reboot-to-bootloader", action="store_true", help="실행 중이면 자동으로 BOOTSEL 진입")
    ap.add_argument("--pre", action="store_true", help="프리릴리스 펌웨어 허용")
    ap.add_argument("--dry-run", action="store_true", help="다운로드/검증만 (플래시 안 함)")
    ap.add_argument("--force", action="store_true", help="이미 설치돼 있어도 재설치")
    ap.add_argument("--list", action="store_true", help="알려진 보드 목록 출력")
    ap.add_argument("--timeout", type=int, default=40, help="CIRCUITPY 대기 시간(초)")
    ap.add_argument("--ui", action="store_true", help="그래픽 UI 실행")
    return ap


def main():
    args = build_arg_parser().parse_args()
    if args.ui:
        return gui_main()
    return run_from_args(args)


def gui_main():
    """Tkinter 그래픽 UI (파이썬 기본 내장)."""
    try:
        import tkinter as tk
        from tkinter import ttk, scrolledtext, messagebox
    except Exception as e:
        log("tkinter 를 사용할 수 없습니다: %s" % e)
        log("커맨드라인 모드로 실행하세요 (--ui 없이).")
        return 1
    import queue as _queue
    import threading as _threading

    global _LOG_SINK, _PROGRESS_SINK
    q = _queue.Queue()

    def _sink(msg):
        q.put(("log", msg))

    def _prog(done, total):
        q.put(("prog", (done, total)))

    _LOG_SINK = _sink
    _PROGRESS_SINK = _prog

    root = tk.Tk()
    root.title("CircuitPython 설치기  (RP2040 / RP2350)")
    root.geometry("780x600")
    root.minsize(680, 520)

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    board_var = tk.StringVar(value="raspberry_pi_pico2")
    port_var = tk.StringVar(value="")
    lang_var = tk.StringVar(value="en_US")
    timeout_var = tk.StringVar(value="40")
    status_var = tk.StringVar(value="대기 중")
    force_var = tk.BooleanVar(value=True)
    reboot_var = tk.BooleanVar(value=True)
    dry_var = tk.BooleanVar(value=False)
    pre_var = tk.BooleanVar(value=False)

    # --- 설정 ---
    top = ttk.LabelFrame(frm, text="설정", padding=8)
    top.pack(fill="x")

    ttk.Label(top, text="보드 모델").grid(row=0, column=0, sticky="w")
    board_cb = ttk.Combobox(top, textvariable=board_var, width=30, values=list(KNOWN_BOARDS.keys()))
    board_cb.grid(row=0, column=1, sticky="w", padx=6)
    ttk.Label(top, text="시리얼 포트").grid(row=0, column=2, sticky="w", padx=(16, 0))
    port_cb = ttk.Combobox(top, textvariable=port_var, width=14, values=[])
    port_cb.grid(row=0, column=3, sticky="w", padx=6)

    ttk.Label(top, text="언어").grid(row=1, column=0, sticky="w", pady=(8, 0))
    ttk.Entry(top, textvariable=lang_var, width=12).grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
    ttk.Label(top, text="대기(초)").grid(row=1, column=2, sticky="w", padx=(16, 0), pady=(8, 0))
    ttk.Spinbox(top, from_=5, to=180, textvariable=timeout_var, width=6).grid(row=1, column=3, sticky="w", padx=6, pady=(8, 0))

    # --- 옵션 ---
    opts = ttk.LabelFrame(frm, text="옵션", padding=8)
    opts.pack(fill="x", pady=(8, 0))
    ttk.Checkbutton(opts, text="이미 설치돼 있어도 재설치", variable=force_var).grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(opts, text="BOOTSEL 자동 진입", variable=reboot_var).grid(row=0, column=1, sticky="w", padx=16)
    ttk.Checkbutton(opts, text="다운로드만(dry-run)", variable=dry_var).grid(row=0, column=2, sticky="w", padx=16)
    ttk.Checkbutton(opts, text="프리릴리스 허용", variable=pre_var).grid(row=0, column=3, sticky="w", padx=16)

    # --- 버튼 ---
    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(8, 0))
    start_btn = ttk.Button(btns, text="▶ 설치 시작")
    start_btn.pack(side="left")
    refresh_btn = ttk.Button(btns, text="감지 새로고침")
    refresh_btn.pack(side="left", padx=6)
    boards_btn = ttk.Button(btns, text="지원 보드")
    boards_btn.pack(side="left", padx=6)
    clear_btn = ttk.Button(btns, text="로그 지우기")
    clear_btn.pack(side="left", padx=6)
    ttk.Label(btns, textvariable=status_var).pack(side="right")

    # --- 진행률 ---
    pbar = ttk.Progressbar(frm, mode="determinate", maximum=100)
    pbar.pack(fill="x", pady=(8, 0))

    # --- 로그 ---
    txt = scrolledtext.ScrolledText(frm, height=18, state="disabled", wrap="word")
    txt.pack(fill="both", expand=True, pady=(8, 0))

    def append_log(msg):
        txt.configure(state="normal")
        txt.insert("end", msg + "\n")
        txt.see("end")
        txt.configure(state="disabled")

    def clear_log():
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.configure(state="disabled")

    def show_boards():
        lines = ["%s  —  %s" % (k, v) for k, v in KNOWN_BOARDS.items()]
        messagebox.showinfo(
            "지원 보드",
            "\n".join(lines) + "\n\n그 밖의 보드는 https://circuitpython.org/downloads",
        )

    def refresh():
        bl = find_bootloader_drive()
        cp = find_circuitpy_drive()
        ports = list_ports()
        port_cb["values"] = ports
        if ports and not port_var.get().strip():
            port_var.set(ports[0])
        status_var.set("부트로더: %s  |  CircuitPython: %s  |  포트: %s"
                       % (bl or "없음", cp or "없음", ", ".join(ports) or "없음"))
        append_log("[감지] 부트로더=%s  CircuitPython=%s  포트=%s"
                   % (bl or "-", cp or "-", ", ".join(ports) or "-"))

    def drain():
        try:
            while True:
                kind, payload = q.get_nowait()
                if kind == "log":
                    append_log(payload)
                elif kind == "prog":
                    done, total = payload
                    pbar["maximum"] = total
                    pbar["value"] = done
                elif kind == "done":
                    rc = payload
                    start_btn.configure(state="normal")
                    pbar["value"] = 0
                    if rc == 0:
                        status_var.set("완료")
                        messagebox.showinfo(
                            "완료",
                            "설치가 끝났습니다.\n\nThonny: Tools > Options > Interpreter\n"
                            "→ 'CircuitPython (generic)' + 포트 선택",
                        )
                    else:
                        status_var.set("오류/중단 (코드 %s)" % rc)
        except _queue.Empty:
            pass
        root.after(120, drain)

    def start():
        board = board_var.get().strip()
        if not board:
            messagebox.showwarning("보드", "보드 모델을 입력하세요.")
            return
        rt = reboot_var.get()
        port = port_var.get().strip()
        if rt and not port:
            messagebox.showwarning(
                "포트",
                "BOOTSEL 자동 진입을 쓰려면 시리얼 포트를 선택하세요.\n"
                "포트가 없으면 보드를 직접 BOOTSEL 로 넣어두세요.",
            )
            return
        try:
            to = int(timeout_var.get())
        except Exception:
            to = 40
        ns = argparse.Namespace(
            board=board,
            lang=lang_var.get().strip() or "en_US",
            uf2=None,
            port=port,
            reboot_to_bootloader=rt,
            pre=pre_var.get(),
            dry_run=dry_var.get(),
            force=force_var.get(),
            list=False,
            timeout=to,
        )
        start_btn.configure(state="disabled")
        status_var.set("진행 중...")
        clear_log()

        def work():
            rc = 1
            try:
                rc = run_from_args(ns)
            except Exception as e:
                q.put(("log", "예외: %s" % e))
            q.put(("done", rc))

        _threading.Thread(target=work, daemon=True).start()

    start_btn.configure(command=start)
    refresh_btn.configure(command=refresh)
    boards_btn.configure(command=show_boards)
    clear_btn.configure(command=clear_log)

    append_log("보드를 연결한 뒤 [설치 시작] 을 누르세요.")
    append_log("이미 CircuitPython 이 실행 중이면 'BOOTSEL 자동 진입' 으로 버튼 없이 재설치됩니다.")
    append_log("")
    refresh()
    root.after(120, drain)
    root.mainloop()
    _LOG_SINK = None
    _PROGRESS_SINK = None
    return 0


if __name__ == "__main__":
    sys.exit(main())
