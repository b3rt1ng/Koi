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

        shells = ["/bin/bash", "/bin/sh", "/bin/zsh", "/bin/dash"]
        interesting_users = [u for u in users if any(shell in u[2] for shell in shells)]

        if self.args.all:
            self.table("All users", ["Username", "UID", "Shell"], users)
        if interesting_users:
            self.table("Interesting users", ["Username", "UID", "Shell"], interesting_users)

    def _run_windows(self) -> None:
        ps_cmd = (
            "Get-LocalUser | Select-Object @{"
            "Name='User';Expression={$_.Name}}, "
            "@{Name='SID';Expression={$_.SID.Value}}, "
            "@{Name='Enabled';Expression={$_.Enabled}}, "
            "@{Name='LastLogon';Expression={$_.LastLogon}} | "
            "ConvertTo-Json"
        )

        try:
            import json
            result = self._win_query(ps_cmd)
            if not result:
                self.err("Failed to enumerate users")
                return

            users_data = json.loads(result)
            if not isinstance(users_data, list):
                users_data = [users_data]

            users = []
            for user in users_data:
                username = user.get("User", "?")
                sid = user.get("SID", "?")
                enabled = str(user.get("Enabled", "?"))
                lastlogon = str(user.get("LastLogon", "Never"))
                users.append([username, sid, enabled, lastlogon])

            enabled_users = [u for u in users if u[2] == "True"]

            if self.args.all:
                self.table("All users", ["Username", "SID", "Enabled", "LastLogon"], users)
            if enabled_users:
                self.table("Enabled users", ["Username", "SID", "Enabled", "LastLogon"], enabled_users)

        except Exception as e:
            self.err(f"Error parsing user data: {e}")