"""Command line entry point: run / toggle / status.

`toggle` is meant to be wired to a status bar click, `status` to a waybar
custom module (JSON output, refreshed via RTMIN+WAYBAR_SIGNAL).
"""

import json
import os
import shutil
import signal
import subprocess
import sys

from . import KBD_NAME, PROG, WAYBAR_SIGNAL


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


def signal_waybar():
    subprocess.run(['pkill', f'-RTMIN+{WAYBAR_SIGNAL}', '-x', 'waybar'],
                   check=False)


def notify(message):
    if shutil.which('notify-send'):
        subprocess.run(['notify-send', '-u', 'critical', PROG, message],
                       check=False)


def cmd_status():
    if running_pid():
        out = {'text': 'kbd→pad', 'class': 'on',
               'tooltip': f'BLE キーボード転送中 ({KBD_NAME}) — クリックで停止'}
    else:
        out = {'text': 'kbd', 'class': 'off',
               'tooltip': 'クリックで BLE キーボード転送を開始'}
    print(json.dumps(out, ensure_ascii=False))


def cmd_toggle():
    pid = running_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        return
    logdir = os.path.expanduser('~/.cache')
    os.makedirs(logdir, exist_ok=True)
    log = open(os.path.join(logdir, PROG + '.log'), 'ab', buffering=0)
    subprocess.Popen([sys.executable, '-m', 'btkeycast', 'run'],
                     stdout=log, stderr=log, start_new_session=True)


def cmd_run():
    pid = running_pid()
    if pid and pid != os.getpid():
        raise SystemExit('already running')

    from .hog import Core
    from .ui import run_ui

    try:
        core = Core()
        core.start()
    except SystemExit as e:
        notify(str(e))
        raise
    with open(pidfile(), 'w') as f:
        f.write(str(os.getpid()))
    try:
        signal_waybar()
        run_ui(core)
    finally:
        core.stop()
        try:
            os.unlink(pidfile())
        except OSError:
            pass
        signal_waybar()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'run'
    if cmd == 'status':
        cmd_status()
    elif cmd == 'toggle':
        cmd_toggle()
    elif cmd == 'run':
        cmd_run()
    else:
        raise SystemExit(f'usage: {PROG} [run|toggle|status]')
