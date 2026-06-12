"""Persistent user choices (forward target, pinned keyboards)."""

import json
import os

from . import PROG


def _path():
    base = os.environ.get('XDG_CONFIG_HOME',
                          os.path.expanduser('~/.config'))
    return os.path.join(base, PROG, 'config.json')


def load():
    try:
        with open(_path()) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return {'target': d.get('target') or None,
            'keyboards': list(d.get('keyboards', []))}


def save(cfg):
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, p)
