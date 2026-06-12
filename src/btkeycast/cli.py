"""Command line entry point.

  daemon   run the persistent daemon (waybar continuous-exec module)
  toggle   show/hide the capture popup (left click); starts the daemon
           detached if none is running
  conn     toggle the BLE connection (right click)
"""

import fcntl
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


def _ppid(pid):
    try:
        with open(f'/proc/{pid}/stat') as f:
            return int(f.read().rsplit(')', 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def acquire_instance_lock():
    """Single-instance gate via flock on the pidfile.

    waybar はマルチモニタだと custom module の exec を出力ごとに 1 個ずつ
    起動するので、daemon は出力数ぶん同時に立ち上がる。先に flock を取れた
    1 個だけが本体になる。負けた側は、ロック保持者が同じ親 (= 同じ waybar)
    の兄弟なら黙って身を引き (None を返す)、前世代の残骸なら SIGTERM して
    引き継ぐ。

    Returns the fd holding the lock (keep it open for the daemon's
    lifetime; the lock dies with the process), or None when a sibling
    already runs.
    """
    fd = open(pidfile(), 'a+')
    deadline = time.time() + 5
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            holder = running_pid()
            if holder and holder != os.getpid():
                if _ppid(holder) == os.getppid():
                    fd.close()
                    return None
                try:
                    os.kill(holder, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if time.time() > deadline:
                fd.close()
                raise SystemExit('another instance refuses to exit')
            time.sleep(0.1)
            continue
        # flock を持たない旧版 daemon が残っていたら引き継ぐ (移行経路)
        legacy = running_pid()
        if legacy and legacy != os.getpid():
            try:
                os.kill(legacy, signal.SIGTERM)
            except ProcessLookupError:
                pass
        fd.seek(0)
        fd.truncate()
        fd.write(str(os.getpid()))
        fd.flush()
        return fd


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
