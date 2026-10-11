# -*- coding: utf-8 -*-
"""统一的 Win32 / HID ctypes 声明

存在的意义（都是实测踩过的坑）：

1.  **必须声明 restype**。`ctypes.WinDLL("kernel32")` 的 `CreateFileW` 默认
    restype 是 `c_int`，失败时返回 **-1**（截断成 32 位）；而
    `wintypes.HANDLE(-1).value` 是 `0xFFFFFFFFFFFFFFFF`。于是
    `if h == INVALID_HANDLE` **恒为 False** —— 打开失败会被当成成功，
    更糟的是失败句柄会被缓存起来，本进程内再也不重试（拔插一次就永久读不到）。
    这里统一 `restype = wintypes.HANDLE`，并用 `is_invalid(h)` 判空。

2.  **NTSTATUS 不是 0 表示成功**。`HidP_GetValueCaps` /
    `HidP_GetUsageValue` 成功返回 `HIDP_STATUS_SUCCESS = 0x00110000`，
    与 0 比较会把成功当成失败（标准 HID 电池通道因此 100% 读不出电量）。

3.  **OVERLAPPED 必须活到 I/O 真正结束**。超时后只调 `CancelIo` 就返回，
    Python 回收结构体内存而内核仍可能写入 → 访问冲突。这里提供
    `cancel_and_wait()` 用 `CancelIoEx` + `GetOverlappedResult(..., True)`
    等内核收尾。
"""
import ctypes
from ctypes import wintypes

# ---------------------------------------------------------------- 常量
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_FLAG_OVERLAPPED = 0x40000000
OPEN_EXISTING = 3
ERROR_IO_PENDING = 997
ERROR_OPERATION_ABORTED = 995

HidP_Input = 0
HidP_Output = 1
HidP_Feature = 2

#: HidP_* 成功状态码（**不是 0**）
HIDP_STATUS_SUCCESS = 0x00110000
#: HID Battery System usage page
USAGE_PAGE_BATTERY = 0x85

# ---------------------------------------------------------------- DLL
kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
hid32 = ctypes.WinDLL("hid.dll")

# ---------------------------------------------------------------- 函数签名
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]

kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [
    wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]

kernel32.ResetEvent.restype = wintypes.BOOL
kernel32.ResetEvent.argtypes = [wintypes.HANDLE]

kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

kernel32.ReadFile.restype = wintypes.BOOL
kernel32.ReadFile.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]

kernel32.WriteFile.restype = wintypes.BOOL
kernel32.WriteFile.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]

kernel32.GetOverlappedResult.restype = wintypes.BOOL
kernel32.GetOverlappedResult.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
    wintypes.BOOL]

kernel32.CancelIoEx.restype = wintypes.BOOL
kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]

hid32.HidD_GetFeature.restype = wintypes.BOOL
hid32.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                  wintypes.DWORD]
hid32.HidD_SetFeature.restype = wintypes.BOOL
hid32.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                  wintypes.DWORD]
hid32.HidD_GetPreparsedData.restype = wintypes.BOOL
hid32.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE,
                                        ctypes.POINTER(ctypes.c_void_p)]
hid32.HidD_FreePreparsedData.restype = wintypes.BOOL
hid32.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid32.HidP_GetCaps.restype = ctypes.c_long          # NTSTATUS
hid32.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
# ⚠ HidP_*ValueCaps 的缓冲/计数一律用 addressof(...) 传地址，**不要**直接
#   传 ctypes 数组或结构体实例。实测：直接传数组时，即使调用本身返回成功，
#   进程也会在之后（GC / 退出阶段）抛 access violation；改用 addressof 后
#   完全正常。同理 HidD_FreePreparsedData 传 addressof(pp)。
hid32.HidP_GetValueCaps.restype = ctypes.c_long     # NTSTATUS
hid32.HidP_GetValueCaps.argtypes = [
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
hid32.HidP_GetUsageValue.restype = ctypes.c_long    # NTSTATUS
hid32.HidP_GetUsageValue.argtypes = [
    ctypes.c_int, ctypes.c_ushort, ctypes.c_ushort, ctypes.c_ushort,
    ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_ulong]


# ---------------------------------------------------------------- 结构体
class OVERLAPPED(ctypes.Structure):
    """与 Windows OVERLAPPED 对齐（x64 下 sizeof = 32）"""
    _fields_ = [("Internal", ctypes.POINTER(ctypes.c_ulong)),
                ("InternalHigh", ctypes.POINTER(ctypes.c_ulong)),
                ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort),
        ("UsagePage", ctypes.c_ushort),
        ("InputReportByteLength", ctypes.c_ushort),
        ("OutputReportByteLength", ctypes.c_ushort),
        ("FeatureReportByteLength", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 17),
        ("NumberLinkCollectionNodes", ctypes.c_ushort),
        ("NumberInputButtonCaps", ctypes.c_ushort),
        ("NumberInputValueCaps", ctypes.c_ushort),
        ("NumberInputDataIndices", ctypes.c_ushort),
        ("NumberOutputButtonCaps", ctypes.c_ushort),
        ("NumberOutputValueCaps", ctypes.c_ushort),
        ("NumberOutputDataIndices", ctypes.c_ushort),
        ("NumberFeatureButtonCaps", ctypes.c_ushort),
        ("NumberFeatureValueCaps", ctypes.c_ushort),
        ("NumberFeatureDataIndices", ctypes.c_ushort),
    ]


class HIDP_VALUE_CAPS(ctypes.Structure):
    """与 ddk/hidpi.h 的 HIDP_VALUE_CAPS 完全一致（x64 sizeof = 60）

    ⚠ 曾经的错误写法：`("Reserved2", c_ulong * 5)`（20 字节）应为
      `USHORT[5]`（10 字节）。错版 sizeof=68，LogicalMin 偏移到 52（正确 44），
      导致 HidP_GetValueCaps 填充的数据被整体错读、电量换算全是垃圾值。
    """
    _fields_ = [
        ("UsagePage", ctypes.c_ushort),          # +0
        ("ReportID", ctypes.c_ubyte),            # +2
        ("IsAlias", ctypes.c_ubyte),             # +3
        ("BitField", ctypes.c_ushort),           # +4
        ("LinkCollection", ctypes.c_ushort),     # +6
        ("Usage", ctypes.c_ushort),              # +8
        ("IsStringRange", ctypes.c_ubyte),       # +10
        ("IsDesignatorRange", ctypes.c_ubyte),   # +11
        ("IsAbsolute", ctypes.c_ubyte),          # +12
        ("HasNull", ctypes.c_ubyte),             # +13
        ("Reserved", ctypes.c_ushort),           # +14
        ("BitSize", ctypes.c_ulong),             # +16
        ("ReportCount", ctypes.c_ulong),         # +20
        ("Reserved2", ctypes.c_ushort * 5),      # +24  长度 10 字节
        #                                            +34 补 2 字节对齐
        ("UnitsExp", ctypes.c_ulong),            # +36
        ("Units", ctypes.c_ulong),               # +40
        ("LogicalMin", ctypes.c_long),           # +44
        ("LogicalMax", ctypes.c_long),           # +48
        ("PhysicalMin", ctypes.c_long),          # +52
        ("PhysicalMax", ctypes.c_long),          # +56
    ]                                            # sizeof = 60


# ---------------------------------------------------------------- 工具
#: 正确的 INVALID_HANDLE_VALUE（64 位全 F）
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def is_invalid(handle):
    """统一的句柄有效性判断

    ⚠ 失败句柄有两种表示，**都必须认**：
      · restype=c_int（ctypes 默认）时长整型 -1
      · restype=wintypes.HANDLE 时是无符号 0xFFFFFFFFFFFFFFFF
    只比较其中一种就会出现"打开失败被当成成功"。
    """
    if handle is None:
        return True
    try:
        v = int(handle)
    except (TypeError, ValueError):
        return True
    if v in (0, -1):
        return True
    # 64 位下 HANDLE 是无符号的，取低 32/64 位再比一次
    return (v & INVALID_HANDLE_VALUE) == INVALID_HANDLE_VALUE


def open_device(path, access=GENERIC_READ | GENERIC_WRITE,
                share=FILE_SHARE_READ | FILE_SHARE_WRITE,
                overlapped=False):
    """打开 HID 设备路径。失败返回 None（**不要**拿返回值去和 -1 比）"""
    flags = FILE_FLAG_OVERLAPPED if overlapped else 0
    h = kernel32.CreateFileW(path, access, share, None, OPEN_EXISTING,
                             flags, None)
    return None if is_invalid(h) else h


def close_handle(handle):
    """安全关闭句柄（对无效句柄调用是无害的 no-op）"""
    if not is_invalid(handle):
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass


#: usage page >= 该值即视为厂商自定义集合
VENDOR_USAGE_PAGE = 0xFF00


def is_vendor_collection(usage_page):
    """是否厂商自定义集合（0xFF00 及以上）"""
    try:
        return int(usage_page) >= VENDOR_USAGE_PAGE
    except (TypeError, ValueError):
        return False


def success(status):
    """NTSTATUS 是否表示成功（=0x00110000，不是 0）"""
    return status == HIDP_STATUS_SUCCESS


# ------------------------------------------------- 安全的 HID 解析封装
def get_preparsed(h):
    """取得 preparsed data 地址；失败返回 None"""
    pp = ctypes.c_void_p()
    if not hid32.HidD_GetPreparsedData(h, ctypes.byref(pp)) or not pp.value:
        return None
    return pp.value


def free_preparsed(addr):
    """释放 preparsed data（传地址，不传 c_void_p 对象）"""
    if addr:
        try:
            hid32.HidD_FreePreparsedData(addr)
        except Exception:
            pass


def get_caps(pp_addr):
    """返回 (HIDP_CAPS, ok)：同样用 addressof 传址"""
    caps = HIDP_CAPS()
    st = hid32.HidP_GetCaps(pp_addr, ctypes.addressof(caps))
    return caps, success(st)


def get_value_caps(pp_addr, report_type, max_count=64):
    """读 value caps，返回普通 Python 元组列表 [(page, rid, usage, lo, hi)]

    内部用原始字节缓冲 + addressof 传址 —— 直接传 ctypes 数组会让进程在
    之后崩溃（见文件顶部说明）。
    """
    out = []
    if max_count <= 0:
        return out
    raw = ctypes.create_string_buffer(
        ctypes.sizeof(HIDP_VALUE_CAPS) * max_count)
    cnt = ctypes.c_ulong(max_count)
    st = hid32.HidP_GetValueCaps(report_type, ctypes.addressof(raw),
                                 ctypes.addressof(cnt), pp_addr)
    if not success(st):
        return out
    n = min(int(cnt.value), max_count)
    arr = ctypes.cast(raw, ctypes.POINTER(HIDP_VALUE_CAPS))
    for i in range(max(0, n)):
        c = arr[i]
        out.append((int(c.UsagePage), int(c.ReportID), int(c.Usage),
                    int(c.LogicalMin), int(c.LogicalMax)))
    return out


def get_usage_value(pp_addr, report_type, usage_page, usage, report_buf,
                    report_len):
    """读某个 usage 的值；成功返回 int，失败返回 None"""
    val = ctypes.c_ulong(0)
    st = hid32.HidP_GetUsageValue(
        report_type, usage_page, 0, usage, ctypes.byref(val), pp_addr,
        ctypes.addressof(report_buf) if report_buf is not None else None,
        report_len)
    return int(val.value) if success(st) else None


def get_feature(handle, buf, length):
    """读 feature report（传地址，避免数组直接转换）"""
    return bool(hid32.HidD_GetFeature(handle, ctypes.addressof(buf), length))


def set_feature(handle, buf, length):
    """写 feature report（传地址）"""
    return bool(hid32.HidD_SetFeature(handle, ctypes.addressof(buf), length))


def get_value_caps_by_page(pp_addr, report_type, usage_page,
                           max_count=16):
    """只取某个 usage page 的 value caps —— **厂商页必须走这个入口**。

    ⚠ 实测：对 usage page >= 0xFF00 的厂商集合调用 `HidP_GetValueCaps`
      （全量枚举）会返回成功，但进程随后在 GC / 退出阶段抛
      access violation（本机 4 个厂商接口 100% 复现：0xFF00 / 0xFF02 /
      0xFF04）。改用 `HidP_GetSpecificValueCaps` 按 usage page 精确查询
      则完全正常，而且正是我们需要的语义。
    """
    fn = hid32.HidP_GetSpecificValueCaps
    fn.restype = ctypes.c_long
    fn.argtypes = [ctypes.c_int, ctypes.c_ushort, ctypes.c_ushort,
                   ctypes.c_ushort, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p]
    out = []
    if max_count <= 0:
        return out
    raw = ctypes.create_string_buffer(
        ctypes.sizeof(HIDP_VALUE_CAPS) * max_count)
    cnt = ctypes.c_ulong(max_count)
    st = fn(report_type, usage_page, 0, 0, ctypes.addressof(raw),
            ctypes.addressof(cnt), pp_addr)
    if not success(st):
        return out
    n = min(int(cnt.value), max_count)
    arr = ctypes.cast(raw, ctypes.POINTER(HIDP_VALUE_CAPS))
    for i in range(max(0, n)):
        c = arr[i]
        out.append((int(c.UsagePage), int(c.ReportID), int(c.Usage),
                    int(c.LogicalMin), int(c.LogicalMax)))
    return out


def read_overlapped(handle, event, size, timeout_ms):
    """Overlapped 读一帧。

    返回 (data, err)；成功时 err 为 None。
    超时/取消时会等内核真正收尾，避免 OVERLAPPED 提前释放。
    """
    ov = OVERLAPPED()
    ov.hEvent = event
    kernel32.ResetEvent(event)
    buf = (ctypes.c_ubyte * size)()
    got = wintypes.DWORD(0)
    if not kernel32.ReadFile(handle, buf, size, ctypes.byref(got),
                             ctypes.byref(ov)):
        err = ctypes.get_last_error()
        if err != ERROR_IO_PENDING:
            return None, f"ReadFile err={err}"
        if kernel32.WaitForSingleObject(event, timeout_ms) != 0:
            # 取消并**等它真正结束**，否则 ov 出栈后内核仍可能写这块内存
            cancel_and_wait(handle, ov, event)
            return None, f"timeout({timeout_ms}ms)"
        if not kernel32.GetOverlappedResult(handle, ctypes.byref(ov),
                                            ctypes.byref(got), False):
            return None, f"GetOverlappedResult err={ctypes.get_last_error()}"
    return bytes(buf[:got.value]), None


def cancel_and_wait(handle, ov, event, wait_ms=500):
    """取消指定 I/O 并等待内核完成（保证 OVERLAPPED 可以安全释放）"""
    try:
        kernel32.CancelIoEx(handle, ctypes.byref(ov))
    except Exception:
        try:
            kernel32.CancelIo(handle)
        except Exception:
            pass
    try:
        kernel32.WaitForSingleObject(event, wait_ms)
        got = wintypes.DWORD(0)
        kernel32.GetOverlappedResult(handle, ctypes.byref(ov),
                                     ctypes.byref(got), True)
    except Exception:
        pass
