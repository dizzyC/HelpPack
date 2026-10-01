from __future__ import annotations

import ctypes
import platform
import uuid
from ctypes import wintypes

from helppack.english import text as msg

from ..english import label as display_label
from .investigation import Finding, Investigation, query, readable, rows
from .runner import CommandRunner


class Guid(ctypes.Structure):
    _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16), ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def default_volume() -> dict:
    if platform.system() != "Windows":
        raise NotImplementedError(msg('仅 Windows 支持原生默认端点音量读取'))
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    initialized = ole.CoInitializeEx(None, 0) >= 0
    ole.CoCreateInstance.argtypes = [ctypes.POINTER(Guid), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Guid), ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype = ctypes.c_long
    pointers = []
    def check(code):
        if code < 0:
            raise OSError(msg('音频接口不可用（HRESULT {0:X}）', code & 4294967295))
    def call(pointer, slot, types, *args):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(table[slot])(pointer, *args)
    try:
        enumerator = ctypes.c_void_p()
        check(ole.CoCreateInstance(ctypes.byref(Guid.parse("BCDE0395-E52F-467C-8E3D-C4579291692E")), None, 1,
                                   ctypes.byref(Guid.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")), ctypes.byref(enumerator)))
        pointers.append(enumerator)
        endpoint = ctypes.c_void_p()
        check(call(enumerator, 4, [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)], 0, 1, ctypes.byref(endpoint)))
        pointers.append(endpoint)
        volume = ctypes.c_void_p()
        check(call(endpoint, 3, [ctypes.POINTER(Guid), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
                   ctypes.byref(Guid.parse("5CDF2C82-841E-4546-9722-0CF74078229A")), 23, None, ctypes.byref(volume)))
        pointers.append(volume)
        level, mute = ctypes.c_float(), wintypes.BOOL()
        check(call(volume, 9, [ctypes.POINTER(ctypes.c_float)], ctypes.byref(level)))
        check(call(volume, 15, [ctypes.POINTER(wintypes.BOOL)], ctypes.byref(mute)))
        return {msg('默认多媒体端点音量百分比'): round(level.value * 100, 1), msg('静音'): bool(mute.value)}
    finally:
        for pointer in reversed(pointers):
            call(pointer, 2, [])
        if initialized:
            ole.CoUninitialize()


def classic_bluetooth() -> list[dict]:
    if platform.system() != "Windows":
        raise NotImplementedError()
    class SystemTime(ctypes.Structure):
        _fields_ = [("values", wintypes.WORD * 8)]
    class DeviceInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("address", ctypes.c_ulonglong), ("device_class", wintypes.DWORD),
                    ("connected", wintypes.BOOL), ("remembered", wintypes.BOOL), ("authenticated", wintypes.BOOL),
                    ("seen", SystemTime), ("used", SystemTime), ("name", wintypes.WCHAR * 248)]
    class Search(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("authenticated", wintypes.BOOL), ("remembered", wintypes.BOOL),
                    ("unknown", wintypes.BOOL), ("connected", wintypes.BOOL), ("inquiry", wintypes.BOOL),
                    ("timeout", ctypes.c_ubyte), ("radio", wintypes.HANDLE)]
    dll = ctypes.WinDLL("bthprops.cpl", use_last_error=True)
    dll.BluetoothFindFirstDevice.argtypes = [ctypes.POINTER(Search), ctypes.POINTER(DeviceInfo)]
    dll.BluetoothFindFirstDevice.restype = wintypes.HANDLE
    dll.BluetoothFindNextDevice.argtypes = [wintypes.HANDLE, ctypes.POINTER(DeviceInfo)]
    dll.BluetoothFindNextDevice.restype = wintypes.BOOL
    dll.BluetoothFindDeviceClose.argtypes = [wintypes.HANDLE]
    options, info = Search(), DeviceInfo()
    options.size, info.size = ctypes.sizeof(options), ctypes.sizeof(info)
    options.authenticated = options.remembered = options.connected = True
    options.inquiry = False  # Never start discovery or pairing.
    handle = dll.BluetoothFindFirstDevice(ctypes.byref(options), ctypes.byref(info))
    if not handle:
        error = ctypes.get_last_error()
        if error not in (0, 259):
            raise OSError(msg('经典蓝牙接口不可用'))
        return []
    found = []
    try:
        for _ in range(100):
            found.append({msg('名称'): info.name, msg('已配对'): bool(info.authenticated), msg('已记住'): bool(info.remembered), msg('当前连接标志'): bool(info.connected)})
            if not dll.BluetoothFindNextDevice(handle, ctypes.byref(info)):
                break
    finally:
        dll.BluetoothFindDeviceClose(handle)
    return found


def inspect_peripherals(kind: str, cancel, progress, runner=None) -> Investigation:
    if kind not in {"声音", "蓝牙", "打印机"}:
        raise ValueError(msg('外设类型无效'))
    runner = runner or CommandRunner()
    result = Investigation(display_label(kind) + " · " + msg('专项检查'))
    service_names = {"声音": "Audiosrv,AudioEndpointBuilder", "蓝牙": "bthserv", "打印机": "Spooler"}[kind]
    queries = [(msg('相关服务'), f"Get-Service -Name {service_names} | Select-Object Name,@{{n='State';e={{[string]$_.Status}}}}|ConvertTo-Json -Compress")]
    if kind == "蓝牙":
        queries.append((msg('蓝牙适配器/设备'), "Get-PnpDevice -Class Bluetooth -PresentOnly | Select-Object FriendlyName,Class,Status | ConvertTo-Json -Compress"))
        try:
            values = classic_bluetooth()
            result.findings.append(Finding(msg('经典蓝牙配对/连接'), "已读取" if values else "未获得设备", str(values)))
        except (OSError, NotImplementedError):
            result.findings.append(Finding(msg('经典蓝牙配对/连接'), "当前接口不支持", msg('不能根据 PnP 存在推断已配对/连接。')))
        result.recommendations.append(msg('经典蓝牙连接标志不保证音频配置文件已连接；此原生接口不覆盖所有 BLE 设备，BLE 配对状态无法验证时需查看 Windows 设置。'))
    elif kind == "声音":
        try:
            result.findings.append(Finding(msg('默认输出静音/音量'), "已读取", readable(default_volume())))
        except (OSError, NotImplementedError):
            result.findings.append(Finding(msg('默认输出静音/音量'), "无法验证", msg('没有可读的默认端点或接口权限受限。')))
        queries.append((msg('音频设备状态'), "Get-PnpDevice -Class AudioEndpoint -PresentOnly | Select-Object FriendlyName,Status | ConvertTo-Json -Compress"))
        result.recommendations.append(msg('输出设备与默认设备由界面列出；试听只在主动点击后播放低音量两秒声音，不调整系统音量或默认设备。'))
    else:
        queries.append((msg('打印机默认/离线/暂停'), "Get-CimInstance Win32_Printer | Select-Object Name,Default,WorkOffline,PrinterStatus,PrinterState | ConvertTo-Json -Compress"))
        queries.append((msg('打印队列（不读取文档名或所有者）'), "@(Get-Printer | ForEach-Object {$p=$_;Get-PrintJob -PrinterName $p.Name -ErrorAction Stop | Select-Object -First 30 @{n='Printer';e={$p.Name}},Id,JobStatus,TotalPages,PagesPrinted})|ConvertTo-Json -Compress"))
        result.recommendations.append(msg('PrinterState 的暂停位为 1；队列/脱机标志是系统快照，未检测到队列不证明实体打印成功。测试页会消耗纸张/墨粉，需选择真实打印机并单独确认。'))
    for index, (label, script) in enumerate(queries):
        if cancel.is_set():
            raise InterruptedError("已取消")
        progress(20 + index * 25, label)
        try:
            value = rows(query(runner, script, 25))
            if label == msg('打印机默认/离线/暂停'):
                for printer in value:
                    state = printer.get("PrinterState")
                    printer[msg('暂停标志')] = bool(state & 1) if isinstance(state, int) else "无法读取"
            result.findings.append(Finding(label, "已读取" if value else "未检测到记录", readable(value)))
        except (OSError, ValueError, TimeoutError) as exc:
            result.findings.append(Finding(label, "权限不足" if isinstance(exc, PermissionError) else "无法读取", type(exc).__name__))
    progress(100, msg('外设检查结束'))
    return result
