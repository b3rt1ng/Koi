from __future__ import annotations

from koi.modules.blueprint import KoiModule

_DANGEROUS_PRIVS: dict[str, str] = {
    "SeImpersonatePrivilege":        "Potato attacks (PrintSpoofer, RoguePotato, GodPotato)",
    "SeAssignPrimaryTokenPrivilege": "Potato attacks / token assignment",
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

    def _q(self, expr: str, timeout: float = 15.0) -> str:
        try:
            return self._win_query(expr, timeout=timeout).strip()
        except Exception:
            return ""

    def run(self) -> None:
        critical: dict[str, str] = {}
        high:     dict[str, str] = {}
        info:     dict[str, str] = {}

        with self.spinner("Checking privileges..."):
            raw = self._q(
                "((whoami /priv) -match 'Enabled'"
                " | ForEach-Object { (($_ -split '\\s{2,}')[0]).Trim() }) -join '§'"
            )
        for priv in (p.strip() for p in raw.split("§") if p.strip()):
            if priv in _DANGEROUS_PRIVS:
                critical[priv] = _DANGEROUS_PRIVS[priv]

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
            critical["AlwaysInstallElevated"] = "HKLM + HKCU both set, install any MSI as SYSTEM"
        elif hklm == "1" or hkcu == "1":
            high["AlwaysInstallElevated (partial)"] = f"HKLM={hklm or '0'}  HKCU={hkcu or '0'}, only one key set"

        with self.spinner("Checking UAC level..."):
            uac = self._q(
                "(Get-ItemProperty"
                " 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System'"
                ").ConsentPromptBehaviorAdmin"
            )
        label = _UAC_LEVELS.get(uac, f"Level {uac}")
        if uac == "0":
            critical["UAC disabled"] = label
        else:
            info[f"UAC level {uac}"] = label

        with self.spinner("Checking unquoted service paths..."):
            raw = self._q(
                "(Get-WmiObject Win32_Service"
                " | Where-Object { $_.StartMode -ne 'Disabled'"
                " -and $_.PathName -match ' '"
                " -and $_.PathName -notmatch '^\"'"
                " -and $_.PathName -notmatch '^C:\\\\Windows\\\\' }"
                " | ForEach-Object { \"$($_.Name)|||$($_.PathName)\" }) -join '§'",
                timeout=20,
            )
        for entry in (e for e in raw.split("§") if "|||" in e):
            name, path = entry.split("|||", 1)
            high[f"Unquoted path: {name.strip()}"] = path.strip()

        with self.spinner("Checking writable PATH directories..."):
            raw = self._q(
                "($env:PATH.Split(';') | ForEach-Object {"
                " $d = $_.Trim();"
                " if($d -and (Test-Path $d)) {"
                "  try {"
                "   $t = Join-Path $d '_koi_test.tmp';"
                "   [IO.File]::OpenWrite($t).Close();"
                "   Remove-Item $t -EA SilentlyContinue; $d"
                "  } catch {} } }) -join '§'"
            )
        for d in (x.strip() for x in raw.split("§") if x.strip()):
            high[f"Writable PATH: {d}"] = "DLL / binary hijack possible"

        with self.spinner("Checking stored credentials..."):
            raw = self._q("(cmdkey /list) -join '§'")
        creds = [l.strip() for l in raw.split("§") if "Target:" in l or "User:" in l]
        if creds:
            high["Stored credentials"] = "  |  ".join(creds)

        with self.spinner("Checking sensitive files..."):
            files_expr = "@(" + ",".join(f"'{f}'" for f in _SENSITIVE_FILES) + ")"
            raw = self._q(f"({files_expr} | Where-Object {{Test-Path $_}}) -join '§'")
        for f in (x.strip() for x in raw.split("§") if x.strip()):
            high[f"Sensitive file: {f}"] = "May contain plaintext credentials"

        with self.spinner("Checking scheduled tasks..."):
            raw = self._q(
                "(Get-ScheduledTask"
                " | Where-Object { $_.State -ne 'Disabled'"
                " -and ($_.Principal.UserId -match 'SYSTEM'"
                " -or $_.Principal.RunLevel -eq 'Highest') }"
                " | ForEach-Object {"
                "  $a = $_.Actions | Where-Object { $_.Execute } | Select-Object -First 1;"
                "  if($a){ \"$($_.TaskName)|||$($a.Execute)\" }"
                " }) -join '§'",
                timeout=20,
            )
        for entry in (e for e in raw.split("§") if "|||" in e):
            name, exe = entry.split("|||", 1)
            name, exe = name.strip(), exe.strip()
            if exe:
                info[f"Task (SYSTEM): {name}"] = exe

        with self.spinner("Checking AutoRun entries..."):
            raw = self._q(
                "(@("
                " 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run',"
                " 'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run'"
                ") | ForEach-Object { $k = $_;"
                " try { (Get-ItemProperty $k -EA Stop).PSObject.Properties"
                "  | Where-Object { $_.Name -notlike 'PS*' }"
                "  | ForEach-Object { \"$($_.Name)|||$($_.Value)\" }"
                " } catch {} }) -join '§'"
            )
        for entry in (e for e in raw.split("§") if "|||" in e):
            name, val = entry.split("|||", 1)
            info[f"AutoRun: {name.strip()}"] = val.strip()

        has_potato = any(
            p in critical
            for p in ("SeImpersonatePrivilege", "SeAssignPrimaryTokenPrivilege")
        )
        if has_potato:
            critical["Potato attack feasible"] = (
                "SeImpersonate/SeAssignPrimaryToken enabled, try PrintSpoofer, GodPotato"
            )

        print()
        if critical:
            self.box("Critical - direct privesc vectors", critical)
        if high:
            self.box("High - notable findings", high)
        if info:
            self.box("Info", info)

        total = len(critical) + len(high) + len(info)
        if total == 0:
            self.ok("No obvious privilege escalation vectors found.")
        else:
            self.status(f"{total} finding(s): {len(critical)} critical, {len(high)} high, {len(info)} info")
