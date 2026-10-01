"""Ownership checks for requests crossing a Windows privilege boundary."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from helppack.english import text as msg


def assert_current_user_owns(path: Path) -> None:
    if os.name != "nt":
        raise OSError(msg('请求所有者验证仅支持 Windows'))
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi.EqualSid.restype = wintypes.BOOL
    advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise OSError(msg('无法验证当前 Windows 身份'))
    descriptor = ctypes.c_void_p()
    try:
        length = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))
        if not length.value:
            raise OSError(msg('无法读取当前用户 SID'))
        user = ctypes.create_string_buffer(length.value)
        if not advapi.GetTokenInformation(token, 1, user, length.value, ctypes.byref(length)):
            raise OSError(msg('无法读取当前用户 SID'))
        user_sid = ctypes.cast(user, ctypes.POINTER(ctypes.c_void_p))[0]
        owner = ctypes.c_void_p()
        code = advapi.GetNamedSecurityInfoW(str(path), 1, 1, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor))
        if code or not advapi.EqualSid(user_sid, owner):
            raise PermissionError(msg('请求必须属于当前用户；不支持用另一个管理员账户代执行'))
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        kernel.CloseHandle(token)
