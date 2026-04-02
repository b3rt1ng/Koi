#!/usr/bin/env python3

from __future__ import annotations

import argparse
import signal
import sys

from koi.listener import Listener
from koi.utils.ui import notify, _b


def main():
    parser = argparse.ArgumentParser(
        description="koi – multi-session reverse shell listener",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", "-p", type=int, default=4444, help="Listen port (default: 4444)")
    args = parser.parse_args()

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