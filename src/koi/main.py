#!/usr/bin/env python3

from __future__ import annotations

import argparse
import signal
import sys

from koi.listener import Listener
from koi.utils.ui import notify, _b, display_art, print_payloads


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
    args = parser.parse_args()

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