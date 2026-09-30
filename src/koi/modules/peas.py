from __future__ import annotations

from koi.modules.blueprint import KoiModule

LINPEAS_URL = "https://github.com/peass-ng/PEASS-ng/releases/latest/download/linpeas.sh"
WINPEAS_URL = "https://github.com/peass-ng/PEASS-ng/releases/latest/download/winPEASx64.exe"


class PeasModule(KoiModule):
    name = "peas"
    description = "Fetch the latest LinPEAS/winPEAS release and upload it to the target"
    usage = "peas <id> [-o <remote_path>]"
    category = "Privilege Escalation"
    platform = ["linux", "windows_ps"]
    arguments = [
        {"flags": ["-o", "--output"], "default": None, "help": "Remote destination path"},
    ]
    external_resources = [
        {
            "name": "linpeas.sh",
            "url": LINPEAS_URL,
            "cache_key": "linpeas.sh",
        },
        {
            "name": "winPEASx64.exe",
            "url": WINPEAS_URL,
            "cache_key": "winPEASx64.exe",
        },
    ]

    def run(self) -> None:
        if self.session.os_type == "linux":
            url, name = LINPEAS_URL, "linpeas.sh"
            dest = self.args.output or f"./{name}"
        else:
            url, name = WINPEAS_URL, "winPEASx64.exe"
            dest = self.args.output or f".\\{name}"

        raw = self._fetch_and_deploy(
            dest, url=url, cache_key=name, label=name,
            chmod=(self.session.os_type == "linux"),
        )
        if raw is None:
            return

        self.box("Upload complete", {
            "tool":        name,
            "remote path": dest,
            "size":        f"{len(raw)} bytes  ({len(raw)/1024:.1f} KB)",
        })
