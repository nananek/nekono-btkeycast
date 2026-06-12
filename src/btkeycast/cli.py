"""Command line entry point.

  daemon   run the persistent daemon (waybar continuous-exec module)
  toggle   show/hide the capture popup (left click); starts the daemon
           detached if none is running
  conn     toggle the BLE connection (right click)
"""

import os
import shutil
import signal
import subprocess
import sys
import time

from . import PROG


def pidfile():
    runtime = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    return os.path.join(runtime, PROG + '.pid')


def running_pid():
    try:
        with open(pidfile()) as f:
            pid = int(f.read().strip())
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            if PROG.encode() in f.read():
                return pid
    except (OSError, ValueError):
        pass
    return None


def notify(message):
    if shutil.which('notify-send'):
        subprocess.run(['notify-send', '-u', 'critical', PROG, message],
                       check=False)


def spawn_daemon():
    logdir = os.path.expanduser('~/.cache')
    os.makedirs(logdir, exist_ok=True)
    log = open(os.path.join(logdir, PROG + '.log'), 'ab', buffering=0)
    subprocess.Popen([sys.executable, '-m', 'btkeycast', 'daemon'],
                     stdout=log, stderr=log, start_new_session=True)
    for _ in range(30):
        time.sleep(0.1)
        pid = running_pid()
        if pid:
            return pid
    return None


def cmd_toggle():
    pid = running_pid() or spawn_daemon()
    if not pid:
        notify('daemon を起動できませんでした (~/.cache/btkeycast.log 参照)')
        raise SystemExit(1)
    os.kill(pid, signal.SIGUSR1)


def cmd_conn():
    pid = running_pid()
    if not pid:
        notify('daemon が動いていません (waybar の custom/btkeycast 経由で起動します)')
        raise SystemExit(1)
    os.kill(pid, signal.SIGUSR2)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'daemon'
    if cmd == 'daemon':
        from .daemon import run
        run()
    elif cmd == 'toggle':
        cmd_toggle()
    elif cmd == 'conn':
        cmd_conn()
    else:
        raise SystemExit(f'usage: {PROG} [daemon|toggle|conn]')
