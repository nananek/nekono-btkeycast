"""Layer-shell popup that captures all keyboard input while visible.

The window uses wlr-layer-shell keyboard-mode EXCLUSIVE, so the compositor
routes every key event here (compositor keybindings still win, the pointer is
untouched). No evdev grabbing, no extra privileges.
"""

import signal

import gi

gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

from . import KBD_NAME  # noqa: E402

CSS = b'''
window { background-color: rgba(40, 42, 54, 0.97); }
#title { color: #f8f8f2; font-size: 15px; font-weight: bold; }
#status { color: #f1fa8c; font-size: 13px; }
window.ready #status { color: #50fa7b; }
window.error #status { color: #ff5555; }
#hint { color: #6272a4; font-size: 11px; }
button { background: #44475a; color: #f8f8f2; border: none;
         border-radius: 4px; padding: 4px 12px; }
button:hover { background: #6272a4; }
'''


class Popup:
    def __init__(self, core):
        self.core = core
        self.pressed = set()

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.win = Gtk.Window()
        GtkLayerShell.init_for_window(self.win)
        GtkLayerShell.set_layer(self.win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(
            self.win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        GtkLayerShell.set_anchor(self.win, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.TOP, 60)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_property('margin', 16)
        title = Gtk.Label(label=f'⌨ {KBD_NAME} (BLE HID 転送)')
        title.set_name('title')
        self.status = Gtk.Label(label='初期化中…')
        self.status.set_name('status')
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(48)
        hint = Gtk.Label(
            label='このポップアップが出ている間、キー入力は転送先へ送られます\n'
                  '(コンポジタのキーバインドはローカル優先 / マウスは通常どおり)')
        hint.set_name('hint')
        hint.set_justify(Gtk.Justification.CENTER)
        close = Gtk.Button(label='切断して閉じる')
        close.connect('clicked', lambda *_: Gtk.main_quit())
        box.pack_start(title, False, False, 0)
        box.pack_start(self.status, False, False, 0)
        box.pack_start(hint, False, False, 0)
        box.pack_start(close, False, False, 0)
        self.win.add(box)

        self.win.connect('key-press-event', self.on_press)
        self.win.connect('key-release-event', self.on_release)
        self.win.connect('delete-event', lambda *_: Gtk.main_quit())
        core.on_state = self.set_state
        self.win.show_all()

    def set_state(self, state, detail=None):
        ctx = self.win.get_style_context()
        for c in ('ready', 'error'):
            ctx.remove_class(c)
        if state == 'advertising':
            text = (f'BLE 広告中 — 転送先の 設定 > Bluetooth で'
                    f'「{KBD_NAME}」を選択してください')
        elif state == 'connected':
            text = f'{detail} に接続 — ペアリング/購読待ち…'
        elif state == 'ready':
            ctx.add_class('ready')
            text = f'転送中 → {detail}'
        else:
            ctx.add_class('error')
            text = detail or 'エラー'
        self.status.set_text(text)

    def on_press(self, _w, event):
        code = event.hardware_keycode - 8
        if code not in self.pressed:        # drop GDK autorepeat
            self.pressed.add(code)
            self.core.press(code)
        return True

    def on_release(self, _w, event):
        code = event.hardware_keycode - 8
        self.pressed.discard(code)
        self.core.release(code)
        return True


def run_ui(core):
    """Show the popup and run the main loop until closed or signalled."""
    Popup(core)
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig,
                             lambda: (Gtk.main_quit(), False)[1])
    Gtk.main()
