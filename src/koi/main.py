#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys

from koi.listener import Listener
from koi.utils.config import CONFIG
from koi.utils.ui import notify, display_art, print_payloads, __version__
from koi.utils.obfuscate_ui import run_obfuscate_ui
from koi.utils.logger import review as _review
from koi.utils.logger import clear_log as _clear_log



def _prepare_local_cache() -> None:
    """Download and cache all external resources declared by modules."""
    from koi.modules.loader import collect_external_resources
    from koi.utils.powerupgrade import get_external_resources as pw_resources
    from koi.utils.cache import fetch_or_cache
    from koi.utils.ui import bold, accent

    resources = collect_external_resources()
    resources.extend(pw_resources())

    if not resources:
        notify('info', "No external resources to cache.")
        return

    print()
    notify('info', f"Preparing cache: {bold(len(resources))} resource(s) to download")
    print()

    succeeded = []
    failed = []

    for i, resource in enumerate(resources, 1):
        name = resource.get("name", "Unknown")
        url = resource.get("url")
        cache_key = resource.get("cache_key")

        if not url or not cache_key:
            notify('warning', f"[{i}/{len(resources)}] {accent(name)}: malformed resource config")
            failed.append((name, "malformed config"))
            continue

        try:
            sys.stdout.write(f"  [{i}/{len(resources)}] {accent(f'{name:<30}')} ")
            sys.stdout.flush()
            data, source = fetch_or_cache(url, cache_key)
            if source == "remote":
                print(f"✓ ({len(data)} bytes)")
                succeeded.append(name)
            else:
                print("✓ (cached)")
                succeeded.append(name)
        except Exception as e:
            print("✗")
            notify('warning', f"  {str(e)[:80]}")
            failed.append((name, str(e)))

    print()
    if succeeded:
        notify('success', f"Cached: {bold(len(succeeded))}")
        for name in succeeded:
            print(f"  ✓ {name}")

    if failed:
        print()
        notify('warning', f"Failed: {bold(len(failed))}")
        for name, reason in failed:
            print(f"  ✗ {name}: {reason[:50]}")

    print()


def _onoff(value) -> str:
    """Render a config-sourced boolean for a --help default hint."""
    return "on" if value else "off"


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
    parser.add_argument("-v", "--version", action="version", version=f"koi {__version__}",
                        help="show the koi version and exit")

    listener_group = parser.add_argument_group("listener")
    listener_group.add_argument("--host", default=CONFIG["host"], help=f"Bind address (default: {CONFIG['host']})")
    listener_group.add_argument("--port", "-p", type=int, default=CONFIG["port"], help=f"Listen port (default: {CONFIG['port']})")

    payload_group = parser.add_argument_group("payloads")
    payload_group.add_argument("--payloads", nargs="?", const="__all__", metavar="IFACE",
                               help="Print payloads for all interfaces (or a specific one) and exit")
    payload_group.add_argument("--obfuscator", "--cook", nargs="?", const="__all__", metavar="IFACE",
                               help="Open the payload obfuscator (optionally for a specific interface) and exit")

    opsec_group = parser.add_argument_group("opsec")
    opsec_group.add_argument("--keep-history", "-kh", dest="keep_history", action="store_true",
                             help=f"Keep the target's shell history on upgraded sessions (config: {_onoff(CONFIG['keep_history'])})")
    opsec_group.add_argument("--strip-history", dest="keep_history", action="store_false",
                             help="Wipe the target's shell history on upgraded sessions")
    opsec_group.add_argument("--no-log", "-nl", dest="logging", action="store_false",
                             help=f"Do not record sessions to ~/.koi/logs (config: {_onoff(CONFIG['logging'])})")
    opsec_group.add_argument("--log", dest="logging", action="store_true",
                             help="Record sessions to ~/.koi/logs")

    cache_group = parser.add_argument_group("cache & offline")
    cache_group.add_argument("--local", "-l", dest="local", action="store_true",
                             help=f"Local mode: use cache only, no external network calls (config: {_onoff(CONFIG['local_mode'])})")
    cache_group.add_argument("--no-local", dest="local", action="store_false",
                             help="Allow external network calls")
    cache_group.add_argument("--local-prepare", "-lp", action="store_true", help="Download and cache all external resources needed by modules")
    cache_group.add_argument("--purge-cache", "-pc", action="store_true", help="removes all files in cache")

    parser.set_defaults(
        keep_history=bool(CONFIG["keep_history"]),
        logging=bool(CONFIG["logging"]),
        local=bool(CONFIG["local_mode"]),
    )

    mcp_group = parser.add_argument_group("AI / MCP")
    mcp_group.add_argument("--mcp", action="store_true", default=bool(CONFIG["mcp_activate"]),
                           help="Expose sessions and modules over MCP (loopback HTTP). "
                                "Default from config: mcp_activate")
    mcp_group.add_argument("--mcp-port", type=int, default=CONFIG.get("mcp_port", 7331), metavar="PORT",
                           help="Port for the MCP server (default from config: mcp_port, else 7331)")
    mcp_group.add_argument("--mcp-allow-exec", action="store_true", default=bool(CONFIG["mcp_exec_allow"]),
                           help="Let MCP clients run commands and modules on live sessions "
                                "(read-only without it). Default from config: mcp_exec_allow")
    mcp_group.add_argument("--mcp-token", default=None, metavar="TOKEN",
                           help="Bearer token for the MCP server (default: saved in ~/.koi/config.json, or $KOI_MCP_TOKEN)")

    args = parser.parse_args()
    
    if args.purge_cache:
        from koi.utils.cache import purge_cache
        ok = purge_cache()
        print("Cache purged." if ok else "Cache purge failed.")
        sys.exit(0 if ok else 1)

    if args.payloads is not None:
        print_payloads(None if args.payloads == "__all__" else args.payloads, args.port)
        sys.exit(0)

    if args.obfuscator is not None:
        run_obfuscate_ui(None if args.obfuscator == "__all__" else args.obfuscator, args.port)
        sys.exit(0)

    if args.local_prepare:
        _prepare_local_cache()
        sys.exit(0)

    listener = Listener(host=args.host, port=args.port, local_mode=args.local,
                        keep_history=args.keep_history, no_log=not args.logging)

    if args.mcp:
        from koi.mcp.server import KoiMCPServer, missing_dependencies

        # thread, where the failure would land as a traceback over the prompt.
        if missing := missing_dependencies():
            notify('error', f"MCP dependencies missing: {', '.join(missing)}")
            notify('status', "Reinstall to restore them:  pipx install --force koi-handler")
            sys.exit(1)

        listener.mcp_server = KoiMCPServer(
            listener,
            port=args.mcp_port,
            token=args.mcp_token,
            allow_exec=args.mcp_allow_exec,
        )

    try:
        listener.start()
    except PermissionError:
        notify('error', f"Permission denied on port {args.port}.")
        sys.exit(1)
    except OSError as e:
        notify('error', f"Cannot start listener: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)


def koireview():
    parser = argparse.ArgumentParser(
        description="koireview – review a recorded Koi session",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action=_ArtHelpAction, help="show this help message and exit")
    parser.add_argument("log", nargs="?", default=None, metavar="LOG",
                        help="Log file to review (name or path). Omit to list available logs.")
    parser.add_argument("-c", "--clear", action="store_true", help="Clear the specified log or all logs if none specified")
    args = parser.parse_args()

    if args.clear:
        if args.log is None:
            from koi.utils.logger import list_logs
            logs = list_logs()
            if not logs:
                print("No logs to clear.")
                return
            for log in logs:
                _clear_log(log)
        else:
            from koi.utils.logger import resolve_log
            log_path = resolve_log(args.log)
            if log_path is None:
                print(f"Log not found: {args.log}", file=sys.stderr)
                sys.exit(1)
            _clear_log(log_path)
        return

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
    parser.add_argument("--port", "-p", type=int, default=CONFIG["port"], help=f"Callback port embedded in the payload (default: {CONFIG['port']})")
    parser.add_argument("iface", nargs="?", default=None, metavar="IFACE",
                        help="Network interface to use (default: all)")
    args = parser.parse_args()
    run_obfuscate_ui(args.iface, args.port)


if __name__ == "__main__":
    main()