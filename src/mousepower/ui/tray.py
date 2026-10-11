# -*- coding: utf-8 -*-
"""MousePower 托盘：数字 / 电池条双模式图标 + 悬停详情 + 低电量通知

图标颜色跟随「强调色」设置，与浮窗电池保持一致。
"""
import threading
import time

from PIL import Image, ImageDraw, ImageFont

from .theme import battery_color, hex_to_rgb

_RENDER = 256       # 高分辨率绘制后再缩放，小尺寸下更精致


def _font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "msyhbd.ttc",
                 "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _age_text(sec):
    """秒数 → 可读时长（用于提示"数据是多久以前的"）"""
    try:
        sec = float(sec)
    except (TypeError, ValueError):
        return "一段"
    if sec < 60:
        return "刚刚"
    if sec < 3600:
        return f"{int(sec // 60)} 分钟"
    if sec < 86400:
        return f"{int(sec // 3600)} 小时"
    return f"{int(sec // 86400)} 天"


def _bolt_polygon(cx, cy, w, h):
    """闪电图标的多边形顶点（与浮窗里的闪电同形状）"""
    bw, bh = w, h
    pts = [
        (cx + bw * 0.18, cy - bh / 2),
        (cx - bw * 0.50, cy + bh * 0.06),
        (cx - bw * 0.02, cy + bh * 0.06),
        (cx - bw * 0.22, cy + bh / 2),
        (cx + bw * 0.50, cy - bh * 0.10),
        (cx + bw * 0.02, cy - bh * 0.10),
    ]
    return [(int(x), int(y)) for x, y in pts]


def _ink_on(rgb):
    """底色上的纯黑/纯白文字色"""
    r, g, b = rgb
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return (0, 0, 0) if lum > 150 else (255, 255, 255)


def make_icon(style="number", percent=None, charging=False, offline=False,
              accent="#30d158", size=32):
    """托盘图标。style: number=数字块, battery=电池条

    充电时**画闪电、不显示数字**（与浮窗一致）—— 早期版本只是把底色换成
    强调色、数字照旧，从图标上根本看不出在充电。
    """
    S = _RENDER
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    accent_rgb = hex_to_rgb(accent)

    if offline:
        # 灰底 + 横杠（与数字块同尺寸，保证托盘里大小一致）
        d.rounded_rectangle([0, S * 0.10, S, S * 0.90],
                            radius=int(S * 0.24), fill=(128, 128, 132, 245))
        d.rounded_rectangle([S * 0.24, S * 0.46, S * 0.76, S * 0.56],
                            radius=int(S * 0.05), fill=(255, 255, 255, 255))
        out = img.resize((size, size), Image.LANCZOS)
        out.info.update(style=style, percent=None, charging=False,
                        offline=True)
        return out

    fill_rgb = hex_to_rgb(battery_color(percent, charging, accent))
    if charging:
        fill_rgb = accent_rgb

    if style == "battery":
        # 电池条：粗轮廓 + 内部填充（图形占满画布）
        lw = max(2, int(S * 0.065))
        pad = int(S * 0.02)
        cap_w = int(S * 0.12)
        x0, y0 = pad + lw, int(S * 0.23)
        x1, y1 = S - cap_w - pad - lw, int(S * 0.77)
        rad = int((y1 - y0) * 0.32)
        ink = (255, 255, 255, 255)
        d.rounded_rectangle([x0, y0, x1, y1], radius=rad,
                            fill=(0, 0, 0, 130))
        if percent is not None:
            iw = (x1 - x0) - 2 * lw
            fw = max(lw, int(iw * percent / 100))
            d.rounded_rectangle([x0 + lw, y0 + lw, x0 + lw + fw, y1 - lw],
                                radius=max(1, rad - lw),
                                fill=fill_rgb + (255,))
        d.rounded_rectangle([x0, y0, x1, y1], radius=rad, outline=ink,
                            width=lw)
        cy = (y0 + y1) / 2
        ch = (y1 - y0) * 0.44
        d.rectangle([x1 + lw, cy - ch / 2, x1 + cap_w + lw, cy + ch / 2],
                    outline=ink, width=lw)
        # 充电：电池内部叠一个闪电（24px 下也认得出来）
        if charging:
            d.polygon(_bolt_polygon((x0 + x1) / 2, cy,
                                    (x1 - x0) * 0.42, (y1 - y0) * 0.62),
                      fill=(255, 255, 255, 255))
    else:
        # 数字块：强调色圆角底 + 纯黑/纯白数字（占满画布）
        d.rounded_rectangle([0, S * 0.06, S, S * 0.94],
                            radius=int(S * 0.26),
                            fill=fill_rgb + (252,))
        if charging:
            # ⚠ 充电时**不显示数字**，改显示闪电（与浮窗行为一致；
            #   原来只是把底色换成强调色、数字照旧，根本看不出在充电）
            d.polygon(_bolt_polygon(S / 2, S * 0.52,
                                    S * 0.46, S * 0.62),
                      fill=(255, 255, 255, 255))
        else:
            txt = str(percent) if percent is not None else "--"
            f = _font(int(S * (0.60 if len(txt) <= 2 else 0.46)))
            d.text((S / 2, S * 0.51), txt, font=f,
                   fill=_ink_on(fill_rgb) + (255,), anchor="mm")
    out = img.resize((size, size), Image.LANCZOS)
    # 把渲染状态附在图上，便于测试断言（比"数白色像素"可靠得多：
    # 字形 "65" 的白像素其实比闪电还多，用像素判断会误判）
    out.info.update(style=style, percent=percent, charging=bool(charging),
                    offline=bool(offline))
    return out


class TrayIcon:
    """pystray 托盘封装（run_detached 由 main 负责时序）"""

    def __init__(self, cfg, on_refresh, on_settings, on_quit,
                 on_toggle_widget, on_move_position):
        import pystray
        self.cfg = cfg
        self._icon = pystray.Icon(
            "MousePower",
            icon=make_icon(),
            title="MousePower 启动中…",
            menu=pystray.Menu(
                pystray.MenuItem("立即刷新", on_refresh, default=True),
                pystray.MenuItem("移动位置", on_move_position),
                pystray.MenuItem("显示/隐藏浮窗", on_toggle_widget),
                pystray.MenuItem("设置…", on_settings),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", on_quit),
            ))
        self._pystray = pystray
        self._low_notified = False
        self._pending = None            # 托盘未就绪时缓存的最近一次更新
        self._ready = False             # 托盘窗口是否已就绪
        self._lock = threading.Lock()

    def start_detached(self):
        threading.Thread(target=self._run_wrapper, daemon=True).start()

    def _run_wrapper(self):
        """托盘线程入口：就绪后把启动早期缓存的更新补上

        run() 里 delay=0 的那次引导刷新可能早于托盘窗口建立，
        此时 Shell_NotifyIcon 会因 hWnd 为空而静默失败，
        图标与提示要等下一次刷新才正确。
        """
        try:
            self._icon.run_detached()
        except Exception:
            return
        # ⚠ 就绪检测必须放到**后台线程**里等：
        #   原实现在这里同步 sleep 最多 5 秒，期间 update() 只会往
        #   _pending 里塞、不刷新图标；而补发只做一次，若此时还没就绪
        #   就永久丢掉那次更新（用户遇到的现象：充电了托盘图标不变）。
        #   现在改成轮询到就绪为止，且 update() 在就绪后也会自行补发。
        threading.Thread(target=self._wait_ready, daemon=True).start()

    def _wait_ready(self, timeout=60.0):
        """等托盘窗口就绪，然后补发最近一次被缓存的更新"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if getattr(self._icon, "_hwnd", None):
                with self._lock:
                    self._ready = True
                    pending = self._pending
                    self._pending = None
                if pending is not None:
                    try:
                        self.update(*pending)
                    except Exception:
                        pass
                return
            time.sleep(0.05)

    def stop(self):
        try:
            self._icon.stop()
        except Exception:
            pass

    def refresh_menu(self):
        try:
            self._icon.update_menu()
        except Exception:
            pass

    def update(self, device_name, percent, charging, offline, stale=False,
               age_sec=None):
        style = self.cfg.get("tray.style", "number")
        accent = self.cfg.get("widget.accent", "#30d158")
        # 托盘窗口还没建立时先缓存，等就绪后由 _wait_ready 补发
        if not getattr(self._icon, "_hwnd", None):
            with self._lock:
                self._pending = (device_name, percent, charging, offline,
                                 stale, age_sec)
                self._ready = False
            return
        with self._lock:
            self._ready = True
        self._apply_icon(style, accent, device_name,
                         percent, charging, offline, stale, age_sec)

    def _apply_icon(self, style, accent, device_name, percent, charging,
                    offline, stale, age_sec):
        self._icon.icon = make_icon(style, percent, charging, offline,
                                    accent)
        if offline:
            self._icon.title = "MousePower: 未检测到鼠标"
        elif percent is None:
            self._icon.title = f"MousePower: {device_name}\n电量不可读"
        else:
            state = "充电中" if charging else "电量"
            line = f"MousePower: {device_name}\n{state} {percent}%"
            if stale:
                line += "（上次读数"
                line += f"·{_age_text(age_sec)}前）" if age_sec is not None \
                    else "）"
            self._icon.title = line

        # 低电量 toast（一轮只提醒一次）
        n = self.cfg.notify
        try:
            threshold = int(n.get("threshold", 20))
        except (TypeError, ValueError):
            threshold = 20
        try:
            enabled = bool(n.get("low_battery"))
        except Exception:
            enabled = False
        if enabled and percent is not None and not charging \
                and percent <= threshold:
            if not self._low_notified:
                self._low_notified = True
                try:
                    self._icon.notify(
                        f"{device_name} 电量仅剩 {percent}%，请及时充电",
                        "MousePower 低电量提醒")
                except Exception:
                    pass
        elif percent is not None and percent > threshold + 5:
            self._low_notified = False
