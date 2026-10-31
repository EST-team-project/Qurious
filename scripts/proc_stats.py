"""자식 프로세스(와 그 손자)가 쓴 CPU 시간 — 단계가 계산에 묶였는지, 기다림에 묶였는지 가리는 재료 (할 일 P1 · 설계 가설 H2 · H5 · 2026-10-31).

러너는 단계를 자식 프로세스로 돌린다. 걸린 시간(벽시계)만 알면 그 단계가 CPU 를 쓰느라 오래 걸리는지(받아올 네트워크 기다림이나
디스크 기다림이 아니라) 모른다. **CPU 초 ÷ 걸린 초** 가 1 에 가까우면 한 코어를 꽉 쓰는 계산(→ 쪼개 여러 코어로 나눌 후보),
0.3 아래면 기다림(→ 동시에 여러 요청을 보내는 쪽이 이득), 1 을 넘으면 이미 여러 코어를 쓴다.

**왜 작업 개체(Job Object)인가** — 가상환경의 ``python.exe`` 는 진짜 인터프리터를 다시 띄우는 얇은 껍데기라, 자식 프로세스 핸들 하나만 읽으면
계산 단계도 0.06 초로 나온다(2026-10-31 시험이 잡았다). 자식을 작업 개체에 넣어 두면 껍데기 아래 손자까지 합친 시간(``TotalUserTime`` +
``TotalKernelTime``)을 끝난 뒤에도 읽을 수 있다. 표준 라이브러리(ctypes)만 쓴다 — psutil 없이.

한계: 붙이는 순간(``Popen`` 이 돌아온 직후, 수 ms) 앞에 껍데기가 이미 손자를 띄웠다면 그 손자는 빠진다(실측에서는 없었다). Windows 가
아니거나 붙이지 못하면 ``None`` — 기록 칸이 그냥 비는 것이지 오류가 아니다. 재는 일이 단계를 깨면 안 되므로 어떤 예외도 밖으로 내보내지 않는다.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1


class CpuMeter:
    """자식 하나를 담는 작업 개체 — ``attach`` → (자식이 돎) → ``seconds`` → ``close``."""

    def __init__(self, job, k32) -> None:
        self._job, self._k32 = job, k32

    @classmethod
    def attach(cls, proc) -> Optional["CpuMeter"]:
        """방금 띄운 ``Popen`` 을 작업 개체에 넣는다 — 못 하면 ``None``(Windows 가 아님 · 이미 끝남 · 이미 다른 작업 개체가 막음)."""
        if os.name != "nt" or not isinstance(proc, subprocess.Popen):    # 엉뚱한 객체의 핸들(-1 = 내 자신)을 넣지 않는다
            return None
        job = None
        try:
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            k32.CreateJobObjectW.restype = ctypes.c_void_p
            k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            k32.AssignProcessToJobObject.restype = wintypes.BOOL
            k32.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                      ctypes.POINTER(wintypes.DWORD)]
            k32.QueryInformationJobObject.restype = wintypes.BOOL
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            job = k32.CreateJobObjectW(None, None)
            if not job:
                return None
            if not k32.AssignProcessToJobObject(job, int(proc._handle)):
                k32.CloseHandle(job)
                return None
            return cls(job, k32)
        except Exception:  # noqa: BLE001
            try:
                if job:
                    k32.CloseHandle(job)
            except Exception:  # noqa: BLE001
                pass
            return None

    def seconds(self) -> Optional[float]:
        """지금까지 이 작업 개체의 프로세스들이 쓴 CPU 초(사용자 + 커널) — 끝난 프로세스 몫도 들어 있다."""
        try:
            import ctypes
            from ctypes import wintypes

            class Accounting(ctypes.Structure):
                _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
                            ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                            ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                            ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

            info = Accounting()
            if not self._k32.QueryInformationJobObject(self._job, _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION, ctypes.byref(info),
                                                       ctypes.sizeof(info), None):
                return None
            return round((info.TotalUserTime + info.TotalKernelTime) / 1e7, 2)      # 100ns 단위
        except Exception:  # noqa: BLE001
            return None

    def close(self) -> None:
        try:
            self._k32.CloseHandle(self._job)
        except Exception:  # noqa: BLE001
            pass
        self._job = None


def measure(proc) -> Optional[CpuMeter]:
    """``CpuMeter.attach`` 의 짧은 이름 — 러너가 ``Popen`` 직후 부른다."""
    return CpuMeter.attach(proc)
