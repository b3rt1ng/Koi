from __future__ import annotations

import re
from koi.modules.blueprint import KoiModule
from koi.utils.config import TIMEOUTS


class WifiEnumModule(KoiModule):
    name        = "wifi"
    description = "Cleanly enumerates nearby Wi-Fi networks and configurations via nmcli or local files."
    category    = "Enumeration"
    platform    = "linux"
    usage       = "wifi <id>"

    def run(self) -> None:
        self.status("Analyzing Wi-Fi...")

        with self.spinner("Scanning Wi-Fi networks..."):
            nmcli_res = self._try_exec("nmcli --fields BARS,SSID,SECURITY device wifi list 2>/dev/null", timeout=TIMEOUTS["exec_query"])

        if nmcli_res and "SSID" in nmcli_res:
            lines = nmcli_res.splitlines()
            scanned_networks = {}
            for line in lines[1:]:
                line_clean = line.strip()
                if not line_clean:
                    continue
                parts = re.split(r'\s{2,}', line_clean)
                ssid = parts[1].strip() if len(parts) > 1 else ""
                if not ssid or ssid == "--":
                    ssid = "hidden"
                key, n = ssid, 1
                while key in scanned_networks:
                    n += 1
                    key = f"{ssid} ({n})"
                scanned_networks[key] = line_clean
            if scanned_networks:
                self.box("Detected networks (via nmcli)", scanned_networks)
        else:
            self.warn("nmcli returned no results (check interface status).")

        self.status("Checking Wi-Fi configuration files...")

        wpa_conf = self._try_exec("cat /etc/wpa_supplicant/wpa_supplicant.conf 2>/dev/null", timeout=TIMEOUTS["exec_query"])
        creds = {}

        if wpa_conf and "network=" in wpa_conf:
            networks = re.findall(r'network=\{([^\}]+)\}', wpa_conf, re.DOTALL)
            for idx, net_block in enumerate(networks):
                ssid_m = re.search(r'ssid="([^"]+)"', net_block)
                psk_m  = re.search(r'psk="([^"]+)"', net_block)
                if ssid_m:
                    ssid = ssid_m.group(1)
                    psk  = psk_m.group(1) if psk_m else "[Key missing]"
                    creds[f"wpa_supplicant ({ssid})"] = f"PSK: {psk}"

        if creds:
            self.box("Extracted profiles", creds)
        else:
            self.status("No readable profiles found in standard locations.")

        self.success("Wi-Fi analysis complete.")