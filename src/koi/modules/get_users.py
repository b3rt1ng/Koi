from koi.modules.blueprint import KoiModule


class GetUsersModule(KoiModule):
    name = "get_users"
    description = "List local users by reading /etc/passwd on the target."
    usage = "get_users <id> [all]"
    category = "Enumeration"

    def run(self) -> None:
        result = self.exec("cat /etc/passwd")
        if not result.success:
            self.err(f"Could not read /etc/passwd (rc={result.returncode})")
            return

        users = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) < 7:
                continue
            username, _, uid, _, _, _, shell = parts[:7]
            users[username] = f"uid={uid}  shell={shell}"
        
        shells = ["/bin/bash", "/bin/sh", "/bin/zsh", "/bin/dash"]
        interesting_users = {}

        for username, info in users.items():
            if any(shell in info for shell in shells):
                interesting_users[username] = info

        if "all" in self.raw_args:
            self.box(f"All users ({len(users)})", users)
        if interesting_users:
            self.box(f"There are {len(interesting_users)} interesting users", interesting_users)