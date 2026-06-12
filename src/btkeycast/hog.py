"""HID-over-GATT (HOGP) keyboard peripheral on top of BlueZ D-Bus.

Everything runs unprivileged: the GATT application, LE advertisement and
pairing agent are plain D-Bus objects served to bluetoothd, so no raw L2CAP
sockets, no root, and no bluetoothd configuration changes. Classic BR/EDR
devices paired on the same adapter are unaffected.
"""

import os
import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

from . import KBD_NAME
from .keymap import KEYMAP, REPORT_MAP

BLUEZ = 'org.bluez'
OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
PROP_IFACE = 'org.freedesktop.DBus.Properties'
ADAPTER_IFACE = 'org.bluez.Adapter1'
DEVICE_IFACE = 'org.bluez.Device1'
GATT_MGR_IFACE = 'org.bluez.GattManager1'
GATT_SVC_IFACE = 'org.bluez.GattService1'
GATT_CHR_IFACE = 'org.bluez.GattCharacteristic1'
GATT_DSC_IFACE = 'org.bluez.GattDescriptor1'
ADV_MGR_IFACE = 'org.bluez.LEAdvertisingManager1'
ADV_IFACE = 'org.bluez.LEAdvertisement1'
AGENT_IFACE = 'org.bluez.Agent1'

APP_PATH = '/org/btkeycast/app'
ADV_PATH = '/org/btkeycast/adv0'
AGENT_PATH = '/org/btkeycast/agent'


def uuid16(x):
    return f'0000{x:04x}-0000-1000-8000-00805f9b34fb'


class Service(dbus.service.Object):
    def __init__(self, bus, index, uuid):
        self.path = f'{APP_PATH}/service{index}'
        self.uuid = uuid
        self.characteristics = []
        super().__init__(bus, self.path)

    def get_properties(self):
        return {GATT_SVC_IFACE: {
            'UUID': self.uuid,
            'Primary': dbus.Boolean(True),
            'Characteristics': dbus.Array(
                [c.path for c in self.characteristics], signature='o'),
        }}


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service, value=()):
        self.path = f'{service.path}/char{index}'
        self.uuid = uuid
        self.flags = flags
        self.service = service
        self.value = list(value)
        self.descriptors = []
        self.notifying = False
        service.characteristics.append(self)
        super().__init__(bus, self.path)

    def get_properties(self):
        return {GATT_CHR_IFACE: {
            'Service': dbus.ObjectPath(self.service.path),
            'UUID': self.uuid,
            'Flags': dbus.Array(self.flags, signature='s'),
            'Descriptors': dbus.Array(
                [d.path for d in self.descriptors], signature='o'),
        }}

    @dbus.service.method(GATT_CHR_IFACE, in_signature='a{sv}',
                         out_signature='ay')
    def ReadValue(self, options):
        self.on_access(options)
        return dbus.Array(self.value, signature='y')

    @dbus.service.method(GATT_CHR_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        self.on_access(options)
        self.value = list(value)

    def on_access(self, options):
        pass

    @dbus.service.method(GATT_CHR_IFACE)
    def StartNotify(self):
        self.notifying = True
        self.on_notify(True)

    @dbus.service.method(GATT_CHR_IFACE)
    def StopNotify(self):
        self.notifying = False
        self.on_notify(False)

    def on_notify(self, enabled):
        pass

    @dbus.service.signal(PROP_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def notify_value(self, value):
        if self.notifying:
            self.PropertiesChanged(
                GATT_CHR_IFACE,
                {'Value': dbus.Array(value, signature='y')}, [])


class Descriptor(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, chrc, value=()):
        self.path = f'{chrc.path}/desc{index}'
        self.uuid = uuid
        self.flags = flags
        self.chrc = chrc
        self.value = list(value)
        chrc.descriptors.append(self)
        super().__init__(bus, self.path)

    def get_properties(self):
        return {GATT_DSC_IFACE: {
            'Characteristic': dbus.ObjectPath(self.chrc.path),
            'UUID': self.uuid,
            'Flags': dbus.Array(self.flags, signature='s'),
        }}

    @dbus.service.method(GATT_DSC_IFACE, in_signature='a{sv}',
                         out_signature='ay')
    def ReadValue(self, options):
        return dbus.Array(self.value, signature='y')


class Application(dbus.service.Object):
    def __init__(self, bus):
        self.services = []
        super().__init__(bus, APP_PATH)

    @dbus.service.method(OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        resp = {}
        for s in self.services:
            resp[s.path] = s.get_properties()
            for c in s.characteristics:
                resp[c.path] = c.get_properties()
                for d in c.descriptors:
                    resp[d.path] = d.get_properties()
        return resp


class Advertisement(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, ADV_PATH)

    @dbus.service.method(PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return {
            'Type': 'peripheral',
            'ServiceUUIDs': dbus.Array([uuid16(0x1812)], signature='s'),
            'LocalName': KBD_NAME,
            'Appearance': dbus.UInt16(0x03C1),   # keyboard
            'Discoverable': dbus.Boolean(True),
        }

    @dbus.service.method(ADV_IFACE)
    def Release(self):
        pass


class Agent(dbus.service.Object):
    """NoInputNoOutput agent: accept everything (Just Works pairing)."""

    @dbus.service.method(AGENT_IFACE)
    def Release(self):
        pass

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='s')
    def RequestPinCode(self, device):
        return '0000'

    @dbus.service.method(AGENT_IFACE, in_signature='o', out_signature='u')
    def RequestPasskey(self, device):
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_IFACE, in_signature='ouq')
    def DisplayPasskey(self, device, passkey, entered):
        pass

    @dbus.service.method(AGENT_IFACE, in_signature='os')
    def DisplayPinCode(self, device, pincode):
        pass

    @dbus.service.method(AGENT_IFACE, in_signature='ou')
    def RequestConfirmation(self, device, passkey):
        pass

    @dbus.service.method(AGENT_IFACE, in_signature='o')
    def RequestAuthorization(self, device):
        pass

    @dbus.service.method(AGENT_IFACE, in_signature='os')
    def AuthorizeService(self, device, uuid):
        pass

    @dbus.service.method(AGENT_IFACE)
    def Cancel(self):
        pass


class Core:
    """Owns the adapter, the GATT app and the keyboard state machine.

    Exposes raw state as attributes (error / adv_registered / device_path /
    device_name / subscribed) and fires on_change() whenever any of it moves.
    The advertisement can be toggled at runtime with adv_on()/adv_off() —
    adv_off() + Disconnect releases the central so it stops treating us as an
    attached keyboard.
    """

    def __init__(self):
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.on_change = lambda: None
        self.error = None
        self.adv_registered = False
        self.subscribed = False
        self.target = None           # BT address; None = first central wins
        self._addr_cache = {}
        om = dbus.Interface(self.bus.get_object(BLUEZ, '/'), OM_IFACE)
        objs = om.GetManagedObjects()
        adapters = sorted(str(p) for p, i in objs.items()
                          if ADAPTER_IFACE in i)
        want = os.environ.get('BTKEYCAST_ADAPTER')
        if want:
            self.adapter_path = f'/org/bluez/{want}'
            if self.adapter_path not in adapters:
                raise SystemExit(
                    f'adapter {want} not found (available: {adapters})')
        else:
            if not adapters:
                raise SystemExit('no Bluetooth adapter found')
            powered = [p for p in adapters
                       if objs[p][ADAPTER_IFACE].get('Powered')]
            self.adapter_path = (powered or adapters)[0]
        self.adapter = dbus.Interface(
            self.bus.get_object(BLUEZ, self.adapter_path), PROP_IFACE)
        self.device_path = None
        self.device_name = None
        self.app_registered = False
        self.want_adv = True
        self.mods = 0
        self.keys = []
        self.orig_alias = str(self.adapter.Get(ADAPTER_IFACE, 'Alias'))
        self.orig_pairable = bool(self.adapter.Get(ADAPTER_IFACE, 'Pairable'))

    def aset(self, prop, val):
        self.adapter.Set(ADAPTER_IFACE, prop, val)

    def start(self):
        try:
            self.aset('Powered', dbus.Boolean(True))
        except dbus.exceptions.DBusException as e:
            raise SystemExit(
                f'cannot power on {self.adapter_path}'
                f' ({e.get_dbus_name()}); try: rfkill unblock bluetooth')
        self.aset('Alias', KBD_NAME)
        self.aset('Pairable', dbus.Boolean(True))

        self.agent = Agent(self.bus, AGENT_PATH)
        am = dbus.Interface(self.bus.get_object(BLUEZ, '/org/bluez'),
                            'org.bluez.AgentManager1')
        am.RegisterAgent(AGENT_PATH, 'NoInputNoOutput')
        try:
            am.RequestDefaultAgent(AGENT_PATH)
        except dbus.exceptions.DBusException:
            pass

        self.app = Application(self.bus)
        hid = Service(self.bus, 0, uuid16(0x1812))
        Characteristic(self.bus, 0, uuid16(0x2A4E),
                       ['read', 'write-without-response'], hid, [0x01])
        Characteristic(self.bus, 1, uuid16(0x2A4B),
                       ['encrypt-read'], hid, REPORT_MAP)
        self.input_report = Characteristic(
            self.bus, 2, uuid16(0x2A4D), ['encrypt-read', 'notify'],
            hid, [0] * 8)
        self.input_report.on_notify = self.notify_changed
        Descriptor(self.bus, 0, uuid16(0x2908), ['read'],
                   self.input_report, [0x01, 0x01])
        out_report = Characteristic(
            self.bus, 3, uuid16(0x2A4D),
            ['read', 'write', 'write-without-response'], hid, [0])
        Descriptor(self.bus, 0, uuid16(0x2908), ['read'],
                   out_report, [0x01, 0x02])
        Characteristic(self.bus, 4, uuid16(0x2A4A), ['read'], hid,
                       [0x11, 0x01, 0x00, 0x02])
        Characteristic(self.bus, 5, uuid16(0x2A4C),
                       ['write-without-response'], hid)
        for c in hid.characteristics:
            c.on_access = self._seen_device
        self.app.services.append(hid)

        bas = Service(self.bus, 1, uuid16(0x180F))
        Characteristic(self.bus, 0, uuid16(0x2A19), ['read', 'notify'],
                       bas, [100])
        self.app.services.append(bas)

        # Device Information with PnP ID is mandatory for HOGP hosts (iOS/macOS)
        dis = Service(self.bus, 2, uuid16(0x180A))
        Characteristic(self.bus, 0, uuid16(0x2A50), ['read'], dis,
                       [0x02, 0x6B, 0x1D, 0x46, 0x02, 0x00, 0x01])
        Characteristic(self.bus, 1, uuid16(0x2A29), ['read'], dis,
                       [ord(c) for c in 'btkeycast'])
        self.app.services.append(dis)

        self.adv = Advertisement(self.bus)
        self.adv_mgr = dbus.Interface(
            self.bus.get_object(BLUEZ, self.adapter_path), ADV_MGR_IFACE)

        gm = dbus.Interface(self.bus.get_object(BLUEZ, self.adapter_path),
                            GATT_MGR_IFACE)
        gm.RegisterApplication(
            APP_PATH, {},
            reply_handler=self._app_registered,
            error_handler=lambda e: self.fail(f'GATT registration failed: {e}'))

        self.bus.add_signal_receiver(
            self._dev_changed, dbus_interface=PROP_IFACE,
            signal_name='PropertiesChanged', arg0=DEVICE_IFACE,
            path_keyword='path')
        self._resolve_device()

    def _app_registered(self):
        self.app_registered = True
        if self.want_adv:
            self.adv_on()

    def adv_on(self):
        self.want_adv = True
        if not self.app_registered or self.adv_registered:
            return

        def ok():
            self.adv_registered = True
            self.on_change()

        self.adv_mgr.RegisterAdvertisement(
            ADV_PATH, {}, reply_handler=ok,
            error_handler=lambda e: self.fail(f'LE advertising failed: {e}'))

    def adv_off(self):
        self.want_adv = False
        if self.adv_registered:
            self.adv_registered = False
            try:
                self.adv_mgr.UnregisterAdvertisement(ADV_PATH)
            except dbus.exceptions.DBusException:
                pass
        if self.device_path:
            try:
                dbus.Interface(self.bus.get_object(BLUEZ, self.device_path),
                               DEVICE_IFACE).Disconnect()
            except dbus.exceptions.DBusException:
                pass
        self.on_change()

    def fail(self, msg):
        print(msg, file=sys.stderr, flush=True)
        self.error = msg
        self.on_change()

    # ---- connection tracking

    def addr_of(self, path):
        if path not in self._addr_cache:
            try:
                self._addr_cache[path] = str(dbus.Interface(
                    self.bus.get_object(BLUEZ, path), PROP_IFACE
                ).Get(DEVICE_IFACE, 'Address'))
            except dbus.exceptions.DBusException:
                return None
        return self._addr_cache[path]

    def _disconnect_path(self, path):
        try:
            dbus.Interface(self.bus.get_object(BLUEZ, path),
                           DEVICE_IFACE).Disconnect()
        except dbus.exceptions.DBusException:
            pass

    def paired_centrals(self):
        """[(address, name, connected)] of devices bonded to our adapter."""
        om = dbus.Interface(self.bus.get_object(BLUEZ, '/'), OM_IFACE)
        out = []
        for path, ifaces in om.GetManagedObjects().items():
            dev = ifaces.get(DEVICE_IFACE)
            if (dev and str(path).startswith(self.adapter_path + '/')
                    and dev.get('Paired')):
                out.append((str(dev['Address']),
                            str(dev.get('Name') or dev['Address']),
                            bool(dev.get('Connected'))))
        return sorted(out, key=lambda d: d[1])

    def set_target(self, address):
        """Pin the central we forward to; kick a mismatched current one."""
        self.target = address
        if (address and self.device_path
                and self.addr_of(self.device_path) != address):
            self._disconnect_path(self.device_path)
        self.on_change()

    def _adopt(self, path):
        self.device_path = path
        props = dbus.Interface(self.bus.get_object(BLUEZ, path), PROP_IFACE)
        try:
            self.device_name = str(props.Get(DEVICE_IFACE, 'Name'))
        except dbus.exceptions.DBusException:
            self.device_name = str(props.Get(DEVICE_IFACE, 'Address'))
        self.on_change()

    def _dev_changed(self, iface, changed, invalidated, path=None):
        if not path or not path.startswith(self.adapter_path + '/'):
            return
        if changed.get('Paired'):
            try:
                dbus.Interface(
                    self.bus.get_object(BLUEZ, path), PROP_IFACE
                ).Set(DEVICE_IFACE, 'Trusted', dbus.Boolean(True))
            except dbus.exceptions.DBusException:
                pass
        if 'Connected' not in changed:
            return
        if changed['Connected']:
            if self.target and self.addr_of(path) != self.target:
                return       # 関係ない機器 (ローカルの BT 周辺機器等) は放置
            self._adopt(path)
        elif path == self.device_path:
            self.device_path = None
            self.subscribed = False
            self.mods, self.keys = 0, []
            self.on_change()

    def _seen_device(self, options):
        """A central touched our HID service — that is who we forward to."""
        path = str(options.get('device', ''))
        if not path:
            return
        if self.target and self.addr_of(path) != self.target:
            # target 以外の central がキーボードとして使おうとした — 蹴る
            self._disconnect_path(path)
            return
        if path != self.device_path:
            self._adopt(path)

    def _resolve_device(self):
        """Fallback: find the connected central we should forward to."""
        om = dbus.Interface(self.bus.get_object(BLUEZ, '/'), OM_IFACE)
        for path, ifaces in om.GetManagedObjects().items():
            dev = ifaces.get(DEVICE_IFACE)
            if not (dev and str(path).startswith(self.adapter_path + '/')
                    and dev.get('Connected')):
                continue
            addr = str(dev.get('Address'))
            if (self.target and addr == self.target) or (
                    not self.target
                    and dev.get('AddressType') == 'random'):
                self.device_path = str(path)
                self.device_name = str(dev.get('Name') or addr)
                self.on_change()
                return

    def notify_changed(self, enabled):
        self.subscribed = enabled
        if enabled and not self.device_path:
            self._resolve_device()
        self.on_change()

    # ---- key handling (evdev keycodes)

    def press(self, code):
        usage = KEYMAP.get(code)
        if usage is None:
            return
        if 0xE0 <= usage <= 0xE7:
            self.mods |= 1 << (usage - 0xE0)
        elif usage not in self.keys and len(self.keys) < 6:
            self.keys.append(usage)
        self.send()

    def release(self, code):
        usage = KEYMAP.get(code)
        if usage is None:
            return
        if 0xE0 <= usage <= 0xE7:
            self.mods &= ~(1 << (usage - 0xE0))
        elif usage in self.keys:
            self.keys.remove(usage)
        self.send()

    def release_all(self):
        self.mods, self.keys = 0, []
        self.send()

    def send(self):
        report = [self.mods, 0] + self.keys + [0] * (6 - len(self.keys))
        self.input_report.notify_value(report)

    # ---- teardown

    def stop(self):
        self.mods, self.keys = 0, []
        try:
            self.send()
        except Exception:
            pass
        for call in (
            lambda: dbus.Interface(
                self.bus.get_object(BLUEZ, self.adapter_path),
                ADV_MGR_IFACE).UnregisterAdvertisement(ADV_PATH),
            lambda: dbus.Interface(
                self.bus.get_object(BLUEZ, self.adapter_path),
                GATT_MGR_IFACE).UnregisterApplication(APP_PATH),
            lambda: self.device_path and dbus.Interface(
                self.bus.get_object(BLUEZ, self.device_path),
                DEVICE_IFACE).Disconnect(),
            lambda: self.aset('Alias', self.orig_alias),
            lambda: self.aset('Pairable', dbus.Boolean(self.orig_pairable)),
            lambda: dbus.Interface(
                self.bus.get_object(BLUEZ, '/org/bluez'),
                'org.bluez.AgentManager1').UnregisterAgent(AGENT_PATH),
        ):
            try:
                call()
            except Exception:
                pass
