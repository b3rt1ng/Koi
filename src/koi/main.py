#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import signal
import sys

from koi.listener import Listener, _STATE_FILE
from koi.session import OS_LABEL_NAMES
from koi.utils.ui import notify, _b, _p, _c, _gr, _y, _bl, display_art, print_payloads, print_report_box


def _print_info() -> None:
    print("koi is a multi-session reverse shell listener.")
    print("It accepts incoming TCP connections from remote shells, manages them as")
    print("numbered sessions, and lets the operator interact with them, upgrade them")
    print("to full PTYs, and run post-exploitation modules.")
    print()
    print("Commands: go <id>  upgrade <id>  kill <id>  run <module> <id>  ls  payload  help")
    print()

    if not os.path.exists(_STATE_FILE):
        print("Status: no active listener.")
        return

    try:
        with open(_STATE_FILE) as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Error reading state: {e}")
        return

    host = state.get("host", "?")
    port = state.get("port", "?")
    pid = state.get("pid", "?")
    sessions = state.get("sessions", [])
    alive = [s for s in sessions if s.get("alive", True)]

    print(f"Listener: {host}:{port}  (pid {pid})")
    print(f"Active sessions: {len(alive)}")

    if alive:
        print()
        for s in sorted(alive, key=lambda x: x["id"]):
            os_label = OS_LABEL_NAMES.get(s.get("os_type") or "", "unknown")
            upgrade_label = "PTY" if s.get("upgraded") else "raw"
            print(f"  #{s['id']}  {s['ip']}:{s['port']}  {os_label}  {upgrade_label}  up {s.get('uptime', '?')}")


class _ArtHelpAction(argparse.Action):
    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings=option_strings, dest=dest, default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        display_art(small=True)
        parser.print_help()
        parser.exit()


def main():
    parser = argparse.ArgumentParser(
        description="koi – multi-session reverse shell listener",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action=_ArtHelpAction, help="show this help message and exit")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", "-p", type=int, default=4444, help="Listen port (default: 4444)")
    parser.add_argument("--payloads", nargs="?", const="__all__", metavar="IFACE",
                        help="Print payloads for all interfaces (or a specific one) and exit")
    parser.add_argument("-i", "--info", action="store_true",
                        help="Print a summary of the running listener and active sessions, then exit")
    args = parser.parse_args()

    if args.info:
        _print_info()
        sys.exit(0)

    if args.payloads is not None:
        print_payloads(None if args.payloads == "__all__" else args.payloads, args.port)
        sys.exit(0)

    listener = Listener(host=args.host, port=args.port)

    signal.signal(
        signal.SIGINT,
        lambda *_: (print(), notify('warning', f"Use {_b('exit')} to quit cleanly."))
    )

    try:
        listener.start()
    except PermissionError:
        notify('error', f"Permission denied on port {args.port}.")
        sys.exit(1)
    except OSError as e:
        notify('error', f"Cannot start listener: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()