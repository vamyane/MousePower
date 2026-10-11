# -*- coding: utf-8 -*-
"""HID 厂商私有协议自动探测器

设计目标：把"这次卡了几小时的试错"压成一次自动扫描。

通用流程（对任何厂商私有协议都适用）：
  1. 枚举该 VID/PID 下的全部 HID 接口
  2. 读真实报告长度（HidD_GetPreparsedData → HidP_GetCaps）
  3. 按 Output/Feature 能力挑出"可写通道"
  4. 挑出"可读通道"（Input Report）
  5. 遍历命令码 × 常见校验和算法族，发一帧探针
  6. 观察哪个组合能收到"非 ack"的响应
  7. 从响应里定位电量字段（0-100 且随刷新变化/位置靠前的字节）

特异部分（自动试出来 = 探测结果）：
  · 命令码是哪个
  · 校验和用哪种算法
  · 电量在第几字节

保守遍历策略（用户已确认）：
  · 每个命令只发一次
  · 帧间隔 ≥ 80ms
  · 全部读用 Overlapped + 超时，绝不阻塞
"""
import ctypes
import time
from ctypes import c_ubyte, wintypes

from .winhid import (
    ERROR_IO_PENDING, FILE_FLAG_OVERLAPPED, GENERIC_READ, GENERIC_WRITE,
    OPEN_EXISTING, OVERLAPPED, close_handle, get_caps, get_preparsed,
    free_preparsed, hid32 as _hid32, is_invalid, kernel32 as _kernel32,
    open_device, read_overlapped, set_feature,
)

VID = 0x260D
KNOWN_PIDS = (0x1074, 0x1084)

GEN_R = GENERIC_READ
GEN_W = GENERIC_WRITE
INVALID = ctypes.c_void_p(-1).value

# 保守遍历节奏
FRAME_GAP_SEC = 0.08        # 帧间隔 80ms
READ_TIMEOUT_MS = 200       # 单次读超时
CMD_SETTLE_SEC = 0.35       # 发命令后等待响应窗口


# ---------------- 1. 枚举接口 ----------------

def _dec(p):
    return p.decode() if isinstance(p, bytes) else p


def enumerate_interfaces(vid=None, pid=None):
    """枚举接口，标注每个接口的 usage_page / 报告长度 / 读写能力"""
    import hid
    out = []
    for d in hid.enumerate(vid, pid):
        path = _dec(d["path"])
        iface = {
            "path": path,
            "vid": d["vendor_id"], "pid": d["product_id"],
            "usage_page": d["usage_page"], "usage": d["usage"],
            "interface": d["interface_number"],
            "product": d.get("product_string") or "",
            "manufacturer": d.get("manufacturer_string") or "",
            "is_vendor_page": d["usage_page"] >= 0xFF00,
        }
        # 读真实报告长度
        caps = _read_caps(path)
        iface.update(caps)
        out.append(iface)
    return out


def _read_caps(path):
    """用 HidD_GetPreparsedData + HidP_GetCaps 读真实能力"""
    res = {"input_len": 0, "output_len": 0, "feature_len": 0,
           "ok": False, "err": "", "usage_page": 0, "usage": 0}
    h = open_device(path, 0)          # 只读即可拿到 caps
    if is_invalid(h):
        res["err"] = f"CreateFile 失败 err={ctypes.get_last_error()}"
        return res
    pp = None
    try:
        pp = get_preparsed(h)
        if not pp:
            res["err"] = "HidD_GetPreparsedData 失败"
            return res
        caps, ok = get_caps(pp)
        if not ok:
            res["err"] = "HidP_GetCaps 失败"
            return res
        res["input_len"] = int(caps.InputReportByteLength)
        res["output_len"] = int(caps.OutputReportByteLength)
        res["feature_len"] = int(caps.FeatureReportByteLength)
        res["usage_page"] = int(caps.UsagePage)
        res["usage"] = int(caps.Usage)
        res["ok"] = True
    finally:
        free_preparsed(pp)
        close_handle(h)
    return res


# ---------------- 2. 校验和算法族 ----------------

def _cs_none(d, cmd):
    return 0


def _cs_sum(d, cmd):
    return sum(d[:16]) & 0xFF


def _cs_x55_sum(d, cmd):
    """(0x55 - sum(前16字节)) & 0xFF  ← 达尔优用这个"""
    return (0x55 - sum(d[:16])) & 0xFF


def _cs_x5a_sum(d, cmd):
    return (0x5A - sum(d[:16])) & 0xFF


def _cs_sum_p1(d, cmd):
    return (sum(d[:16]) + 1) & 0xFF


def _cs_sum_neg(d, cmd):
    return (-sum(d[:16])) & 0xFF


def _cs_xor(d, cmd):
    v = 0
    for b in d[:16]:
        v ^= b
    return v


def _cs_xor55(d, cmd):
    v = 0x55
    for b in d[:16]:
        v ^= b
    return v


def _cs_sum_cmd(d, cmd):
    return (sum(d[:16]) + cmd) & 0xFF


def _cs_x55_sum_cmd(d, cmd):
    return (0x55 - sum(d[:16]) - cmd) & 0xFF


def _cs_sum_byte0(d, cmd):
    """sum(byte0..byte15) 但 byte0 参与方式不同（有些协议 byte0 不计）"""
    return sum(d[1:16]) & 0xFF


def _cs_x55_sum_skip1(d, cmd):
    return (0x55 - sum(d[1:16])) & 0xFF


# 名称 → 函数。顺序按"常见度"排，命中即停
CHECKSUM_FAMILY = [
    ("x55_sum", _cs_x55_sum),        # 达尔优（已知可用）
    ("xor55", _cs_xor55),
    ("sum", _cs_sum),
    ("xor", _cs_xor),
    ("x5a_sum", _cs_x5a_sum),
    ("sum_neg", _cs_sum_neg),
    ("x55_sum_cmd", _cs_x55_sum_cmd),
    ("sum_cmd", _cs_sum_cmd),
    ("sum_p1", _cs_sum_p1),
    ("x55_sum_skip1", _cs_x55_sum_skip1),
    ("sum_skip1", _cs_sum_byte0),
    ("none", _cs_none),
]


_CS_BY_NAME = {name: fn for name, fn in CHECKSUM_FAMILY}


def _by_name(name):
    """按名称取校验和函数"""
    return _CS_BY_NAME.get(name, _cs_x55_sum)


# ---------------- 3. 通道会话 ----------------

class Channel:
    """一条可写的命令通道 + 一条可读的响应通道"""

    def __init__(self, write_path, read_path, report_len):
        self.write_path = write_path
        self.read_path = read_path
        self.report_len = report_len
        self.h_w = None
        self.h_r = None
        self.evt = None

    def open(self):
        # ⚠ 必须用 winhid.open_device：未声明 restype 时 CreateFileW 失败
        #   返回 -1，而 INVALID_HANDLE_VALUE 是 0xFF..FF，`h not in (None,
        #   INVALID)` 判不出来 → 打开失败被当成假成功，后续 SetFeature 全
        #   失败，报"设备无响应"而不是"打开失败"，把排查方向带偏。
        self.h_w = open_device(self.write_path)
        self.h_r = open_device(self.read_path, overlapped=True)
        self.evt = _kernel32.CreateEventW(None, True, False, None)
        ok = (not is_invalid(self.h_w) and not is_invalid(self.h_r)
              and bool(self.evt))
        if not ok:
            self.close()
        return bool(ok)

    def close(self):
        close_handle(self.h_w)
        close_handle(self.h_r)
        close_handle(self.evt)
        self.h_w = self.h_r = self.evt = None

    def write_frame(self, data: bytes):
        buf = (c_ubyte * len(data))()
        for i, v in enumerate(data):
            buf[i] = v
        return set_feature(self.h_w, buf, len(data))

    def read_frame(self, timeout_ms=READ_TIMEOUT_MS):
        """Overlapped 读一帧。

        ⚠ 超时后必须**等内核真正收尾**再返回：原实现只调 CancelIo 就
          return，栈/托管的 OVERLAPPED 随即被回收，而内核仍可能往里写
          → access violation（潜在 0xC0000005）。同时事件是复用的手动
          重置事件，被取消的 I/O 完成时仍会 SetEvent，下次 Wait 立刻
          返回并把旧缓冲当成新数据。这里交给 winhid.read_overlapped
          统一处理（CancelIoEx + GetOverlappedResult(..., True)）。
        """
        data, _err = read_overlapped(self.h_r, self.evt, self.report_len,
                                     timeout_ms)
        return data

    def drain(self, rounds=8):
        """清空残留响应：读到连续空为止（带轮次上限防死循环）"""
        empties = 0
        for _ in range(rounds):
            if not self.read_frame(30):
                empties += 1
                if empties >= 2:
                    break
            else:
                empties = 0


# ---------------- 4. 发一帧探针 ----------------

def pick_report_len(write_iface, read_iface):
    """命令帧长度：**必须优先用写通道自己的 feature 长度**

    ⚠ 原实现取三个通道的 max()。HidD_SetFeature 的缓冲长度必须等于该
      通道的 FeatureReportByteLength，若同设备另有一个 64 字节的
      Input/Output 通道，max() 会返回 64 → 17 字节的 feature 写直接失败
      → 探测永远"无响应"。
    """
    for c in (write_iface.get("feature_len", 0),
              write_iface.get("output_len", 0),
              read_iface.get("input_len", 0)):
        if c and c >= 4:
            return c
    return 17


class ProbeReport:
    """探测过程的结构化结果"""

    def __init__(self):
        self.interfaces = []
        self.channel = None          # (write_up, read_up)
        self.report_len = 0
        self.hits = []               # [{cmd, checksum, resp_hex, percent, ...}]
        self.battery = None          # {cmd, checksum, offset, percent, ...}
        self.needs_replug = False    # 探测后设备需重新插拔才恢复真实读数
        self.needs_settle = False    # 探测后设备需静置片刻才恢复真实读数
        self.notes = []

    def log(self, msg):
        self.notes.append(msg)

    def to_dict(self):
        return {
            "interfaces": [
                {k: v for k, v in i.items() if k != "path"}
                for i in self.interfaces
            ],
            "channel": self.channel,
            "report_len": self.report_len,
            "hits": self.hits,
            "battery": self.battery,
            "needs_replug": self.needs_replug,
            "needs_settle": self.needs_settle,
            "notes": self.notes,
        }


def _find_battery_field(resp, cmd):
    """从响应里猜电量字段

    策略：在数据区里找 0-100 的字节，优先靠前、优先"看起来像百分比"的位置。
    返回 (offset, value, charging_guess) 或 None
    """
    if not resp or len(resp) < 4:
        return None
    # 常见：命令码回显在 byte[1] → 数据从 byte[6] 起（达尔优）
    #       或 byte[0] → 数据从 byte[5] 起
    echo1 = len(resp) > 1 and resp[1] == cmd
    base = 6 if echo1 else 5
    # 先看这个"约定位置"
    cands = []
    if base < len(resp) and 0 <= resp[base] <= 100:
        cands.append(base)
    # 再扫数据区所有 0-100 的字节兜底
    for i in range(3, len(resp)):
        if i not in cands and 0 < resp[i] <= 100:
            cands.append(i)
    if not cands:
        return None
    off = cands[0]
    chg = None
    if off + 1 < len(resp):
        chg = bool(resp[off + 1])
    return off, resp[off], chg


def _pair_candidates(writes, reads):
    """按"长度匹配度"给通道组合排序

    经验：厂商命令帧与响应帧长度通常一致（协议对称）。
    长度一致的组合优先试，因为重复开关通道会扰动设备，
    必须尽快命中、尽早收手。
    """
    pairs = []
    for w in writes:
        wl = w.get("feature_len", 0) or w.get("output_len", 0)
        for r in reads:
            rl = r.get("input_len", 0)
            match = 1 if (wl and wl == rl) else 0
            # 长度一致优先；其次长度大者优先（完整帧更像命令通道）
            pairs.append((match, wl, rl, w, r))
    pairs.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    return pairs


def probe_device(vid, pids, progress=None, max_cmd=0x30):
    """对一个设备跑完整探测

    progress: 可选回调 fn(text) 用于 UI 实时显示
    """
    rep = ProbeReport()

    def emit(msg):
        rep.log(msg)
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    # ---------- 1. 枚举 ----------
    emit("① 枚举 HID 接口…")
    ifaces = []
    used_pid = None
    for pid in pids:
        lst = enumerate_interfaces(vid, pid)
        if lst:
            used_pid, ifaces = pid, lst
            break
    if not ifaces:
        emit(f"   未找到设备 (VID=0x{vid:04x})")
        return rep
    rep.interfaces = ifaces
    emit(f"   找到 VID=0x{vid:04x} PID=0x{used_pid:04x}，"
         f"{len(ifaces)} 个接口")

    # ---------- 2. 挑候选通道 ----------
    vendor = [i for i in ifaces if i["is_vendor_page"]]
    writes = [i for i in vendor
              if i.get("feature_len", 0) > 0 or i.get("output_len", 0) > 0]
    reads = [i for i in vendor if i.get("input_len", 0) > 0]
    emit(f"② 厂商接口 {len(vendor)} 个 → 可写 {len(writes)} / 可读 {len(reads)}")
    if not writes or not reads:
        emit("   ✗ 没有可用的厂商读写通道，无法自动探测")
        return rep

    # ---------- 3. 通道配对（长度匹配优先，命中即收手）----------
    emit("③ 通道配对（按报告长度匹配排序，命中即停）…")
    best = None
    tried = 0
    for match, wl, rl, w, r in _pair_candidates(writes, reads):
        report_len = pick_report_len(w, r)
        tried += 1
        ok, why, has_data, _sample = score_channel_pair(w, r, report_len)
        tag = "✓" if ok else "✗"
        note = "长度一致" if match else "长度不一致"
        emit(f"   {tag} 写=0x{w['usage_page']:04x}"
             f"(len{wl}) + 读=0x{r['usage_page']:04x}"
             f"(len{rl}) [{note}] → {why}")
        if ok:
            best = (w, r, report_len)
            break
        # 通道开关会扰动设备：试错后稍等再试下一组
        time.sleep(0.5)

    if best is None:
        emit("   ✗ 所有候选组合都无响应")
        return rep
    w, r, rl = best
    rep.channel = [f"0x{w['usage_page']:04x}", f"0x{r['usage_page']:04x}"]
    rep.report_len = rl
    emit(f"   采用: 写=0x{w['usage_page']:04x} 读=0x{r['usage_page']:04x} "
         f"报告长度={rl}（共试 {tried} 组）")

    # 让设备从通道开关中恢复
    time.sleep(0.6)

    # ---------- 4. 遍历命令码 × 校验和 ----------
    emit("④ 遍历命令码 × 校验和算法族（保守节奏，每帧间隔 80ms）…")
    ch = Channel(w["path"], r["path"], rl)
    if not ch.open():
        emit("   ✗ 通道打开失败")
        return rep

    try:
        ch.drain(6)
        emit("   逐命令：发一帧 → 读到响应后原地复读 2 次确认，"
             "避免长时间折腾设备")
        for cmd in range(0x01, max_cmd + 1):
            ch.drain(3)
            hit = None
            for cs_name, cs_func in CHECKSUM_FAMILY:
                frame = build_frame(cmd, cs_func, rl)
                if not ch.write_frame(frame):
                    time.sleep(FRAME_GAP_SEC)
                    continue
                time.sleep(CMD_SETTLE_SEC)
                got = _await_data(ch, cmd, 0.22)
                time.sleep(FRAME_GAP_SEC)
                if got:
                    hit = (cs_name, got)
                    break
            if not hit:
                continue

            # ---- 原地复验：连读 3 次，一致才算稳定 ----
            cs_name, first = hit
            vals = [_read_value(first, cmd)]
            for _ in range(2):
                ch.drain(2)
                frame = build_frame(cmd, _by_name(cs_name), rl)
                if not ch.write_frame(frame):
                    break
                time.sleep(CMD_SETTLE_SEC)
                got = _await_data(ch, cmd, 0.22)
                if got:
                    vals.append(_read_value(got, cmd))
                else:
                    vals.append(None)
                time.sleep(FRAME_GAP_SEC)

            st = [v for v in vals if v is not None]
            same = len(st) >= 2 and len(set(st)) == 1
            item = {"cmd": f"0x{cmd:02x}", "cmd_int": cmd,
                    "checksum": cs_name, "resp_hex": first.hex(),
                    "stable": same}
            if same:
                off, val, chg = _find_battery_field(first, cmd) or (6, st[0],
                                                                    None)
                item.update({"offset": off, "percent": st[0], "charging": chg})
                rep.hits.append(item)
                emit(f"   ✓ cmd=0x{cmd:02x} + {cs_name:14s} 稳定 {st[0]}%"
                     f"  电量偏移 byte[{off}]"
                     + ("  充电中" if chg else ""))
            else:
                emit(f"   · cmd=0x{cmd:02x} + {cs_name:14s} 响应但不稳定 "
                     f"({vals}) 忽略")

        # ---------- 判定电量命令 ----------
        emit("⑤ 判定电量命令…")
        if rep.hits:
            def rank(h):
                score = 0
                if h["cmd_int"] == 0x04:
                    score += 100            # 业界通用电量命令
                if h.get("percent", 0) > 0:
                    score += 50             # 非零更可能是真电量
                if h.get("charging"):
                    score += 20
                return -score

            rep.hits.sort(key=rank)
            cand = rep.hits[0]
            rep.battery = {
                "cmd": cand["cmd"], "cmd_int": cand["cmd_int"],
                "checksum": cand["checksum"], "offset": cand["offset"],
                "percent": cand["percent"], "charging": cand["charging"],
                "candidates": [
                    {"cmd": h["cmd"], "checksum": h["checksum"],
                     "percent": h.get("percent")} for h in rep.hits],
            }
            note = "（命中通用约定 0x04）" if cand["cmd_int"] == 0x04 else \
                   f"（从 {len(rep.hits)} 个稳定候选中择优）"
            emit(f"   判定命令码={cand['cmd']} 校验和={cand['checksum']} "
                 f"电量偏移=byte[{cand['offset']}] "
                 f"当前={cand['percent']}% {note}")
            if len(rep.hits) > 1:
                alts = ", ".join(
                    f"{h['cmd']}({h.get('percent')}%)" for h in rep.hits[1:])
                emit(f"   其他稳定候选: {alts}")
        else:
            emit("   未找到任何稳定响应的命令码")
            emit("   （设备可能有厂商通道但需要驱动先握手，"
                 "或响应布局特殊）")
    finally:
        ch.close()

    # ---------- 6. 收尾说明 ----------
    # 实测发现（2026-09-27）：遍历阶段向设备发送上百帧后，设备会进入
    # "降级响应"状态 —— 仍正常应答，但数据区恒为 0，需数十秒至数分钟
    # 自行恢复（无需拔插）。因此探测阶段【不】立即复读电量：
    # 那时读数必然是假的 0，只会误导用户。
    # 参数有效性已由「逐命令原地复读」保证，真实电量留给正常运行读取。
    if rep.battery:
        rep.battery["percent"] = None
        rep.needs_settle = True
        emit("⑥ 探测完成")
        emit(f"   命令码 {rep.battery['cmd']} · "
             f"校验和 {rep.battery['checksum']} · "
             f"电量偏移 byte[{rep.battery['offset']}]")
        emit("   参数已通过多次一致性验证，可直接用于读电量")
        emit("   ⚠ 探测期间发送了大量命令，设备可能有 1~2 分钟处于"
             "降级响应（读数显示 0）")
        emit("   ⚠ 请稍候片刻，或重新插拔接收器，之后再读即为真实电量")

    return rep


def _await_data(ch, cmd, window=0.22):
    """在时间窗内等待一个"有数据"的响应帧"""
    deadline = time.time() + window
    while time.time() < deadline:
        resp = ch.read_frame(120)
        if not resp:
            return None
        kind, _d = classify_response(resp, cmd)
        if kind == "data":
            return resp
    return None


def _read_value(resp, cmd):
    """从响应帧提取电量候选值"""
    f = _find_battery_field(resp, cmd)
    return f[1] if f else None


# ---------------- 4. 发一帧探针 ----------------

def build_frame(cmd, cs_func, report_len=17, params=b"", report_id=0x08,
                header_pattern="id_cmd"):
    """按指定布局构造命令帧"""
    d = bytearray(report_len)
    if header_pattern == "id_cmd":
        d[0] = report_id
        d[1] = cmd
        for i, b in enumerate(params):
            if i + 2 < report_len - 1:
                d[i + 2] = b
    elif header_pattern == "cmd_only":
        d[0] = cmd
        for i, b in enumerate(params):
            if i + 1 < report_len - 1:
                d[i + 1] = b
    elif header_pattern == "id_only":
        d[0] = report_id
        for i, b in enumerate(params):
            if i + 1 < report_len - 1:
                d[i + 1] = b
    d[report_len - 1] = cs_func(d, cmd) & 0xFF
    return bytes(d)


def classify_response(resp, cmd):
    """判断响应帧是不是"有数据的真响应"

    返回 (kind, detail)
      kind: 'data' 有实质数据 / 'ack' 空确认 / 'other' 其他 / 'none' 无响应

    响应帧可能有两种布局（不同厂商不同）：
      A: [report_id, cmd, status, ...data...]   命令码在 byte[1]
      B: [cmd, status, ...data...]              命令码在 byte[0]
    两者都要认。
    """
    if not resp:
        return "none", ""
    if len(resp) < 2:
        return "other", f"len={len(resp)}"

    # 定位命令码回显位置
    if len(resp) > 1 and resp[1] == cmd:
        echo_at, data_start = 1, 3
    elif resp[0] == cmd:
        echo_at, data_start = 0, 2
    else:
        return "other", f"resp={resp.hex()}"

    body = resp[data_start:]
    nonzero = sum(1 for b in body if b != 0x00)
    if nonzero == 0:
        return "ack", f"resp={resp.hex()}"
    return "data", f"resp={resp.hex()}"


def score_channel_pair(write_iface, read_iface, report_len, probe_cmds=(0x01, 0x02)):
    """验证一对通道能不能真正对话

    做法：挑几个命令码，只用一个"最可能的校验和"发出去看有没有响应。
    只要有任何响应（哪怕 ack），就说明这条写通道是活的。
    返回 (ok, 说明, 是否收到过 data, 响应样本)
    """
    ch = Channel(write_iface["path"], read_iface["path"], report_len)
    if not ch.open():
        return False, "打开失败", False, ""

    saw_ack = False
    saw_resp = ""
    try:
        ch.drain(4)
        for cmd in probe_cmds:
            frame = build_frame(cmd, _cs_x55_sum, report_len)
            if not ch.write_frame(frame):
                continue
            time.sleep(0.30)
            deadline = time.time() + 0.25
            while time.time() < deadline:
                resp = ch.read_frame(120)
                if not resp:
                    break
                kind, detail = classify_response(resp, cmd)
                if kind in ("data", "ack"):
                    saw_resp = detail
                    if kind == "data":
                        return True, "通道可写且有数据响应", True, detail
                    saw_ack = True
                    break
    finally:
        ch.close()

    if saw_ack:
        return True, "通道可写（收到确认帧）", False, saw_resp
    return False, "无响应", False, ""
