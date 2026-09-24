# -*- coding: utf-8 -*-
"""MousePower 托盘：数字 / 电池条双模式图标 + 悬停详情 + 低电量通知"""
import threading

from PIL import Image, ImageDraw, ImageFont

from .theme import battery_color, hex_to_rgb


def _font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_icon(style="number", percent=None, charging=False, offline=False,
              accent="#30d158"):
    """托盘图标 32x32。style: number=百分比数字, battery=电池格"""
    S = 64
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = battery_color(percent, charging, accent)
    if offline:
        d.rounded_rectangle([2, 14, S-2, S-14], radius=12,
                            fill=(120, 120, 120, 235))
        d.text((S//2, S//2-2), "–", font=_font(30),
               fill=(255, 255, 255, 255), anchor="mm")
        return img.resize((32, 32), Image.LANCZOS)

    if style == "battery":
        d.rounded_rectangle([2, 14, S-2, S-14], radius=12,
                            fill=(28, 28, 30, 240))
        # 电池格
        bx, by, bw, bh = 10, 24, 44, 18
        d.rounded_rectangle([bx, by, bx+bw, by+bh], radius=4,
                            outline=(255, 255, 255, 255), width=3)
        d.rectangle([bx+bw, by+5, bx+bw+5, by+bh-5],
                    fill=(255, 255, 255, 255))
        if percent is not None:
            fw = max(4, int((bw-6) * percent / 100))
            d.rounded_rectangle([bx+3, by+3, bx+2+fw, by+bh-3], radius=2,
                                fill=color)
        if charging:
            # 闪电
            pts = [(S//2+4, 12), (S//2-8, 34), (S//2+1, 34),
                   (S//2-4, 52), (S//2+10, 30), (S//2+1, 30)]
            d.polygon(pts, fill=(255, 255, 255, 255))
    else:
        bg = (28, 28, 30, 240) if not charging else (10, 90, 45, 245)
        d.rounded_rectangle([2, 14, S-2, S-14], radius=12, fill=bg)
        txt = str(percent) if percent is not None else "--"
        f = _font(40 if len(txt) <= 2 else 30)
        d.text((S//2, S//2-2), txt, font=f,
              fill=(255, 255, 255, 255), anchor="mm")
        if charging:
            d.ellipse([S-14, 16, S-2, 28], fill=(48, 209, 88, 255))
    return img.resize((32, 32), Image.LANCZOS)


class TrayIcon:
    """pystray 托盘封装（run_detached 由 main 负责时序）"""

    def __init__(self, cfg, on_refresh, on_settings, on_quit,
                 on_toggle_widget, on_toggle_click_through):
        import pystray
        self.cfg = cfg
        self._icon = pystray.Icon(
            "MousePower",
            icon=make_icon(),
            title="MousePower 启动中…",
            menu=pystray.Menu(
                pystray.MenuItem("立即刷新", on_refresh, default=True),
                pystray.MenuItem("显示/隐藏浮窗", on_toggle_widget),
                pystray.MenuItem(
                    "鼠标穿透（不遮挡点击）",
                    on_toggle_click_through,
                    checked=lambda item: bool(
                        self.cfg.get("widget.click_through"))),
                pystray.MenuItem("设置…", on_settings),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", on_quit),
            ))
        self._pystray = pystray
        self._low_notified = False

    def refresh_menu(self):
        """配置变化后刷新菜单勾选状态"""
        try:
            self._icon.update_menu()
        except Exception:
            pass

    def start_detached(self):
        threading.Thread(target=self._icon.run_detached, daemon=True).start()

    def stop(self):
        try:
            self._icon.stop()
        except Exception:
            pass

    def update(self, device_name, percent, charging, offline):
        style = self.cfg.get("tray.style", "number")
        self._icon.icon = make_icon(style, percent, charging, offline,
                                    self.cfg.get("widget.accent"))
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
