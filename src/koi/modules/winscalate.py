from __future__ import annotations

from koi.modules.blueprint import KoiModule
from koi.utils.config import TIMEOUTS

_DANGEROUS_PRIVS: dict[str, str] = {
    "SeImpersonatePrivilege":        "Potato attacks (PrintSpoofer, RoguePotato, GodPotato)",
    "SeAssignPrimaryTokenPrivilege": "Primary token assignment (requires SeIncreaseQuotaPrivilege for full privesc)",
    "SeDebugPrivilege":              "Process injection, LSASS dump",
    "SeTakeOwnershipPrivilege":      "Take ownership of any object",
    "SeLoadDriverPrivilege":         "Load malicious kernel driver (BYOVD)",
    "SeBackupPrivilege":             "Read SAM/SYSTEM hives",
    "SeRestorePrivilege":            "Write arbitrary files",
    "SeCreateSymbolicLinkPrivilege": "Symlink attacks",
}

_UAC_LEVELS: dict[str, str] = {
    "0": "Disabled, no prompt, auto-elevate everything",
    "1": "Prompt for credentials on secure desktop",
    "2": "Prompt for consent on secure desktop",
    "5": "Default, prompt for non-Windows binaries",
}

_SENSITIVE_FILES = [
    "C:\\unattend.xml",
    "C:\\Windows\\Panther\\unattend.xml",
    "C:\\Windows\\Panther\\Unattended.xml",
    "C:\\Windows\\sysprep\\sysprep.xml",
    "C:\\Windows\\sysprep\\sysprep.inf",
    "C:\\inetpub\\wwwroot\\web.config",
    "C:\\Windows\\debug\\NetSetup.log",
]


class WinscalateModule(KoiModule):
    name        = "winscalate"
    description = "Check common Windows privilege escalation vectors."
    category    = "Privilege Escalation"
    platform    = "windows_ps"
    usage       = "winscalate <id>"

    def _q(self, expr: str, timeout: float | None = None) -> str:
        timeout = timeout or TIMEOUTS["exec_query"]
        try:
            return self._win_query(expr, timeout=timeout).strip()
        except Exception:
            return ""

    def _emit(self, label: str, findings: dict) -> int:
        if findings:
            self.box(label, findings)
        return len(findings)

    def run(self) -> None:
        if not self.session.upgraded:
            self.warn(
                "Session is not upgraded, results may be incomplete or truncated. "
                "Run upgrade first for accurate output."
            )

        print()
        n_critical = n_high = n_info = 0

        with self.spinner("Checking privileges..."):
            raw = self._q("((whoami /priv) -match 'Enabled') -join 'KOISEP'")
        privs = {p: _DANGEROUS_PRIVS[p] for p in _DANGEROUS_PRIVS if p in raw}
        if "SeImpersonatePrivilege" in privs:
            privs["Potato attack feasible"] = "SeImpersonatePrivilege enabled, try PrintSpoofer, GodPotato, RoguePotato"
        n_critical += self._emit("Critical - dangerous privileges", privs)

        with self.spinner("Checking AlwaysInstallElevated..."):
            hklm = self._q(
                "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\Installer'"
                " -Name AlwaysInstallElevated -EA SilentlyContinue).AlwaysInstallElevated"
            )
            hkcu = self._q(
                "(Get-ItemProperty 'HKCU:\\SOFTWARE\\Policies\\Microsoft\\Windows\\Installer'"
                " -Name AlwaysInstallElevated -EA SilentlyContinue).AlwaysInstallElevated"
            )
        if hklm == "1" and hkcu == "1":
            n_critical += self._emit("Critical - AlwaysInstallElevated", {
                "AlwaysInstallElevated": "HKLM + HKCU both set, install any MSI as SYSTEM"
            })
        elif hklm == "1" or hkcu == "1":
            n_high += self._emit("High - AlwaysInstallElevated (partial)", {
                "AlwaysInstallElevated": f"HKLM={hklm or '0'}  HKCU={hkcu or '0'}, only one key set"
            })

        with self.spinner("Checking UAC level..."):
            uac = self._q(
                "(Get-ItemProperty"
                " 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System'"
                ").ConsentPromptBehaviorAdmin"
            )
        label = _UAC_LEVELS.get(uac, f"Level {uac}")
        if uac == "0":
            n_critical += self._emit("Critical - UAC disabled", {"UAC": label})
        else:
            n_info += self._emit("Info - UAC", {f"UAC level {uac}": label})

        with self.spinner("Checking unquoted service paths..."):
            raw = self._q(
                "(Get-WmiObject Win32_Service"
                " | Where-Object { $_.StartMode -ne 'Disabled'"
                " -and $_.PathName -match ' '"
                " -and $_.PathName -notmatch '^\"'"
                " -and $_.PathName -notmatch '^C:\\\\Windows\\\\' }"
                " | ForEach-Object { \"$($_.Name)|||$($_.PathName)\" }) -join 'KOISEP'",
                timeout=TIMEOUTS["exec_query"],
            )
        unquoted = {}
        for entry in (e for e in raw.split("KOISEP") if "|||" in e):
            name, path = entry.split("|||", 1)
            unquoted[f"Unquoted path: {name.strip()}"] = path.strip()
        n_high += self._emit("High - unquoted service paths", unquoted)

        with self.spinner("Checking writable PATH directories..."):
            raw = self._q(
                "($env:PATH.Split(';') | ForEach-Object {"
                " $d = $_.Trim();"
                " if($d -and (Test-Path $d)) {"
                "  try {"
                "   $t = Join-Path $d '_koi_test.tmp';"
                "   [IO.File]::OpenWrite($t).Close();"
                "   Remove-Item $t -EA SilentlyContinue; $d"
                "  } catch {} } }) -join 'KOISEP'"
            )
        writable = {d: "DLL / binary hijack possible" for d in (x.strip() for x in raw.split("KOISEP") if x.strip())}
        n_high += self._emit("High - writable PATH directories", writable)

        with self.spinner("Checking stored credentials..."):
            raw = self._q("(cmdkey /list) -join 'KOISEP'")
        creds = [l.strip() for l in raw.split("KOISEP") if "Target:" in l or "User:" in l]
        if creds:
            n_high += self._emit("High - stored credentials", {"cmdkey": "  |  ".join(creds)})

        with self.spinner("Checking sensitive files..."):
            files_expr = "@(" + ",".join(f"'{f}'" for f in _SENSITIVE_FILES) + ")"
            raw = self._q(f"({files_expr} | Where-Object {{Test-Path $_}}) -join 'KOISEP'")
        sensitive = {f: "May contain plaintext credentials" for f in (x.strip() for x in raw.split("KOISEP") if x.strip())}
        n_high += self._emit("High - sensitive files", sensitive)

        with self.spinner("Checking scheduled tasks..."):
            raw = self._q(
                "(Get-ScheduledTask"
                " | Where-Object { $_.State -ne 'Disabled'"
                " -and ($_.Principal.UserId -match 'SYSTEM'"
                " -or $_.Principal.RunLevel -eq 'Highest') }"
                " | ForEach-Object {"
                "  $a = $_.Actions | Where-Object { $_.Execute } | Select-Object -First 1;"
                "  if($a){ \"$($_.TaskName)|||$($a.Execute)\" }"
                " }) -join 'KOISEP'",
                timeout=TIMEOUTS["exec_query"],
            )
        tasks = {}
        for entry in (e for e in raw.split("KOISEP") if "|||" in e):
            name, exe = entry.split("|||", 1)
            name, exe = name.strip(), exe.strip()
            if exe and not any(exe.lower().startswith(p) for p in ("%windir%\\system32", "%systemroot%\\system32", "c:\\windows\\system32")):
                tasks[name] = exe
        n_info += self._emit("Info - scheduled tasks (SYSTEM, non-system path)", tasks)

        with self.spinner("Checking AutoRun entries..."):
            raw = self._q(
                "(@("
                " 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run',"
                " 'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run'"
                ") | ForEach-Object { $k = $_;"
                " try { (Get-ItemProperty $k -EA Stop).PSObject.Properties"
                "  | Where-Object { $_.Name -notlike 'PS*' }"
                "  | ForEach-Object { \"$($_.Name)|||$($_.Value)\" }"
                " } catch {} }) -join 'KOISEP'"
            )
        autorun = {}
        for entry in (e for e in raw.split("KOISEP") if "|||" in e):
            name, val = entry.split("|||", 1)
            autorun[name.strip()] = val.strip()
        n_info += self._emit("Info - AutoRun entries", autorun)

        total = n_critical + n_high + n_info
        if total == 0:
            self.ok("No obvious privilege escalation vectors found.")
        else:
            self.status(f"{total} finding(s): {n_critical} critical, {n_high} high, {n_info} info")
