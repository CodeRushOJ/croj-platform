#!/usr/bin/env python3
"""Hold a crash-safe advisory checkout lock for a parent shell process."""

import argparse
import fcntl
import json
import os
import pathlib
import signal
import stat
import subprocess
import sys
import time


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", required=True, type=pathlib.Path)
    parser.add_argument("--ready", type=pathlib.Path)
    parser.add_argument("--parent-pid", required=True, type=int)
    parser.add_argument("--timeout-ms", required=True, type=int)
    parser.add_argument("--poll-ms", required=True, type=int)
    parser.add_argument("--legacy-grace-ms", required=True, type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


def process_is_alive(process_id):
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def ensure_parent_is_current(parent_pid):
    if os.getppid() != parent_pid:
        raise RuntimeError(f"checkout lock parent exited: {parent_pid}")


def legacy_snapshot(lock_path):
    try:
        lock_stat = os.lstat(lock_path)
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(lock_stat.st_mode):
        return None
    owner_path = lock_path / "owner"
    try:
        owner_stat = os.lstat(owner_path)
        owner = owner_path.read_text().strip()
        owner_identity = (owner_stat.st_dev, owner_stat.st_ino, owner_stat.st_mtime_ns)
    except FileNotFoundError:
        owner = ""
        owner_identity = None
    return (
        lock_stat.st_dev,
        lock_stat.st_ino,
        lock_stat.st_mtime_ns,
        owner_identity,
        owner,
    )


def legacy_is_stale(snapshot, grace_ms):
    owner = snapshot[-1]
    if owner.isdecimal():
        return not process_is_alive(int(owner))
    activity_mtime_ns = snapshot[2]
    if snapshot[3] is not None:
        activity_mtime_ns = max(activity_mtime_ns, snapshot[3][2])
    age_ms = max(0, (time.time_ns() - activity_mtime_ns) // 1_000_000)
    return age_ms >= grace_ms


def quarantine_legacy_lock(lock_path, expected_snapshot):
    if legacy_snapshot(lock_path) != expected_snapshot:
        return False
    quarantine = lock_path.with_name(
        f"{lock_path.name}.stale.{os.getpid()}.{time.time_ns()}"
    )
    os.rename(lock_path, quarantine)
    if legacy_snapshot(quarantine) != expected_snapshot:
        raise RuntimeError(
            f"legacy checkout lock changed during quarantine; retained for inspection: {quarantine}"
        )
    entries = {entry.name for entry in quarantine.iterdir()}
    if entries - {"owner"}:
        raise RuntimeError(f"legacy checkout lock contains unexpected files: {quarantine}")
    owner_path = quarantine / "owner"
    if owner_path.exists():
        owner_path.unlink()
    quarantine.rmdir()
    return True


def acquire_recovery_lock(lock_path, deadline, poll_seconds, parent_pid):
    recovery_path = lock_path.with_name(f"{lock_path.name}.recovery")
    recovery_fd = os.open(recovery_path, os.O_RDWR | os.O_CREAT, 0o600)
    while True:
        ensure_parent_is_current(parent_pid)
        try:
            fcntl.flock(recovery_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return recovery_fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(recovery_fd)
                raise TimeoutError(f"timed out waiting for lock recovery: {lock_path}")
            time.sleep(poll_seconds)


def open_lock_file(lock_path, deadline, poll_seconds, legacy_grace_ms, parent_pid):
    while True:
        ensure_parent_is_current(parent_pid)
        recovery_fd = acquire_recovery_lock(
            lock_path, deadline, poll_seconds, parent_pid
        )
        try:
            retained = sorted(lock_path.parent.glob(f"{lock_path.name}.stale.*"))
            if retained:
                raise RuntimeError(
                    f"retained legacy quarantine blocks checkout lock: {retained[0]}"
                )
            try:
                return os.open(
                    lock_path,
                    os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except IsADirectoryError:
                first = legacy_snapshot(lock_path)
                if first is not None and legacy_is_stale(first, legacy_grace_ms):
                    time.sleep(poll_seconds)
                    second = legacy_snapshot(lock_path)
                    if second == first and legacy_is_stale(second, legacy_grace_ms):
                        quarantine_legacy_lock(lock_path, second)
                        continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"timed out waiting for legacy checkout lock: {lock_path}"
                    )
        finally:
            os.close(recovery_fd)
        time.sleep(poll_seconds)


def main():
    args = parse_args()
    if args.parent_pid <= 1 or args.timeout_ms <= 0 or args.poll_ms <= 0:
        raise SystemExit("parent PID, timeout and poll interval must be positive")
    if args.legacy_grace_ms < args.poll_ms:
        raise SystemExit("legacy grace period must be at least one poll interval")
    command = list(args.command)
    if command[:1] == ["--"]:
        command.pop(0)
    if (args.ready is None) == (not command):
        raise SystemExit("exactly one of --ready or a command after -- is required")

    poll_seconds = args.poll_ms / 1000
    deadline = time.monotonic() + args.timeout_ms / 1000
    lock_fd = open_lock_file(
        args.lock,
        deadline,
        poll_seconds,
        args.legacy_grace_ms,
        args.parent_pid,
    )
    try:
        while True:
            ensure_parent_is_current(args.parent_pid)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for checkout lock: {args.lock}")
                time.sleep(poll_seconds)

        owner = json.dumps({"pid": args.parent_pid}) + "\n"
        os.ftruncate(lock_fd, 0)
        os.write(lock_fd, owner.encode())
        os.fsync(lock_fd)
        if command:
            completed = subprocess.run(command, pass_fds=(lock_fd,), check=False)
            return completed.returncode

        args.ready.write_text("ready\n")

        stopping = False

        def stop(_signal_number, _frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while not stopping and os.getppid() == args.parent_pid:
            time.sleep(poll_seconds)
    finally:
        try:
            if args.ready is not None:
                args.ready.unlink()
        except FileNotFoundError:
            pass
        os.close(lock_fd)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, TimeoutError) as error:
        print(f"checkout lock failed: {error}", file=sys.stderr)
        raise SystemExit(1)
