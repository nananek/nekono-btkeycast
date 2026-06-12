# btkeycast

Forward the local keyboard to an iPad (or any BLE central) as a Bluetooth LE
HID keyboard — the same mechanism a Magic Keyboard uses.

A persistent daemon (hosted as a waybar continuous-exec module) keeps the
BLE connection alive. Left-clicking the bar icon toggles a small overlay
popup below the bar's right edge; while it is visible, every key you type is
translated to HID input reports and notified to the connected central.
Closing the popup returns the keyboard to local use without dropping the
connection, so there is no reconnect delay the next time.

Note that the central hides its on-screen keyboard while a hardware keyboard
is connected — right-click the bar icon to disconnect (and reconnect) when
you want to use the device directly.

## How it works

- **HID over GATT (HOGP) peripheral** served entirely through the BlueZ D-Bus
  API (`GattManager1` / `LEAdvertisingManager1` / `AgentManager1`). No raw
  L2CAP sockets, no root, no `bluetoothd` configuration changes, and classic
  BR/EDR devices (game pads, earbuds) paired on the same adapter keep working.
- **Key capture via wlr-layer-shell** with keyboard-mode `exclusive`
  (gtk-layer-shell). While the popup is mapped the compositor routes all key
  events to it, so no evdev grabbing or `input` group membership is needed.
  Compositor keybindings keep working locally; the pointer is untouched.
- **Optional per-keyboard forwarding**: pin specific keyboards in the popup
  and only those are forwarded (EVIOCGRAB — their events never reach the
  compositor) while every other keyboard keeps working locally. Needs
  python-evdev and read access to `/dev/input` (`input` group).
- **Forward-target pinning**: pick one of the paired centrals in the popup;
  any other central that tries to use the keyboard service is disconnected.
  Selections persist in `~/.config/btkeycast/config.json`.
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
- python-evdev (optional — per-keyboard forwarding)

No pip dependencies.

## Install

On Arch with the `[nekono]` repository:

```bash
pacman -S nekono-btkeycast
```

From a checkout, no installation needed:

```bash
PYTHONPATH=src python -m btkeycast daemon
```

## Usage

```bash
btkeycast daemon     # run the persistent daemon (what waybar execs)
btkeycast toggle     # show/hide the capture popup; spawns the daemon if absent
btkeycast conn       # toggle the BLE connection (release / re-advertise)
```

The daemon prints a waybar JSON line on every state change
(`kbd OFF` / `kbd ...` advertising / `kbd UP` connected / `kbd→pad`
forwarding) and is controlled via signals (SIGUSR1 = popup, SIGUSR2 =
connection), which is what `toggle` / `conn` send.

First time: open the popup, then on the iPad go to Settings > Bluetooth and
select the advertised name (`<hostname>-kbd`). Reconnects are automatic
afterwards.

Waybar wiring:

```jsonc
"custom/btkeycast": {
    "return-type": "json",
    "exec": "btkeycast daemon",
    "exec-if": "which btkeycast",
    "on-click": "btkeycast toggle",
    "on-click-right": "btkeycast conn"
}
```

Style classes emitted: `off`, `adv`, `up`, `on`, `error`.

## Configuration

- `BTKEYCAST_ADAPTER` — Bluetooth adapter to use (e.g. `hci1`). Default:
  the first powered adapter. HOGP coexists with classic BT on one adapter,
  so picking your main adapter is fine.
- `~/.config/btkeycast/config.json` — written by the popup controls:
  `target` (BT address of the pinned central, `null` = first to connect)
  and `keyboards` (ids of pinned keyboards, `[]` = capture everything via
  the popup).

## Notes

- Keyboard only (no pointer forwarding).
- JIS keys (ろ, ¥, 変換, 無変換, カタカナひらがな, 半角/全角) are mapped to
  their USB HID international usages.
- Logs from detached instances go to `~/.cache/btkeycast.log`.
- waybar starts one exec per output on multi-monitor setups; the daemon
  flocks a pidfile so exactly one instance survives (the other bars show
  no widget).

## License

MIT
