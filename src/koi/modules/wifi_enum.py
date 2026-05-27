from __future__ import annotations

import re
from koi.modules.blueprint import KoiModule


class WifiEnumModule(KoiModule):
    name        = "wifi_enum"
    description = "Énumère proprement les réseaux Wi-Fi environnants et configurations via nmcli ou fichiers locaux."
    category    = "Enumeration"
    platform    = "linux"
    usage       = "wifi_enum <id>"

    def _get(self, cmd: str) -> str:
        try:
            return self._exec_clean(cmd, timeout=8)
        except Exception:
            return ""

    def run(self) -> None:
        self.status("Analyse Wi-Fi...")

        # 1. Réseaux visibles via nmcli
        with self.spinner("Scan des réseaux Wi-Fi..."):
            nmcli_res = self._get("nmcli --fields BARS,SSID,SECURITY device wifi list 2>/dev/null")

        if nmcli_res and "SSID" in nmcli_res:
            lines = nmcli_res.splitlines()
            scanned_networks = {}
            for idx, line in enumerate(lines[1:]):
                line_clean = line.strip()
                if line_clean:
                    scanned_networks[f"Réseau_{idx}"] = line_clean
            if scanned_networks:
                self.box("Réseaux détectés (via nmcli)", scanned_networks)
        else:
            self.warn("nmcli n'a pas renvoyé de résultats (vérifiez l'état de l'interface).")

        # 2. Profils wpa_supplicant
        self.status("Vérification des fichiers de configuration Wi-Fi...")

        wpa_conf = self._get("cat /etc/wpa_supplicant/wpa_supplicant.conf 2>/dev/null")
        creds = {}

        if wpa_conf and "network=" in wpa_conf:
            networks = re.findall(r'network=\{([^\}]+)\}', wpa_conf, re.DOTALL)
            for idx, net_block in enumerate(networks):
                ssid_m = re.search(r'ssid="([^"]+)"', net_block)
                psk_m  = re.search(r'psk="([^"]+)"', net_block)
                if ssid_m:
                    ssid = ssid_m.group(1)
                    psk  = psk_m.group(1) if psk_m else "[Clé absente]"
                    creds[f"wpa_supplicant ({ssid})"] = f"PSK: {psk}"

        if creds:
            self.box("Profils extraits", creds)
        else:
            self.status("Aucun profil lisible dans les dossiers standards.")

        self.success("Analyse Wi-Fi terminée.")