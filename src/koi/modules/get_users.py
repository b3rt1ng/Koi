from __future__ import annotations

from koi.modules.blueprint import KoiModule


class GetUsersModule(KoiModule):
    name = "users"
    description = "List local users on Linux (/etc/passwd) or Windows (Get-LocalUser)."
    usage = "users <id> [-a]"
    category = "Enumeration"
    platform = ["linux", "windows_ps"]
    arguments = [
        {
            "flags": ["-a", "--all"],
            "action": "store_true",
            "default": False,
            "help": "Show all users, not just interesting ones.",
        },
    ]

    def run(self) -> None:
        if self.session.os_type == "linux":
            self._run_linux()
        else:
            self._run_windows()

    def _run_linux(self) -> None:
        result = self.exec("cat /etc/passwd")
        if not result.success:
            self.err(f"Could not read /etc/passwd (rc={result.returncode})")
            return

        users = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) < 7:
                continue
            username, _, uid, _, _, _, shell = parts[:7]
            users.append([username, uid, shell])

        if not users:
            self.err("No users parsed from /etc/passwd.")
            return

        shells = ["/bin/bash", "/bin/sh", "/bin/zsh", "/bin/dash"]
        interesting_users = [u for u in users if any(shell in u[2] for shell in shells)]

        headers = ["Username", "UID", "Shell"]
        if self.args.all or not interesting_users:
            self.table("All users", headers, users)
        if interesting_users:
            self.table("Interesting users", headers, interesting_users)

    def _run_windows(self) -> None:
        # ASCII-only separators: a non-ASCII separator (e.g. '§') does not
        # survive the command's cp1252 -> UTF-8 console round-trip on an
        # upgraded ConPtyShell, which collapses the joined output into a single
        # record. 'KOISEP' / '|||' are ASCII and pass through unchanged.
        ps_expr = (
            "(Get-LocalUser | ForEach-Object {"
            "\"$($_.Name)|||$($_.SID.Value)|||$($_.Enabled)|||$($_.LastLogon)\""
            "}) -join 'KOISEP'"
        )

        raw = self._win_query(ps_expr)
        if not raw:
            self.err("Failed to enumerate users")
            return

        users = []
        for entry in raw.split("KOISEP"):
            entry = self._clean(entry)
            if "|||" not in entry:
                continue
            fields = entry.split("|||")
            if len(fields) < 4:
                continue
            username, sid, enabled, lastlogon = (f.strip() for f in fields[:4])
            if not username:
                continue
            users.append([username, sid, enabled, lastlogon or "Never"])

        if not users:
            self.err("Failed to enumerate users")
            return

        headers = ["Username", "SID", "Enabled", "LastLogon"]
        enabled_users = [u for u in users if u[2] == "True"]

        if self.args.all or not enabled_users:
            self.table("All users", headers, users)
        if enabled_users:
            self.table("Enabled users", headers, enabled_users)