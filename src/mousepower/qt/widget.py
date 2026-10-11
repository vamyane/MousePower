# -*- coding: utf-8 -*-
"""Qt 版浮窗：电池造型 + 逐像素透明 + 鼠标穿透

Qt 自带抗锯齿（QPainter.Antialiasing），不再需要 PIL 超采样贴图。
穿透用 Win32 扩展样式切换（避免 Qt 改窗口标志导致的闪烁）。
"""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen)
from PySide6.QtWidgets import QWidget

from ..ui.theme import palette, hex_to_rgb

#: 窗口尺寸（逻辑像素）。剪影是**竖长**的（鼠标 10:16 比例），
#: 所以窗口也跟着竖长，否则形状会被挤成细条、两侧留一大片空白。
#: 单格 ≈ 10:16，双格 ≈ 23:16。
SIZES = {
    "small":  (48, 44, 16),     # (宽, 高, 单格字号)
    "medium": (56, 52, 19),
    "large":  (68, 62, 23),
}

#: 双设备模式下每个半格的内容
_GAP = 3                  # 电池正极凸起宽度
_LW = 2                   # 轮廓线宽
_DIVIDER = 1              # 中间分隔线宽

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

_user32 = ctypes.WinDLL("user32", use_last_error=True)


def _fmt_age(sec):
    """把秒数写成"刚刚 / N 分钟 / N 小时"这类可读形式"""
    try:
        sec = float(sec)
    except (TypeError, ValueError):
        return "一段时间"
    if sec < 60:
        return "刚刚"
    if sec < 3600:
        return f"{int(sec // 60)} 分钟"
    if sec < 86400:
        return f"{int(sec // 3600)} 小时"
    return f"{int(sec // 86400)} 天"


def _contrast_white(h, s, v):
    """HSV 颜色与纯白的 WCAG 对比度（用于自动压明度）"""
    from PySide6.QtGui import QColor as _QC

    c = _QC()
    c.setHsv(h, s, v)
    r, g, b = c.redF(), c.greenF(), c.blueF()

    def lin(u):
        return u / 12.92 if u <= 0.03928 else ((u + 0.055) / 1.055) ** 2.4

    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return 1.05 / (lum + 0.05)


class BatteryWidget(QWidget):
    """电池浮窗"""

    def __init__(self, cfg, on_move_confirm=None, on_refresh=None,
                 on_settings=None, on_quit=None):
        super().__init__(None)
        self.cfg = cfg
        self.on_move_confirm = on_move_confirm
        self.on_refresh = on_refresh
        self.on_settings = on_settings
        self.on_quit = on_quit

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool |
                            Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.percent = None
        self.charging = False
        self.offline = False
        self.device_name = ""
        self.stale = False           # 显示的是"上次有效读数"而非刚读到的
        self.age_sec = None          # 该读数是多久以前的
        #: 两个格子的数据：mouse / keyboard
        self.slots = {
            "mouse": {"percent": None, "charging": False, "offline": True,
                      "device": "", "stale": False, "age_sec": None,
                      "supported": True},
            "keyboard": {"percent": None, "charging": False, "offline": False,
                         "device": "", "stale": False, "age_sec": None,
                         "supported": False},
        }
        self._move_mode = False
        self._drag_start = None
        self._confirm_rect = None
        self.apply_config()
        self._place()
        self._build_menu()

    # ---------- 配置 ----------
    def apply_config(self):
        w = self.cfg.get("widget")
        _w, _h, _fs = SIZES.get(w["size"], SIZES["medium"])
        self.W, self.H, self.fs_big = _w, _h, _fs
        self.setFixedSize(self.W, self.H)
        self.pal = palette(w["theme"])
        self.accent = w["accent"]
        self._opacity = float(w["opacity"])
        # 重锚定位置（尺寸变化后 corner 锚点必须重算），
        # _place → _apply_click_through 里同时会应用 setWindowOpacity
        self._place()
        self._refresh_paint()

    def _refresh_paint(self):
        """外观变化后立即把新外观落到屏幕上

        用户实测反馈：设置里改完强调色，**托盘立刻变色，浮窗不变**，
        得去拖一下窗口才变。

        原因：设置窗口（520×1153）打开时几乎必然**盖住**浮窗，而
        Windows 对被遮挡窗口会**推迟 WM_PAINT**；浮窗虽是置顶工具窗，
        被对话框压住时重绘同样会被延后到"重新可见"才发生（移动/置顶
        恰好会触发它，所以看起来像"移动一下才变"）。

        处理顺序：
          1. `repaint()` —— 同步重绘，把新外观画进窗口缓冲；
          2. `_raise_no_activate()` —— 用 SWP_NOACTIVATE 把浮窗抬到最前，
             使它不再被遮挡，被推迟的绘制才会真正落到屏幕上。
             用扩展样式保证它不会抢走设置窗口的焦点。
        """
        try:
            self.repaint()
        except Exception:
            try:
                self.update()
            except Exception:
                pass
        self._raise_no_activate()

    def _raise_no_activate(self):
        """把浮窗提到最前，但不激活、不抢焦点、不改位置尺寸"""
        try:
            hwnd = int(self.winId())
            if not hwnd:
                return
            HWND_TOPMOST = -1
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            _user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _place(self):
        """根据 corner / position 摆放（坐标一律夹到屏幕可用区）"""
        pos = self.cfg.get("widget.position")
        if pos and self._position_ok(pos):
            x, y = pos
        else:
            if pos:
                # 记忆位置已不在任何屏幕上（换显示器/改分辨率/拔副屏），
                # 回退到停靠角，否则浮窗会永远停在看不见的地方且拖不回来。
                self.cfg.set("widget.position", None)
            x, y = self._corner_position(
                self.cfg.get("widget.corner") or "br")
        self.move(int(x), int(y))
        self._apply_click_through(not self._move_mode)

    def _position_ok(self, pos):
        """坐标是否落在某个屏幕的可用区内（允许少量出血）"""
        try:
            x, y = int(pos[0]), int(pos[1])
        except (TypeError, ValueError, IndexError):
            return False
        from PySide6.QtWidgets import QApplication
        for scr in QApplication.screens():
            g = scr.availableGeometry()
            if (g.left() - 40 <= x <= g.right() - 20
                    and g.top() - 10 <= y <= g.bottom() - 10):
                return True
        return False

    def _corner_position(self, corner):
        """计算停靠角坐标（基于当前屏幕可用区）"""
        scr = self.screen().availableGeometry()
        m = 18
        return {
            "tl": (scr.left() + m, scr.top() + m),
            "tr": (scr.right() - self.W - m, scr.top() + m),
            "bl": (scr.left() + m, scr.bottom() - self.H - m),
            "br": (scr.right() - self.W - m, scr.bottom() - self.H - m),
        }.get(corner, (scr.right() - self.W - m, scr.bottom() - self.H - m))

    def apply_position_corner(self, corner):
        """设置窗口选择停靠角后调用：清掉自由位置并归位"""
        self.cfg.set("widget.position", None)
        self.cfg.set("widget.corner", corner)
        x, y = self._corner_position(corner)
        self.move(int(x), int(y))

    def _apply_click_through(self, through):
        """用 Win32 扩展样式切换穿透（避免 Qt 改标志导致闪烁）"""
        try:
            hwnd = int(self.winId())
            ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ex |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            if through:
                ex |= WS_EX_TRANSPARENT
            else:
                ex &= ~WS_EX_TRANSPARENT
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
            self.setWindowOpacity(self._opacity)
        except Exception:
            pass

    # ---------- 数据 ----------
    def update_value(self, percent, charging, offline=False, device="",
                     stale=False, age_sec=None, kind="mouse"):
        """更新**左半边**（鼠标）的显示值 —— 兼容原有调用"""
        self.update_slot("mouse", percent, charging, offline, device,
                         stale=stale, age_sec=age_sec)

    def update_slot(self, kind, percent, charging, offline=False, device="",
                    stale=False, age_sec=None, supported=True,
                    device_age=None):
        """更新指定格子（mouse / keyboard）

        stale/age_sec：本次是"沿用上次有效读数"（读取失败）时置位。
        device_age   ：设备端该数值多久没变过 —— 接收器会缓存电量、查询
                       不会刷新它，所以"读到了"不等于"刚测的"，提示里要
                       如实说明，不能让用户以为数字卡住是软件的问题。
        """
        s = self.slots.setdefault(kind, {})
        s.update({
            "percent": percent,
            "charging": bool(charging),
            "offline": bool(offline),
            "device": device,
            "stale": bool(stale),
            "age_sec": age_sec,
            "supported": bool(supported),
            "device_age": device_age,
        })
        if kind == "mouse":
            # 老字段同步一份，托盘/其它地方还在读
            self.percent = percent
            self.charging = bool(charging)
            self.offline = bool(offline)
            self.device_name = device
            self.stale = bool(stale)
            self.age_sec = age_sec
        self._update_tooltip()
        self._refresh_paint()

    def slot(self, kind):
        return self.slots.get(kind) or {}

    def _update_tooltip(self):
        lines = []
        for kind, label in (("mouse", "鼠标"), ("keyboard", "键盘")):
            s = self.slots.get(kind)
            if not s:
                continue
            name = s.get("device") or label
            if s.get("offline"):
                state = "未检测到"
            elif s.get("percent") is None:
                state = ("电量不可读" if s.get("supported", True)
                         else "该设备不提供电量")
            elif s.get("charging"):
                # 充电是一等状态：此时显示的是"充电中"，
                # 不该再提示"显示 N 分钟前的读数"（那是按键值的措辞，
                # 会让人以为数据坏了，其实设备正在充电）。
                state = f"充电中（{s['percent']}%）"
            else:
                state = f"电量 {s['percent']}%"
                if s.get("stale"):
                    if s.get("age_sec") is not None:
                        state += f"  ⚠ 显示 {_fmt_age(s['age_sec'])}前的读数"
                    else:
                        state += "  ⚠ 显示上次读数"
                elif s.get("device_age") is not None and s["device_age"] >= 600:
                    # 设备端该数值已 10 分钟以上没变 → 说明是接收器缓存，
                    # 不是在软件里卡住。如实告知，避免误判为"刷新失效"。
                    state += (f"  （设备已 {_fmt_age(s['device_age'])}未上报"
                              f"新值，属接收器缓存）")
            lines.append(f"{name}\n  {state}")
        self.setToolTip("\n".join(lines) if lines else "")

    def show_keyboard(self):
        """是否显示键盘那半格：一旦见过键盘设备就显示"""
        return bool(self.cfg.get("widget.show_keyboard", True))

    def _visible_kinds(self):
        """当前要画的格子"""
        if not self.show_keyboard():
            return ["mouse"]
        return ["mouse", "keyboard"]

    # ---------- 右键菜单（仅移动模式可弹出）----------
    def _build_menu(self):
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu

        self._menu = QMenu(self)
        a = QAction("立即刷新", self)
        a.triggered.connect(lambda: self.on_refresh and self.on_refresh())
        self._menu.addAction(a)
        a = QAction("移动位置", self)
        a.triggered.connect(lambda: self.set_move_mode(True))
        self._menu.addAction(a)
        a = QAction("设置…", self)
        a.triggered.connect(lambda: self.on_settings and self.on_settings())
        self._menu.addAction(a)
        self._menu.addSeparator()
        a = QAction("退出", self)
        a.triggered.connect(lambda: self.on_quit and self.on_quit())
        self._menu.addAction(a)

    # ---------- 绘制 ----------
    def paintEvent(self, _e):
        """鼠标/键盘简笔画**本身就是电池**，没有外壳边框

        按用户要求：
          · 去掉原来的圆角电池外框与正极凸起；
          · 左边画鼠标剪影、右边画键盘剪影，剪影内部按高度填充电量；
          · 充电时填充内部显示闪电图标、**不显示百分比**；
          · 不充电时显示百分比。
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        kinds = self._visible_kinds()
        m = 2
        avail_w = self.W - m * 2
        avail_h = self.H - m * 2
        if len(kinds) == 1:
            boxes = [(m, m, m + avail_w, m + avail_h, kinds[0])]
        else:
            gap = 3
            each = (avail_w - gap) / 2
            boxes = [
                (m, m, m + each, m + avail_h, kinds[0]),
                (m + each + gap, m, m + avail_w, m + avail_h, kinds[1]),
            ]

        for x0, y0, x1, y1, kind in boxes:
            self._paint_silhouette(p, x0, y0, x1, y1, kind)

        # 移动模式：右上角 ✓
        self._confirm_rect = None
        if self._move_mode:
            bx1 = self.W - m
            by0 = m
            r = max(8, int(self.H * 0.26))
            gx = bx1 - r - 2
            gy = by0 + r + 2
            p.setPen(QPen(QColor("#ffffff"), 1))
            p.setBrush(QColor(self.accent))
            p.drawEllipse(int(gx - r), int(gy - r), r * 2, r * 2)
            pen2 = QPen(QColor("#ffffff"), 2)
            pen2.setCapStyle(Qt.RoundCap)
            pen2.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen2)
            from PySide6.QtCore import QPointF
            p.drawPolyline([QPointF(gx - r * 0.40, gy + r * 0.02),
                            QPointF(gx - r * 0.10, gy + r * 0.34),
                            QPointF(gx + r * 0.44, gy - r * 0.32)])
            self._confirm_rect = (gx - r, gy - r, gx + r, gy + r)

    #: 鼠标剪影的原始坐标空间（自绘连续曲线，见 _shape_path）
    _MOUSE_VIEW_W = 12.6
    _MOUSE_VIEW_H = 16.0
    _MOUSE_VIEW_X = 1.7

    def _shape_path(self, kind, x0, y0, x1, y1):
        """返回该设备的剪影路径

        鼠标：**一条连续曲线**画完 —— 顶部圆头 → 两侧饱满外扩 → 底部半圆
        收口，全程没有"直边接半圆"的拐点。
        （Bootstrap Icons 的 `mouse` 就是直边接半圆，交界处有明显折角，
          看起来发方；这里保留它的整体比例，曲线重新拟合过。
          比例参考 Bootstrap Icons `mouse`，MIT 许可。）
        """
        from PySide6.QtGui import QPainterPath, QTransform

        w = x1 - x0
        h = y1 - y0
        path = QPainterPath()
        if kind == "mouse":
            src = QPainterPath()
            src.moveTo(8.0, 0.0)
            src.cubicTo(4.35, 0.0, 1.7, 2.75, 1.7, 6.2)      # 左上圆头
            src.cubicTo(1.7, 9.6, 2.2, 12.6, 4.0, 14.6)       # 左侧缓收
            src.cubicTo(4.9, 15.5, 6.3, 16.0, 8.0, 16.0)      # 左下圆角
            src.cubicTo(9.7, 16.0, 11.1, 15.5, 12.0, 14.6)    # 右下圆角
            src.cubicTo(13.8, 12.6, 14.3, 9.6, 14.3, 6.2)     # 右侧回升
            src.cubicTo(14.3, 2.75, 11.65, 0.0, 8.0, 0.0)     # 右上圆头
            src.closeSubpath()

            # 等比缩放居中（保持 12.6:16 的原始比例，不拉伸）
            scale = min(w / self._MOUSE_VIEW_W, h / self._MOUSE_VIEW_H)
            tw = self._MOUSE_VIEW_W * scale
            th = self._MOUSE_VIEW_H * scale
            t = QTransform()
            t.translate(x0 + (w - tw) / 2.0 - self._MOUSE_VIEW_X * scale,
                        y0 + (h - th) / 2.0)
            t.scale(scale, scale)
            path = t.map(src)
        else:
            r = max(2.0, min(w, h) * 0.18)
            path.addRoundedRect(x0, y0, w, h, r, r)
        return path

    def _fill_color(self, pct, charging):
        """电量填充色：保证"白字可读"且"不同强调色仍可区分"

        `battery_color()` 按等级给出强调色 / 橙 / 红，但强调色往往很亮
        （如 #30d158），满电时整块剪影都是亮色、白字看不清（取消文字
        描边后尤其明显）。

        做法：**保留色相**，只把明度压到"与白字的 WCAG 对比度 ≥ 5.0"
        为止（AA 正文标准是 4.5）。
        ⚠ 不能无脑把亮度统一压到某个固定值 —— 那样 8 个强调色会糊成
          同一个暗色，用户改颜色就"看不出变化"了（实测踩过这个坑）。
        """
        from ..ui.theme import battery_color

        c = QColor(battery_color(pct, charging, self.accent))
        h, s, v, a = c.getHsv()
        s = max(s, 140)                     # 保证不至于糊成灰
        for _ in range(100):
            if _contrast_white(h, s, v) >= 5.0 or v <= 12:
                break
            v -= 2
        c.setHsv(h, s, v, a)
        return c

    def _paint_silhouette(self, p, x0, y0, x1, y1, kind):
        """画一个剪影：中性暗底 = 空电，内部按高度填充 = 电量

        ⚠ 不加描边。白描边在圆拱/圆角处会有明显抗锯齿锯齿（用户反馈
          "显得很 low"）。形状靠在桌面上的**明暗对比**立住：
          暗底（接近不透明的深灰）+ 彩色填充，两者色差足够读出来。
        """
        from ..ui.theme import battery_color

        s = self.slot(kind)
        pct = s.get("percent")
        offline = s.get("offline")
        supported = s.get("supported", True)
        charging = bool(s.get("charging")) and s.get("percent") is not None
        show_value = (not offline) and supported and pct is not None

        w = max(1.0, x1 - x0)
        h = max(1.0, y1 - y0)
        path = self._shape_path(kind, x0, y0, x1, y1)

        # 1) 剪影底色：不带描边，直接填充（空电部分就是这块暗色）
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(28, 28, 32, 235))
        p.drawPath(path)

        # 2) 内部按**高度**填充电量（裁剪在剪影内，不会溢出形状）
        if show_value:
            # ⚠ 用"固定亮度"而不是按电量变色：低级电量本来就转橙/红，
            #   若再叠加越满越亮的渐变，100% 时白字会压在亮色上看不清
            #   （取消文字描边后这个问题很明显）。这里按等级取色后统一
            #   压暗到同一亮度区间，保证白字始终可读。
            c = QColor(self._fill_color(pct, charging))
            p.save()
            p.setClipPath(path)
            fh = h * max(0.0, min(100, pct)) / 100.0
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRect(int(x0), int(y1 - fh), int(w) + 1, int(fh) + 1)
            p.restore()

        # 3) 细节笔画：鼠标的滚轮短线 + 按键分界（半透明白，不要硬边）
        p.setPen(QPen(QColor(255, 255, 255, 140), 1, Qt.SolidLine,
                      Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        if kind == "mouse":
            # 用与剪影同一套坐标变换定位，保证跟着形状走
            scale = min(w / self._MOUSE_VIEW_W, h / self._MOUSE_VIEW_H)
            tw = self._MOUSE_VIEW_W * scale
            th = self._MOUSE_VIEW_H * scale
            ox = x0 + (w - tw) / 2.0
            oy = y0 + (h - th) / 2.0

            def px(u):
                return int(ox + (u - self._MOUSE_VIEW_X) * scale)

            def py(v):
                return int(oy + v * scale)

            p.drawLine(px(8.0), py(3.2), px(8.0), py(5.4))    # 滚轮
            p.drawLine(px(3.6), py(4.8), px(12.4), py(4.8))   # 按键分界
        else:
            cols = max(3, int(w / 5))
            rows = 2
            for r_i in range(rows):
                for c_i in range(cols):
                    px_ = x0 + w * (c_i + 0.5) / cols
                    py_ = y0 + h * (0.32 + 0.32 * r_i)
                    p.drawPoint(int(px_), int(py_))

        # 4) 内容：充电显示闪电（不显电量），否则显示百分比
        #    ⚠ 文本框要用**剪影的实际包围盒**，不能用整格 —— 鼠标剪影比
        #      格子窄（等比缩放后居中），用格子宽会让数字溢出形状。
        sb = path.boundingRect()
        bx0, by0, bx1, by1 = sb.left(), sb.top(), sb.right(), sb.bottom()
        if charging:
            self._paint_bolt(p, bx0, by0, bx1, by1)
        elif show_value:
            self._paint_percent(p, bx0, by0, bx1, by1, pct)
        elif not supported:
            self._paint_text(p, bx0, by0, bx1, by1, "—")
        else:
            self._paint_text(p, bx0, by0, bx1, by1, "--")

    def _paint_bolt(self, p, x0, y0, x1, y1):
        """充电：剪影中央画一个闪电（充电时**不显示电量**）"""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainterPath
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        w = (x1 - x0)
        h = (y1 - y0)
        bw = w * 0.34
        bh = h * 0.52
        pts = [
            QPointF(cx + bw * 0.18, cy - bh / 2),
            QPointF(cx - bw * 0.50, cy + bh * 0.06),
            QPointF(cx - bw * 0.02, cy + bh * 0.06),
            QPointF(cx - bw * 0.22, cy + bh / 2),
            QPointF(cx + bw * 0.50, cy - bh * 0.10),
            QPointF(cx + bw * 0.02, cy - bh * 0.10),
        ]
        path = QPainterPath()
        path.moveTo(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawPath(path)

    def _font_for(self, px):
        f = QFont("Segoe UI", px, QFont.Bold)
        f.setPixelSize(px)
        return f

    def _draw_text_outlined(self, p, rect, text, font_px):
        """纯白文字，**不加描边**

        用户反馈描边"有锯齿显 low"，所以只保留白字身。
        可读性靠底色保证：剪影内部恒为暗色（空电）或已压暗的填充色，
        两者与白字对比都足够。
        """
        from PySide6.QtGui import QPainterPath

        path = QPainterPath()
        f = self._font_for(font_px)
        x, y, w, h = rect
        path.addText(0, 0, f, text)
        br = path.boundingRect()
        dx = x + (w - br.width()) / 2 - br.left()
        dy = y + (h - br.height()) / 2 - br.top()
        path.translate(dx, dy)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawPath(path)

    def _fit_font(self, rect_w, rect_h, txt, ratio_h=0.42):
        """按可用空间自动收缩字号，保证文字不溢出形状

        鼠标剪影是 10:16 的窄长形，字号只看高度一定会横向溢出，
        所以这里同时按宽度约束求解。
        """
        size = max(9, int(rect_h * ratio_h))
        for _ in range(12):
            f = self._font_for(size)
            w_num = QFontMetrics(f).horizontalAdvance(txt)
            f2 = self._font_for(max(7, int(size * 0.56)))
            w_pct = QFontMetrics(f2).horizontalAdvance("%")
            if w_num + w_pct <= rect_w * 0.94 or size <= 9:
                break
            size -= 1
        return size

    def _paint_percent(self, p, x0, y0, x1, y1, pct):
        """居中显示 65% 这样的大小数字混合（字号自适应形状）"""
        w = x1 - x0
        h = y1 - y0
        txt = str(pct)
        fpx = self._fit_font(w, h, txt)
        fs2 = max(7, int(fpx * 0.56))
        p.setFont(self._font_for(fpx))
        w1 = p.fontMetrics().horizontalAdvance(txt)
        p.setFont(self._font_for(fs2))
        w2 = p.fontMetrics().horizontalAdvance("%")
        total = w1 + w2
        tx = x0 + (w - total) / 2
        ty = y0 + h * 0.28
        th = h * 0.44
        self._draw_text_outlined(p, (tx, ty, w1 + 2, th), txt, fpx)
        self._draw_text_outlined(p, (tx + w1, ty + th * 0.10, w2 + 2,
                                     th * 0.90), "%", fs2)

    def _paint_text(self, p, x0, y0, x1, y1, text):
        w = x1 - x0
        h = y1 - y0
        fpx = self._fit_font(w, h, text)
        self._draw_text_outlined(p, (x0, y0 + h * 0.28, w, h * 0.44),
                                 text, fpx)

    # ---------- 交互（仅移动模式可点）----------
    def set_move_mode(self, on):
        self._move_mode = bool(on)
        self._apply_click_through(not self._move_mode)
        self.update()

    def mousePressEvent(self, e):
        if not self._move_mode:
            return
        if e.button() == Qt.RightButton:
            # 移动模式下（穿透已关闭）才能收到右键
            self._menu.popup(e.globalPosition().toPoint())
            return
        pos = e.position()
        rect = self._confirm_rect
        if rect and rect[0] <= pos.x() <= rect[2] and \
                rect[1] <= pos.y() <= rect[3]:
            self.set_move_mode(False)
            self.cfg.set("widget.position", [self.x(), self.y()])
            if self.on_move_confirm:
                self.on_move_confirm()
            return
        self._drag_start = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._move_mode and self._drag_start is not None:
            self.move(e.globalPosition().toPoint() - self._drag_start)

    def mouseReleaseEvent(self, _e):
        self._drag_start = None
