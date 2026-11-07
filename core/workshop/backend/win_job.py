"""Windows Job Object ownership for one backend process tree.

Each backend runs in its own kill-on-close job. Terminating the job ends the
whole tree atomically; if the host process dies abruptly (for example
``taskkill /F`` from Electron), Windows closes the job handle and the tree
ends too. Jobs nest under an outer job such as the one ``start_all.py``
creates (Windows 8 and later).

每个后端运行在独立的“关闭即终止”作业对象中：终止作业即可结束整棵进程树；宿主
异常退出时系统关闭句柄，进程树随之结束。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_void_p),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32():  # type: ignore[no-untyped-def]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel


class WindowsJob:
    """One kill-on-close job object owning a backend process tree."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows job objects are only available on Windows")
        self._kernel = _kernel32()
        handle = self._kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            self._kernel.CloseHandle(handle)
            raise ctypes.WinError(error)
        self._handle: int | None = handle

    def assign(self, pid: int) -> None:
        if self._handle is None:
            raise OSError("job object is closed")
        process = self._kernel.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self._kernel.AssignProcessToJobObject(self._handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self._kernel.CloseHandle(process)

    def terminate(self, exit_code: int = 1) -> None:
        if self._handle is not None:
            self._kernel.TerminateJobObject(self._handle, exit_code)

    def close(self) -> None:
        if self._handle is not None:
            self._kernel.CloseHandle(self._handle)
            self._handle = None
