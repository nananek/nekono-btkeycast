"""btkeycast — forward the local keyboard to a BLE central as a HID-over-GATT keyboard."""

import socket as _socket

__version__ = '0.1.0'

PROG = 'btkeycast'
KBD_NAME = _socket.gethostname().split('.')[0] + '-kbd'
