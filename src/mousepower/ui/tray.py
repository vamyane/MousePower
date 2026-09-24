# -*- coding: utf-8 -*-
"""MousePower 托盘：数字 / 电池条双模式图标 + 悬停详情 + 低电量通知

图标颜色跟随「强调色」设置，与浮窗电池保持一致。
"""
import threading

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


def _ink_on(rgb):
    """底色上的纯黑/纯白文字色"""
    r, g, b = rgb
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return (0, 0, 0) if lum > 150 else (255, 255, 255)


def make_icon(style="number", percent=None, charging=False, offline=False,
              accent="#30d158", size=32):
    """托盘图标。style: number=数字块, battery=电池条"""
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
        return img.resize((size, size), Image.LANCZOS)

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
    else:
        # 数字块：强调色圆角底 + 纯黑/纯白数字（占满画布）
        d.rounded_rectangle([0, S * 0.06, S, S * 0.94],
                            radius=int(S * 0.26),
                            fill=fill_rgb + (252,))
        txt = str(percent) if percent is not None else "--"
        f = _font(int(S * (0.60 if len(txt) <= 2 else 0.46)))
        d.text((S / 2, S * 0.51), txt, font=f,
               fill=_ink_on(fill_rgb) + (255,), anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


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

    def start_detached(self):
        threading.Thread(target=self._icon.run_detached, daemon=True).start()

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

    def update(self, device_name, percent, charging, offline):
        style = self.cfg.get("tray.style", "number")
        accent = self.cfg.get("widget.accent", "#30d158")
        self._icon.icon = make_icon(style, percent, charging, offline,
                                   accent)
        if offline:
            self._icon.title = "MousePower: 未检测到鼠标"
        elif percent is None:
            self._icon.title = f"MousePower: {device_name}\n电量不可读"
        else:
            state = "充电中" if charging else "电量"
            self._icon.title = f"MousePower: {device_name}\n{state} {percent}%"

        # 低电量 toast（一轮只提醒一次）
        n = self.cfg.notify
        if (n.get("low_battery") and percent is not None
                and not charging and percent <= n.get("threshold", 20)):
            if not self._low_notified:
                self._low_notified = True
                try:
                    self._icon.notify(
                        f"{device_name} 电量仅剩 {percent}%，请及时充电",
                        "MousePower 低电量提醒")
                except Exception:
                    pass
        elif percent is not None and percent > n.get("threshold", 20) + 5:
            self._low_notified = False
