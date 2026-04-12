#!/usr/bin/env python3

from __future__ import annotations

import argparse
import signal
import sys

from koi.listener import Listener
from koi.utils.ui import notify, _b, _p, _gr, breaker_with_text, breaker, print_report_box, display_art
from koi.utils.payloads import PayloadGenerator


def _print_payloads(iface: str, port: int) -> None:
    gen = PayloadGenerator(port=port)
    if iface == "__all__":
        all_payloads = gen.for_all()
        if not all_payloads:
            notify('error', "No network interfaces found.")
            return
        interfaces = gen.get_interfaces()
        grouped = {
            f"{name} ({interfaces[name]})": payloads
            for name, payloads in all_payloads.items()
        }
        print_report_box("Payloads", grouped)
    else:
        payloads = gen.for_interface(iface)
        print()
        breaker_with_text(f"payloads for {iface}")
        print()
        if payloads is None:
            notify('error', f"Interface {_p(iface)} not found.")
            notify('status', _gr("Available: " + ", ".join(gen.get_interfaces().keys())))
            return
        for name, payload in payloads.items():
            print(f"{_b(_p(name))}: {_gr(payload)}\n")
        breaker()


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
        _print_payloads(args.payloads, args.port)
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