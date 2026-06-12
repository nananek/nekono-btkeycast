"""Layer-shell popup that captures all keyboard input while visible.

The window uses wlr-layer-shell keyboard-mode EXCLUSIVE, so while it is
mapped the compositor routes every key event here (compositor keybindings
still win, the pointer is untouched). No evdev grabbing, no privileges.

The popup is created once and shown/hidden by the daemon; hiding it returns
the keyboard to local use without touching the BLE connection.
"""

import gi

gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gdk, Gtk, GtkLayerShell  # noqa: E402

from . import KBD_NAME  # noqa: E402

CSS = b'''
window { background-color: rgba(40, 42, 54, 0.97); }
#title { color: #f8f8f2; font-size: 14px; font-weight: bold; }
#status { color: #f1fa8c; font-size: 13px; }
window.ready #status { color: #50fa7b; }
window.disabled #status { color: #6272a4; }
window.error #status { color: #ff5555; }
#hint { color: #6272a4; font-size: 11px; }
button { background: #44475a; color: #f8f8f2; border: none;
         border-radius: 4px; padding: 4px 12px; }
button:hover { background: #6272a4; }
'''


class Popup:
    """Capture window. Calls daemon callbacks for the two buttons."""

    def __init__(self, on_close, on_disconnect, on_key, on_key_release):
        self.on_close = on_close
        self.on_disconnect = on_disconnect
        self.on_key = on_key
        self.on_key_release = on_key_release
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
        GtkLayerShell.set_anchor(self.win, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.TOP, 6)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.RIGHT, 6)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_property('margin', 14)
        title = Gtk.Label(label=f'⌨ {KBD_NAME}')
        title.set_name('title')
        self.status = Gtk.Label(label='初期化中…')
        self.status.set_name('status')
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(44)
        hint = Gtk.Label(
            label='このポップアップが出ている間、キー入力は転送先へ送られます\n'
                  '閉じても BLE 接続は維持 (切断はバーの右クリック or 下のボタン)')
        hint.set_name('hint')
        hint.set_justify(Gtk.Justification.CENTER)
        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btns.set_halign(Gtk.Align.CENTER)
        close = Gtk.Button(label='閉じる (転送停止)')
        close.connect('clicked', lambda *_: self.on_close())
        disconnect = Gtk.Button(label='切断')
        disconnect.connect('clicked', lambda *_: self.on_disconnect())
        btns.pack_start(close, False, False, 0)
        btns.pack_start(disconnect, False, False, 0)
        box.pack_start(title, False, False, 0)
        box.pack_start(self.status, False, False, 0)
        box.pack_start(hint, False, False, 0)
        box.pack_start(btns, False, False, 0)
        self.win.add(box)

        self.win.connect('key-press-event', self._press)
        self.win.connect('key-release-event', self._release)
        self.win.connect(
            'delete-event', lambda *_: (self.on_close(), True)[1])

    def show(self):
        self.win.show_all()

    def hide(self):
        self.pressed.clear()
        self.win.hide()

    @property
    def visible(self):
        return self.win.get_visible()

    def set_status(self, text, css_class=None):
        ctx = self.win.get_style_context()
        for c in ('ready', 'error', 'disabled'):
            ctx.remove_class(c)
        if css_class:
            ctx.add_class(css_class)
        self.status.set_text(text)

    def _press(self, _w, event):
        code = event.hardware_keycode - 8
        if code not in self.pressed:        # drop GDK autorepeat
            self.pressed.add(code)
            self.on_key(code)
        return True

    def _release(self, _w, event):
        code = event.hardware_keycode - 8
        self.pressed.discard(code)
        self.on_key_release(code)
        return True
