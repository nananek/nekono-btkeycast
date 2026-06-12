"""Grab selected evdev keyboards and forward their key events.

Alternative to the layer-shell EXCLUSIVE capture: the pinned devices are
EVIOCGRAB-ed so their events never reach the compositor, while every other
keyboard keeps working locally. Requires read access to /dev/input
(= input group); without it list_keyboards() reports no devices and the
daemon falls back to the EXCLUSIVE popup capture.
"""

import glob
import os


def have_input_access():
    # uaccess ACL でゲームパッド等だけ読める環境があるので any() では駄目
    nodes = glob.glob('/dev/input/event*')
    return bool(nodes) and all(os.access(n, os.R_OK) for n in nodes)


def _evdev():
    try:
        import evdev
        return evdev
    except ImportError:
        return None


def device_id(dev):
    """Stable identity for config: serial if the device has one, else name."""
    return dev.uniq or dev.name


def list_keyboards():
    """[(id, display_name)] of plugged keyboards, [] if none readable."""
    evdev = _evdev()
    if evdev is None:
        return []
    out, seen = [], set()
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        keys = dev.capabilities().get(evdev.ecodes.EV_KEY, [])
        is_kbd = (evdev.ecodes.KEY_A in keys and evdev.ecodes.KEY_Z in keys
                  and evdev.ecodes.KEY_ENTER in keys)
        did = device_id(dev)
        dev.close()
        if is_kbd and did not in seen:
            seen.add(did)
            out.append((did, dev.name))
    return out


class Capture:
    """Owns the active grabs. Callbacks receive evdev keycodes."""

    def __init__(self, on_key, on_key_release):
        self.on_key = on_key
        self.on_key_release = on_key_release
        self.active = {}     # path -> (InputDevice, GLib source id, pressed)

    def start(self, ids):
        """Grab every device matching ids. Returns the number grabbed."""
        from gi.repository import GLib
        evdev = _evdev()
        self.stop()
        if evdev is None or not ids:
            return 0
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            if device_id(dev) not in ids:
                dev.close()
                continue
            try:
                dev.grab()
            except OSError:
                dev.close()
                continue
            src = GLib.io_add_watch(
                dev.fd, GLib.PRIORITY_DEFAULT,
                GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                self._readable, path)
            self.active[path] = (dev, src, set())
        return len(self.active)

    def stop(self):
        for path in list(self.active):
            self._drop(path)

    def _drop(self, path):
        from gi.repository import GLib
        dev, src, pressed = self.active.pop(path)
        GLib.source_remove(src)
        for code in pressed:     # 物理切断で押しっぱなしを残さない
            self.on_key_release(code)
        try:
            dev.ungrab()
        except OSError:
            pass
        try:
            dev.close()
        except OSError:
            pass

    def _readable(self, _fd, cond, path):
        from gi.repository import GLib
        import evdev
        if path not in self.active:
            return False
        if cond & (GLib.IO_HUP | GLib.IO_ERR):
            self._drop(path)
            return False
        dev, _src, pressed = self.active[path]
        try:
            events = list(dev.read())
        except OSError:
            self._drop(path)
            return False
        for ev in events:
            if ev.type != evdev.ecodes.EV_KEY:
                continue
            if ev.value == 1:
                pressed.add(ev.code)
                self.on_key(ev.code)
            elif ev.value == 0:
                pressed.discard(ev.code)
                self.on_key_release(ev.code)
            # value 2 (autorepeat) は送らない — repeat はホスト側が行う
        return True
