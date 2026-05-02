#!/usr/bin/env python3

from __future__ import annotations

import argparse
import signal
import sys

from koi.listener import Listener
from koi.utils.ui import notify, _b, _p, _c, display_art, print_payloads
from koi.utils.obfuscate_ui import run_obfuscate_ui
from koi.utils.logger import review as _review



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
    parser.add_argument("--port", "-p", type=int, default=4010, help="Listen port (default: 4010)")
    parser.add_argument("--payloads", nargs="?", const="__all__", metavar="IFACE",
                        help="Print payloads for all interfaces (or a specific one) and exit")
    parser.add_argument("--obfuscator", "--cook", nargs="?", const="__all__", metavar="IFACE",
                        help="Open the payload obfuscator (optionally for a specific interface) and exit")
    args = parser.parse_args()

    if args.payloads is not None:
        print_payloads(None if args.payloads == "__all__" else args.payloads, args.port)
        sys.exit(0)

    if args.obfuscator is not None:
        run_obfuscate_ui(None if args.obfuscator == "__all__" else args.obfuscator, args.port)
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


def koireview():
    parser = argparse.ArgumentParser(
        description="koireview – review a recorded Koi session",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action=_ArtHelpAction, help="show this help message and exit")
    parser.add_argument("log", nargs="?", default=None, metavar="LOG",
                        help="Log file to review (name or path). Omit to list available logs.")
    args = parser.parse_args()

    if args.log is None:
        from koi.utils.logger import print_log_list
        print_log_list()
    else:
        _review(args.log)


def obfuscator():
    parser = argparse.ArgumentParser(
        description="koifuscator – payload obfuscator",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action=_ArtHelpAction, help="show this help message and exit")
    parser.add_argument("--port", "-p", type=int, default=4010, help="Callback port embedded in the payload (default: 4010)")
    parser.add_argument("iface", nargs="?", default=None, metavar="IFACE",
                        help="Network interface to use (default: all)")
    args = parser.parse_args()
    run_obfuscate_ui(args.iface, args.port)


if __name__ == "__main__":
    main()