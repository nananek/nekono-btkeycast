"""Layer-shell popup: capture window + control panel.

Two capture modes, decided by the daemon:

- EXCLUSIVE (default): wlr-layer-shell keyboard-mode EXCLUSIVE — while the
  popup is mapped the compositor routes every key event here (compositor
  keybindings still win, the pointer is untouched).
- grab: pinned keyboards are EVIOCGRAB-ed by capture.Capture, so this
  window takes no keyboard at all (keyboard-mode NONE) and the remaining
  keyboards keep working locally.

The popup also hosts the forward-target selector and the keyboard pin
list; both persist via config.py through daemon callbacks.
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
#hint, #access { color: #6272a4; font-size: 11px; }
label { color: #f8f8f2; font-size: 12px; }
checkbutton { color: #f8f8f2; font-size: 12px; }
button { background: #44475a; color: #f8f8f2; border: none;
         border-radius: 4px; padding: 4px 12px; }
button:hover { background: #6272a4; }
combobox button { padding: 2px 6px; }
'''

HINT_EXCLUSIVE = ('このポップアップが出ている間、全キーボードの入力を転送します\n'
                  '閉じても BLE 接続は維持 (切断はバーの右クリック or 下のボタン)')
HINT_GRAB = ('チェックしたキーボードだけを転送中 — 他のキーボードはローカルで使えます\n'
             '閉じると転送停止。BLE 接続は維持 (切断はバーの右クリック or 下のボタン)')


class Popup:
    """Capture window. Calls daemon callbacks for every control."""

    def __init__(self, on_close, on_disconnect, on_key, on_key_release,
                 on_target, on_keyboards):
        self.on_close = on_close
        self.on_disconnect = on_disconnect
        self.on_key = on_key
        self.on_key_release = on_key_release
        self.on_target = on_target
        self.on_keyboards = on_keyboards
        self.pressed = set()
        self._updating = False       # programmatic widget updates

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

        target_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                             spacing=8)
        target_row.pack_start(Gtk.Label(label='転送先:'), False, False, 0)
        self.target_combo = Gtk.ComboBoxText()
        self.target_combo.connect('changed', self._target_changed)
        target_row.pack_start(self.target_combo, True, True, 0)

        kbd_label = Gtk.Label(label='転送するキーボード (未選択 = 全部):')
        kbd_label.set_halign(Gtk.Align.START)
        self.kbd_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                               spacing=2)
        self.access_note = Gtk.Label(label='')
        self.access_note.set_name('access')
        self.access_note.set_line_wrap(True)

        self.hint = Gtk.Label(label=HINT_EXCLUSIVE)
        self.hint.set_name('hint')
        self.hint.set_justify(Gtk.Justification.CENTER)
        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btns.set_halign(Gtk.Align.CENTER)
        close = Gtk.Button(label='閉じる (転送停止)')
        close.connect('clicked', lambda *_: self.on_close())
        disconnect = Gtk.Button(label='切断')
        disconnect.connect('clicked', lambda *_: self.on_disconnect())
        btns.pack_start(close, False, False, 0)
        btns.pack_start(disconnect, False, False, 0)
        for w in (title, self.status, target_row, kbd_label, self.kbd_box,
                  self.access_note, self.hint, btns):
            box.pack_start(w, False, False, 0)
        self.win.add(box)

        self.win.connect('key-press-event', self._press)
        self.win.connect('key-release-event', self._release)
        self.win.connect(
            'delete-event', lambda *_: (self.on_close(), True)[1])

    # ---- control panel population

    def populate(self, centrals, target, keyboards, selected, access):
        """Rebuild the target list and the keyboard pin list."""
        self._updating = True
        self.target_combo.remove_all()
        self.target_combo.append('', '(最初に接続した機器)')
        for addr, name, connected in centrals:
            mark = ' ●' if connected else ''
            self.target_combo.append(addr, f'{name}{mark}')
        if not self.target_combo.set_active_id(target or ''):
            self.target_combo.set_active_id('')

        for child in self.kbd_box.get_children():
            self.kbd_box.remove(child)
        for did, name in keyboards:
            check = Gtk.CheckButton(label=name)
            check.set_active(did in selected)
            check.connect('toggled', self._keyboards_changed)
            check.device_id = did
            self.kbd_box.add(check)
        if not access:
            self.access_note.set_text(
                'キーボード個別選択には /dev/input の読み取り権限'
                ' (input グループ) が必要です')
        elif not keyboards:
            self.access_note.set_text('キーボードが見つかりません')
        else:
            self.access_note.set_text('')
        self.access_note.set_visible(bool(self.access_note.get_text()))
        self._updating = False

    def _target_changed(self, combo):
        if not self._updating:
            self.on_target(combo.get_active_id() or None)

    def _keyboards_changed(self, _check):
        if self._updating:
            return
        ids = [c.device_id for c in self.kbd_box.get_children()
               if c.get_active()]
        self.on_keyboards(ids)

    def set_grab_mode(self, grabbing):
        GtkLayerShell.set_keyboard_mode(
            self.win, GtkLayerShell.KeyboardMode.NONE if grabbing
            else GtkLayerShell.KeyboardMode.EXCLUSIVE)
        self.hint.set_text(HINT_GRAB if grabbing else HINT_EXCLUSIVE)

    # ---- visibility / status

    def show(self):
        self.win.show_all()
        self.access_note.set_visible(bool(self.access_note.get_text()))

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

    # ---- EXCLUSIVE-mode key capture

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
