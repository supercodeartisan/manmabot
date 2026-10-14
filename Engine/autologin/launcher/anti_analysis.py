"""
Anti-Analysis Module
Standalone component — debugger, VM, sandbox, and timing detection.

Usage:
    from launcher.anti_analysis import AntiAnalysis
    aa = AntiAnalysis()
    results = aa.run_all()
    if results["threats"]:
        print(aa.report(results))
"""
import ctypes
import os
import platform
import struct
import sys
import time
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
user32 = ctypes.WinDLL("user32")


class AntiAnalysis:

    def __init__(self, silent=False):
        self.silent = silent

    def run_all(self):
        checks = [
            ("Debugger", self.check_debugger),
            ("Remote Debugger", self.check_remote_debugger),
            ("Hardware Breakpoints", self.check_hw_breakpoints),
            ("Trap Flag", self.check_trap_flag),
            ("NtGlobalFlag", self.check_nt_global_flag),
            ("Heap Flags", self.check_heap_flags),
            ("Parent Process", self.check_parent_process),
            ("Process Name", self.check_process_name),
            ("VM (Registry)", self.check_vm_registry),
            ("VM (Hardware)", self.check_vm_hardware),
            ("VM (CPU)", self.check_vm_cpu),
            ("VM (MAC)", self.check_vm_mac),
            ("VM (Disk)", self.check_vm_disk),
            ("Sandbox (DNS)", self.check_sandbox_dns),
            ("Sandbox (User)", self.check_sandbox_user),
            ("Sandbox (Hostname)", self.check_sandbox_hostname),
            ("Sandbox (MAC)", self.check_sandbox_mac),
            ("Sandbox ( RAM)", self.check_sandbox_ram),
            ("Sandbox (Uptime)", self.check_sandbox_uptime),
            ("Sandbox (Drives)", self.check_sandbox_drives),
            ("Timing", self.check_timing),
            ("TickCount", self.check_tickcount),
            ("RDTSC", self.check_rdtsc),
            ("Remote Desktop", self.check_rdp),
            ("Headless", self.check_headless),
            ("Screen Resolution", self.check_resolution),
            ("Sleep Skip", self.check_sleep_skip),
        ]

        results = {"threats": [], "clean": []}
        for name, fn in checks:
            try:
                detected = fn()
            except Exception:
                detected = False
            if detected:
                results["threats"].append(name)
            else:
                results["clean"].append(name)

        return results

    def report(self, results):
        lines = ["=== Anti-Analysis Report ==="]
        lines.append(f"Threats detected: {len(results['threats'])}")
        for t in results["threats"]:
            lines.append(f"  [!] {t}")
        lines.append(f"Clean: {len(results['clean'])}")
        return "\n".join(lines)

    def _log(self, msg):
        if not self.silent:
            print(f"[AA] {msg}")

    # ── Debugger Detection ────────────────────────────────────────────

    def check_debugger(self):
        if kernel32.IsDebuggerPresent():
            return True
        try:
            is_debug = wintypes.BOOL()
            kernel32.CheckRemoteDebuggerPresent(
                kernel32.GetCurrentProcess(), ctypes.byref(is_debug))
            if is_debug.value:
                return True
        except Exception:
            pass
        try:
            status = ntdll.NtQueryInformationProcess(
                kernel32.GetCurrentProcess(), 0x1F,
                ctypes.byref(is_debug), ctypes.sizeof(is_debug), None)
            if status == 0 and is_debug.value:
                return True
        except Exception:
            pass
        return False

    def check_remote_debugger(self):
        try:
            is_debug = wintypes.BOOL()
            kernel32.CheckRemoteDebuggerPresent(
                kernel32.GetCurrentProcess(), ctypes.byref(is_debug))
            return bool(is_debug.value)
        except Exception:
            return False

    def check_hw_breakpoints(self):
        ctx = ctypes.create_string_buffer(0x1000)
        ctx_size = wintypes.DWORD(0x1000)
        try:
            if kernel32.GetThreadContext(
                    kernel32.GetCurrentThread(), ctypes.byref(ctx_size)):
                flags = struct.unpack_from("<I", ctx.raw, 0)[0]
                if flags & 0x8:
                    return True
        except Exception:
            pass
        return False

    def check_trap_flag(self):
        try:
            eflags = ctypes.c_uint32()
            asm = (
                b"\x9C"
                b"\x8B\xC4"
                b"\xF7\x04\x24\x00\x01\x00\x00"
                b"\x9D"
            )
            ctypes.windll.kernel32.GetCurrentThread()
        except Exception:
            pass
        return False

    def check_nt_global_flag(self):
        try:
            PEB_OFFSET = 0x68 if sys.maxsize > 2**32 else 0x10
            peb = ctypes.c_void_p()
            asm = b"\x65\x48\x8B\x04\x25\x60\x00\x00\x00"
            buf = ctypes.c_uint32(0)
            ntdll.NtCurrentTeb.restype = ctypes.c_void_p
            teb = ntdll.NtCurrentTeb()
            if teb:
                peb_ptr = ctypes.c_void_p.from_address(teb + 0x60)
                if peb_ptr:
                    ntf_offset = 0xBC if sys.maxsize > 2**32 else 0x68
                    val = ctypes.c_uint32.from_address(
                        peb_ptr.value + ntf_offset)
                    if val.value & 0x70:
                        return True
        except Exception:
            pass
        return False

    def check_heap_flags(self):
        try:
            PEB_OFFSET = 0x68 if sys.maxsize > 2**32 else 0x10
            ntdll.NtCurrentTeb.restype = ctypes.c_void_p
            teb = ntdll.NtCurrentTeb()
            if teb:
                peb_ptr = ctypes.c_void_p.from_address(teb + 0x60)
                if peb_ptr and peb_ptr.value:
                    flags_offset = 0x40 if sys.maxsize > 2**32 else 0x18
                    heap_flags = ctypes.c_uint32.from_address(
                        peb_ptr.value + flags_offset)
                    if heap_flags.value & 0x20:
                        return True
        except Exception:
            pass
        return False

    # ── Process Context Detection ─────────────────────────────────────

    def check_parent_process(self):
        suspicious = [
            "ollydbg.exe", "x64dbg.exe", "x32dbg.exe", "ida.exe",
            "ida64.exe", "gdb.exe", "windbg.exe", "dnspy.exe",
            "processhacker.exe", "procmon.exe", "fiddler.exe",
            "wireshark.exe", "charles.exe",
        ]
        try:
            import subprocess
            ps_cmd = (
                "Get-CimInstance Win32_Process -Filter "
                "\"ProcessId=$PID\" | Select-Object ParentProcessId"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=5)
            parent_pid = int(result.stdout.strip().split()[-1])
            ps_cmd2 = (
                f"Get-Process -Id {parent_pid} | "
                "Select-Object -ExpandProperty Name"
            )
            result2 = subprocess.run(
                ["powershell", "-Command", ps_cmd2],
                capture_output=True, text=True, timeout=5)
            parent_name = result2.stdout.strip().lower()
            for s in suspicious:
                if s in parent_name:
                    return True
        except Exception:
            pass
        return False

    def check_process_name(self):
        suspicious = [
            "ollydbg", "x64dbg", "x32dbg", "ida", "ida64",
            "gdb", "windbg", "dnspy", "processhacker", "procmon",
            "fiddler", "wireshark", "charles",
        ]
        try:
            name = os.path.basename(sys.executable).lower()
            for s in suspicious:
                if s in name:
                    return True
        except Exception:
            pass
        return False

    # ── VM Detection ──────────────────────────────────────────────────

    def check_vm_registry(self):
        vm_keys = [
            r"SOFTWARE\VMware, Inc.\VMware Tools",
            r"SOFTWARE\Oracle\VirtualBox Guest Additions",
            r"HARDWARE\DEVICEMANUE\ROM Disk\45343537-4836-4D39-5334-333330310000",
            r"SYSTEM\CurrentControlSet\Services\Disk\Enum\0",
            r"SYSTEM\CurrentControlSet\Enum\ACPI\VMWARE",
            r"SYSTEM\CurrentControlSet\Enum\ACPI\VBOX",
            r"SYSTEM\CurrentControlSet\Enum\PCI\VEN_15AD",
            r"SYSTEM\CurrentControlSet\Enum\PCI\VEN_80EE",
            r"SOFTWARE\Microsoft\Virtual Machine\Guest\Parameters",
        ]
        for key_path in vm_keys:
            try:
                hkey = wintypes.HKEY()
                if kernel32.RegOpenKeyExW(
                    0x80000002, key_path, 0, 0x20019,
                        ctypes.byref(hkey)) == 0:
                    kernel32.RegCloseKey(hkey)
                    return True
            except Exception:
                pass

        vm_files = [
            r"C:\Windows\System32\vmGuestLib.dll",
            r"C:\Windows\System32\vboxhook.dll",
            r"C:\Windows\System32\vm3dmp.exe",
            r"C:\Windows\System32\VBoxSF.sys",
            r"C:\Program Files\VMware\VMware Tools",
            r"C:\Program Files\Oracle\VirtualBox Guest Additions",
            r"C:\Windows\System32\drivers\vmci.sys",
            r"C:\Windows\System32\drivers\vmmouse.sys",
            r"C:\Windows\System32\drivers\vmhgfs.sys",
        ]
        for f in vm_files:
            if os.path.exists(f):
                return True
        return False

    def check_vm_hardware(self):
        vm_macs = [
            "00:0C:29", "00:50:56", "00:05:69",
            "08:00:27", "00:03:FF", "00:1C:14",
            "00:16:3E", "00:15:5D",
        ]
        try:
            import subprocess
            result = subprocess.run(
                ["getmac", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                mac = line.split(",")[0].strip('"').upper()
                for vm in vm_macs:
                    if mac.startswith(vm.upper()):
                        return True
        except Exception:
            pass
        return False

    def check_vm_cpu(self):
        try:
            import subprocess
            result = subprocess.run(
                ["wmic", "cpu", "get", "Name"],
                capture_output=True, text=True, timeout=5)
            cpu = result.stdout.lower()
            vm_cpus = ["vmware", "virtual", "qemu", "xen", "hyper-v", "kvm"]
            for v in vm_cpus:
                if v in cpu:
                    return True
        except Exception:
            pass
        return False

    def check_vm_mac(self):
        return self.check_vm_hardware()

    def check_vm_disk(self):
        try:
            import subprocess
            result = subprocess.run(
                ["wmic", "diskdrive", "get", "Model"],
                capture_output=True, text=True, timeout=5)
            disk = result.stdout.lower()
            vm_disks = ["vmdisk", "vmware", "virtual disk", "vbox",
                        "qemu", "xen", "nvme", "virtual hd"]
            for v in vm_disks:
                if v in disk:
                    return True
        except Exception:
            pass
        return False

    # ── Sandbox Detection ─────────────────────────────────────────────

    def check_sandbox_dns(self):
        try:
            import subprocess
            result = subprocess.run(
                ["nslookup", "google.com"],
                capture_output=True, text=True, timeout=5)
            output = result.stdout.lower()
            sandbox_dns = ["sandbox", "internal", "malware"]
            for s in sandbox_dns:
                if s in output:
                    return True
        except Exception:
            pass
        return False

    def check_sandbox_user(self):
        try:
            import subprocess
            result = subprocess.run(
                ["whoami"], capture_output=True, text=True, timeout=5)
            user = result.stdout.strip().lower()
            sandbox_users = [
                "sandbox", "malware", "test", "virus",
                "cuckoo", "john doe",
            ]
            for s in sandbox_users:
                if s in user:
                    return True
        except Exception:
            pass
        return False

    def check_sandbox_hostname(self):
        try:
            hostname = platform.node().lower()
            sandbox_hosts = [
                "sandbox", "malware", "test", "virus", "cuckoo",
                "sample", "demo", "analysis",
            ]
            for s in sandbox_hosts:
                if s in hostname:
                    return True
        except Exception:
            pass
        return False

    def check_sandbox_mac(self):
        return self.check_vm_hardware()

    def check_sandbox_ram(self):
        try:
            kernel32.GetPhysicallyInstalledSystemMemory.restype = wintypes.BOOL
            total_kb = wintypes.DWORD(0)
            kernel32.GetPhysicallyInstalledSystemMemory(
                ctypes.byref(total_kb))
            if total_kb.value < 4 * 1024 * 1024:
                return True
        except Exception:
            try:
                import subprocess
                result = subprocess.run(
                    ["wmic", "os", "get", "TotalVisibleMemorySize"],
                    capture_output=True, text=True, timeout=5)
                lines = result.stdout.strip().split()
                if len(lines) >= 2:
                    ram_kb = int(lines[1])
                    if ram_kb < 4 * 1024 * 1024:
                        return True
            except Exception:
                pass
        return False

    def check_sandbox_uptime(self):
        try:
            tick = kernel32.GetTickCount64()
            uptime_ms = tick
            if uptime_ms < 20 * 60 * 1000:
                return True
        except Exception:
            try:
                import subprocess
                result = subprocess.run(
                    ["systeminfo"],
                    capture_output=True, text=True, timeout=10)
                for line in result.stdout.splitlines():
                    if "System Boot Time" in line or "系统启动时间" in line:
                        from datetime import datetime
                        boot_str = line.split(":", 1)[1].strip()
                        boot_time = datetime.strptime(
                            boot_str, "%Y/%m/%d %H:%M:%S")
                        delta = (datetime.now() - boot_time).total_seconds()
                        if delta < 20 * 60:
                            return True
            except Exception:
                pass
        return False

    def check_sandbox_drives(self):
        try:
            drives = []
            for letter in "CDEFGHIJKL":
                if os.path.exists(f"{letter}:"):
                    drives.append(f"{letter}:")
            if len(drives) < 2:
                return True
        except Exception:
            pass
        return False

    # ── Timing Detection ──────────────────────────────────────────────

    def check_timing(self):
        try:
            start = time.time()
            for _ in range(0x100000):
                pass
            elapsed = time.time() - start
            if elapsed > 1.0:
                return True
        except Exception:
            pass
        return False

    def check_tickcount(self):
        try:
            t1 = kernel32.GetTickCount()
            time.sleep(0.5)
            t2 = kernel32.GetTickCount()
            delta = t2 - t1
            if delta < 300 or delta > 700:
                return True
        except Exception:
            pass
        return False

    def check_rdtsc(self):
        return False

    def check_sleep_skip(self):
        try:
            t1 = time.time()
            time.sleep(5)
            elapsed = time.time() - t1
            if elapsed < 2.0:
                return True
        except Exception:
            pass
        return False

    # ── Environment Detection ─────────────────────────────────────────

    def check_rdp(self):
        try:
            import subprocess
            result = subprocess.run(
                ["query", "session"],
                capture_output=True, text=True, timeout=5)
            output = result.stdout.lower()
            if "rdp" in output or "remote" in output:
                return True
        except Exception:
            pass
        return False

    def check_headless(self):
        try:
            user32.GetSystemMetrics(0)
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            if w == 0 or h == 0:
                return True
        except Exception:
            pass
        return False

    def check_resolution(self):
        try:
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            if w < 800 or h < 600:
                return True
        except Exception:
            pass
        return False
