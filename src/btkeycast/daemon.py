"""Long-running daemon, designed to live as a waybar continuous-exec module.

Prints one waybar JSON line on every state change (like swaync-client -swb).
Control is signal based:

  SIGUSR1  toggle the capture popup (left click) — enables the connection
           if it was disabled
  SIGUSR2  toggle the BLE connection (right click) — releasing it lets the
           iPad show its on-screen keyboard again
  SIGTERM  clean shutdown (waybar restart, etc.)

waybar spawns the exec once per output, so startup goes through
acquire_instance_lock(): exactly one instance survives, siblings exit
silently (their bar simply shows no widget).
"""

import json
import os
import signal

from . import KBD_NAME, PROG, config
from .capture import Capture, have_input_access, list_keyboards
from .cli import acquire_instance_lock, notify


def run():
    lock = acquire_instance_lock()
    if lock is None:
        return       # 同じ waybar の別出力ぶん — 本体は既に居る

    import gi
    gi.require_version('Gdk', '3.0')
    gi.require_version('Gtk', '3.0')
    gi.require_version('GtkLayerShell', '0.1')
    from gi.repository import GLib, Gtk

    from .hog import Core
    from .ui import Popup

    try:
        core = Core()
    except SystemExit as e:
        notify(str(e))
        raise

    cfg = config.load()
    core.target = cfg['target']

    class Daemon:
        def __init__(self):
            self.core = core
            self.cfg = cfg
            self.conn_enabled = True
            self.last_line = None
            self.capture = Capture(on_key=core.press,
                                   on_key_release=core.release)
            self.popup = Popup(on_close=self.hide_popup,
                               on_disconnect=self.disconnect,
                               on_key=core.press,
                               on_key_release=core.release,
                               on_target=self.set_target,
                               on_keyboards=self.set_keyboards)
            core.on_change = self.refresh

        # ---- state -> display

        def state(self):
            if self.core.error:
                return 'error'
            if not self.conn_enabled:
                return 'disabled'
            if self.core.subscribed:
                return 'ready'
            if self.core.device_path:
                return 'connected'
            if self.core.adv_registered:
                return 'advertising'
            return 'starting'

        def refresh(self):
            state = self.state()
            dev = self.core.device_name or '?'
            capturing = self.popup.visible and state == 'ready'

            bar = {
                'error': ('kbd !', 'error', self.core.error),
                'disabled': ('kbd OFF', 'off',
                             '切断中 — 右クリックで接続を有効化'),
                'starting': ('kbd ...', 'adv', '初期化中'),
                'advertising': ('kbd ...', 'adv',
                                f'広告中 —「{KBD_NAME}」への接続待ち'
                                ' (右クリックで停止)'),
                'connected': ('kbd UP', 'up',
                              f'{dev} 接続中 — 左クリックで転送開始'),
                'ready': ('kbd UP', 'up',
                          f'{dev} 接続中 — 左クリックで転送開始'),
            }[state]
            if capturing:
                bar = ('kbd→pad', 'on', f'転送中 → {dev} — 左クリックで停止')
            line = json.dumps(
                {'text': bar[0], 'class': bar[1], 'tooltip': bar[2]},
                ensure_ascii=False)
            if line != self.last_line:
                self.last_line = line
                print(line, flush=True)

            popup_text = {
                'error': (self.core.error or 'エラー', 'error'),
                'disabled': ('切断中 — バー右クリック or 再表示で再接続',
                             'disabled'),
                'starting': ('初期化中…', None),
                'advertising': (f'広告中 — 転送先の 設定 > Bluetooth で'
                                f'「{KBD_NAME}」を選択してください', None),
                'connected': (f'{dev} に接続 — ペアリング/購読待ち…', None),
                'ready': (f'転送中 → {dev}', 'ready'),
            }[state]
            self.popup.set_status(*popup_text)

        # ---- controls

        def toggle_popup(self):
            if self.popup.visible:
                self.hide_popup()
            else:
                if not self.conn_enabled:
                    self.set_connection(True)
                self.popup.populate(centrals=self.core.paired_centrals(),
                                    target=self.cfg['target'],
                                    keyboards=list_keyboards(),
                                    selected=self.cfg['keyboards'],
                                    access=have_input_access())
                self._apply_capture()
                self.popup.show()
                self.refresh()
            return True

        def hide_popup(self):
            self.capture.stop()
            self.core.release_all()
            self.popup.hide()
            self.refresh()

        def _apply_capture(self):
            grabbed = self.capture.start(self.cfg['keyboards'])
            self.popup.set_grab_mode(grabbed > 0)

        def set_target(self, address):
            self.cfg['target'] = address
            config.save(self.cfg)
            self.core.set_target(address)

        def set_keyboards(self, ids):
            self.cfg['keyboards'] = ids
            config.save(self.cfg)
            if self.popup.visible:
                self._apply_capture()
                self.refresh()

        def toggle_connection(self):
            self.set_connection(not self.conn_enabled)
            return True

        def set_connection(self, enabled):
            self.conn_enabled = enabled
            if enabled:
                self.core.adv_on()
            else:
                self.capture.stop()
                self.core.release_all()
                self.core.adv_off()
            self.refresh()

        def disconnect(self):
            self.popup.hide()
            self.set_connection(False)

        def quit(self):
            Gtk.main_quit()
            return False

    daemon = Daemon()
    try:
        try:
            core.start()
        except SystemExit as e:
            notify(str(e))
            raise
        daemon.refresh()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1,
                             daemon.toggle_popup)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2,
                             daemon.toggle_connection)
        for sig in (signal.SIGTERM, signal.SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, daemon.quit)
        Gtk.main()
    finally:
        daemon.capture.stop()
        core.stop()
        try:
            # ロックは死ぬまで保持、中身だけ空に (unlink すると flock 待ちの
            # 兄弟と新規 open の間で inode が割れて二重起動し得る)
            lock.seek(0)
            lock.truncate()
        except OSError:
            pass
        # waybar側にOFF表示を残す (継続execが死んだ場合は最後の行が残るため)
        print(json.dumps({'text': 'kbd OFF', 'class': 'off',
                          'tooltip': f'{PROG} 停止中'}, ensure_ascii=False),
              flush=True)
