"""크래시와 메모리 추적.

프로세스가 파이썬 예외 없이 강제 종료되면(exit -1) 화면에 아무것도 남지
않아 원인을 알 수 없다. 여기서 두 가지를 남긴다.

 - faulthandler: 네이티브 크래시(접근 위반 등)가 나면 C 레벨 위치를
   파일에 찍는다. 보이지 않던 크래시를 보이게 만든다.
 - 메모리 기록: 처리 중 프로세스 메모리와 시스템 여유 메모리를 남긴다.
   메모리 부족이 맞는지 아닌지를 추측이 아니라 숫자로 판단할 수 있다.
"""

from __future__ import annotations

import ctypes
import datetime
import faulthandler
import sys
from pathlib import Path
from typing import Optional, Tuple

LOG_NAME = "faceswap_log.txt"
_log_file = None
_log_path: Optional[Path] = None


def log_path() -> Path:
    return _log_path if _log_path else Path(LOG_NAME).resolve()


def start(folder: str | Path | None = None) -> Path:
    """로그를 열고 네이티브 크래시 추적을 켠다. 실패해도 앱은 계속 돌아간다."""
    global _log_file, _log_path
    base = Path(folder) if folder else Path(__file__).resolve().parent.parent
    _log_path = base / LOG_NAME
    try:
        _log_file = open(_log_path, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(_log_file)
    except Exception:
        _log_file = None
        return _log_path

    total, avail = system_memory_mb()
    write("=" * 60)
    write(f"앱 시작 · python {sys.version.split()[0]}")
    if total:
        write(f"시스템 메모리: 전체 {total:.0f} MB / 여유 {avail:.0f} MB")
    return _log_path


def write(message: str) -> None:
    """로그 한 줄. 실패해도 조용히 넘어간다 (로깅 때문에 죽으면 안 된다)."""
    if _log_file is None:
        return
    try:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        _log_file.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class _MEMSTATUS(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def process_memory_mb() -> Optional[float]:
    """이 프로그램이 쓰는 메모리(MB). Windows가 아니면 None."""
    try:
        c = _PMC()
        c.cb = ctypes.sizeof(_PMC)
        h = ctypes.windll.kernel32.GetCurrentProcess()
        if not ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
            return None
        return c.WorkingSetSize / (1024 * 1024)
    except Exception:
        return None


def system_memory_mb() -> Tuple[Optional[float], Optional[float]]:
    """(전체, 여유) 시스템 메모리 MB. Windows가 아니면 (None, None)."""
    try:
        m = _MEMSTATUS()
        m.dwLength = ctypes.sizeof(_MEMSTATUS)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return None, None
        return m.ullTotalPhys / (1024 * 1024), m.ullAvailPhys / (1024 * 1024)
    except Exception:
        return None, None


def memory_note() -> str:
    """로그에 붙일 메모리 한 줄."""
    used = process_memory_mb()
    total, avail = system_memory_mb()
    if used is None:
        return ""
    note = f"메모리 사용 {used:.0f} MB"
    if avail is not None:
        note += f" · 시스템 여유 {avail:.0f} MB"
    return note
