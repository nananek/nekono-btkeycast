# btkeycast

Forward the local keyboard to an iPad (or any BLE central) as a Bluetooth LE
HID keyboard — the same mechanism a Magic Keyboard uses.

A status-bar click opens a small overlay popup; while the popup is visible,
every key you type is translated to HID input reports and notified to the
connected central. Close the popup and the keyboard is local again (and the
central regains its on-screen keyboard, since the peripheral disconnects).

## How it works

- **HID over GATT (HOGP) peripheral** served entirely through the BlueZ D-Bus
  API (`GattManager1` / `LEAdvertisingManager1` / `AgentManager1`). No raw
  L2CAP sockets, no root, no `bluetoothd` configuration changes, and classic
  BR/EDR devices (game pads, earbuds) paired on the same adapter keep working.
- **Key capture via wlr-layer-shell** with keyboard-mode `exclusive`
  (gtk-layer-shell). While the popup is mapped the compositor routes all key
  events to it, so no evdev grabbing or `input` group membership is needed.
  Compositor keybindings keep working locally; the pointer is untouched.
- The HID service requires encryption (`encrypt-read`), which makes iOS pair
  automatically on first connect (Just Works); the device is then marked
  trusted for instant reconnects.

## Requirements

Wayland compositor with wlr-layer-shell (sway, etc.) and, as system packages:

- python (>= 3.11)
- python-dbus
- python-gobject
- gtk3
- gtk-layer-shell
- bluez (running `bluetoothd`)

No pip dependencies.

## Install

On Arch with the `[nekono]` repository:

```bash
pacman -S nekono-btkeycast
```

From a checkout, no installation needed:

```bash
PYTHONPATH=src python -m btkeycast run
```

## Usage

```bash
btkeycast            # run in the foreground (popup opens immediately)
btkeycast toggle     # start detached, or stop the running instance
btkeycast status     # waybar custom-module JSON ({"text": ..., "class": "on"|"off"})
```

First time: open the popup, then on the iPad go to Settings > Bluetooth and
select the advertised name (`<hostname>-kbd`). Subsequent opens reconnect
automatically.

Waybar wiring:

```jsonc
"custom/btkeycast": {
    "return-type": "json",
    "interval": "once",
    "signal": 8,
    "exec": "btkeycast status",
    "exec-if": "which btkeycast",
    "on-click": "btkeycast toggle"
}
```

The running instance refreshes the module with `SIGRTMIN+8` on start/stop.

## Configuration

- `BTKEYCAST_ADAPTER` — Bluetooth adapter to use (e.g. `hci1`). Default:
  the first powered adapter. HOGP coexists with classic BT on one adapter,
  so picking your main adapter is fine.

## Notes

- Keyboard only (no pointer forwarding).
- JIS keys (ろ, ¥, 変換, 無変換, カタカナひらがな, 半角/全角) are mapped to
  their USB HID international usages.
- Logs from detached instances go to `~/.cache/btkeycast.log`.

## License

MIT
