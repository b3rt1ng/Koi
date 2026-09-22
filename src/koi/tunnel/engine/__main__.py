from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _psk(args) -> str:
    psk = args.psk or os.environ.get("TUNEL_PSK")
    if not psk:
        sys.exit("error: pass --psk or set TUNEL_PSK")
    return psk


def build_parser() -> argparse.ArgumentParser:
    # -v must work before AND after the subcommand, hence the shared parent.
    # SUPPRESS is essential: without it the subparser re-injects its
    # False default and overrides a -v placed before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v", "--verbose", action="store_true",
        default=argparse.SUPPRESS, help="debug logs",
    )

    parser = argparse.ArgumentParser(
        prog="tunel",
        parents=[common],
        description="L3 network tunnel with a userland TCP stack on the agent side.",
    )
    sub = parser.add_subparsers(dest="role", required=True)

    p = sub.add_parser("proxy", parents=[common],
                       help="attacker side: carries the TUN (root required)")
    p.add_argument("--psk", help="shared secret (or TUNEL_PSK)")
    p.add_argument("--listen", default="0.0.0.0", help="listen interface")
    p.add_argument("--port", type=int, default=11601)
    p.add_argument("--tun", default="tunel0", help="TUN interface name")
    p.add_argument("--address", default="240.0.0.1", help="local TUN address")
    p.add_argument("--netmask", type=int, default=24)
    p.add_argument("--route", action="append", default=[],
                   help="network to route through the tunnel (repeatable)")
    p.add_argument("--mtu", type=int, default=1500)
    p.add_argument("--no-configure", action="store_true",
                   help="do not touch the network config (already done by hand)")

    a = sub.add_parser("agent", parents=[common],
                       help="target side: userland stack, no privileges")
    a.add_argument("host", help="proxy address")
    a.add_argument("--psk", help="shared secret (or TUNEL_PSK)")
    a.add_argument("--port", type=int, default=11601)
    a.add_argument("--mtu", type=int, default=1500)
    a.add_argument("--retry-delay", type=float, default=5.0)
    a.add_argument("--max-retries", type=int, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))   # SUPPRESS: absent when not passed
    psk = _psk(args)

    if args.role == "proxy":
        from .proxy import Proxy
        from .tun import TunError

        runner = Proxy(
            psk=psk, tun_name=args.tun, address=args.address, netmask=args.netmask,
            routes=args.route, host=args.listen, port=args.port, mtu=args.mtu,
            configure=not args.no_configure,
        )
        try:
            asyncio.run(runner.run())
        except TunError as exc:
            return _fail(exc)
        except KeyboardInterrupt:
            pass
    else:
        from .agent import Agent

        runner = Agent(
            psk=psk, host=args.host, port=args.port, mtu=args.mtu,
            retry_delay=args.retry_delay, max_retries=args.max_retries,
        )
        try:
            asyncio.run(runner.run())
        except KeyboardInterrupt:
            pass
    return 0


def _fail(exc: Exception) -> int:
    print(f"error: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
