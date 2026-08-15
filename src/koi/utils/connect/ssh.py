from __future__ import annotations

import getpass
import os
import shutil
from pathlib import Path
from typing import Optional

from koi.utils.connect.base import Target, Transport
from koi.utils.ui import accent, bold, muted, notify

_VALUE_FLAGS = set("BbcDEeFIiJLlmOopQRSWw")

_SSHPASS_EXIT: dict[int, str] = {
    5: "invalid or incorrect password",
    6: "host key unknown or changed",
}


class SshTransport(Transport):
    name = "ssh"
    syntax = "<[user[:pass]@]host>"
    summary = "Open a session over ssh (extra ssh args passed through)"

    def parse(self, argv: list[str]) -> Optional[Target]:
        index = None
        skip = False
        for i, token in enumerate(argv):
            if skip:
                skip = False
                continue
            if token.startswith("-") and len(token) > 1:
                skip = len(token) == 2 and token[1] in _VALUE_FLAGS
                continue
            index = i
            break

        if index is None:
            return None

        raw = argv[index]
        args = argv[:index] + argv[index + 1:]

        userinfo, at, hostpart = raw.rpartition("@")
        if at and ":" in userinfo:
            user, _, password = userinfo.partition(":")
            return Target(f"{user}@{hostpart}", hostpart, password or None, args)

        return Target(raw, hostpart or raw, None, args)

    def build_command(self, target: Target, remote_script: str) -> list[str]:
        ssh = ["ssh"]
        if not any("StrictHostKeyChecking" in a for a in target.args):
            ssh += ["-o", "StrictHostKeyChecking=accept-new"]

        argv = ssh + target.args + [target.destination, remote_script]
        return ["sshpass", "-e"] + argv if target.password else argv

    def resolve_auth(self, target: Target) -> bool:
        """An inline password or an ``-i`` key needs nothing from the operator."""
        have_sshpass = bool(shutil.which("sshpass"))

        if target.password:
            if not have_sshpass:
                notify('error', f"An inline password needs {accent('sshpass')}, which is not installed.")
                notify('status', muted("Install it, or drop the password and let ssh prompt for it."))
                return False
            return True

        if any(a == "-i" or a.startswith("-i") for a in target.args):
            return True

        if not have_sshpass:
            notify('status', muted(f"{accent('sshpass')} is not installed; ssh will prompt for the password itself."))
            return True

        pw = self._prompt_password(target.destination)
        if pw is None:
            return False
        target.password = pw or None
        return True

    def env(self, target: Target) -> Optional[dict[str, str]]:
        return {**os.environ, "SSHPASS": target.password} if target.password else None

    def explain_exit(self, target: Target, code: int) -> str:
        if target.password and code in _SSHPASS_EXIT:
            return _SSHPASS_EXIT[code]
        return f"exit code {code}"

    def completions(self) -> list[str]:
        """Host aliases from ~/.ssh/config, patterns excluded (they are not targets)."""
        hosts: list[str] = []
        try:
            lines = (Path.home() / ".ssh" / "config").read_text().splitlines()
        except OSError:
            return hosts
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and parts[0].lower() == "host":
                hosts.extend(p for p in parts[1:] if "*" not in p and "?" not in p)
        return hosts

    @staticmethod
    def _prompt_password(destination: str) -> Optional[str]:
        """None if the operator cancels, the raw string otherwise, empty included."""
        try:
            return getpass.getpass(f"  {accent('password')} for {bold(destination)}: ")
        except (KeyboardInterrupt, EOFError):
            print()
            notify('warning', "Cancelled.")
            return None
