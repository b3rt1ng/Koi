from koi.modules.blueprint import KoiModule


class GetUsersModule(KoiModule):
    name = "get_users"
    description = "List local users by reading /etc/passwd on the target."
    usage = "run get_users <id>"

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

        self.box(f"Users on #{self.session.id}", users)