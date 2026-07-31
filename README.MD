# koi 🎏
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54) ![Linux](https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black) ![Windows](https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white) ![GitHub last commit (branch)](https://img.shields.io/github/last-commit/b3rt1ng/Koi/main?style=for-the-badge&color=rgb(235%2C%20111%2C%20%2092)) ![GitHub Repo stars](https://img.shields.io/github/stars/b3rt1ng/Koi?style=for-the-badge&labelColor=(169%2C%20169%2C%20169)&color=rgb(255%2C%20116%2C%200)) ![PyPI - Version](https://img.shields.io/pypi/v/koi-handler?style=for-the-badge&color=rgb(235%2C%20111%2C%20%2092))


This project is my shot at making a fast, easy to use (yet feature rich) shell handler with a pretty interface.

Disclaimer: please note that this is still under development, and I am still working on some of the key features, talked about in [this section](#-wip).

#### NEW WIKI [HERE](https://b3rt1ng.github.io/koi-wiki/) !!

## 📑 Table of Contents

[✨ Features](#-features) | [🚧 WIP](#-wip) | [🚀 Installation](#-installation) | [💻 Usage](#-usage) | [🔧 PTY Upgrade](#-pty-upgrade) | [🤖 Modules](#-modules) | [🧠 MCP](#-mcp)

Full documentation lives in the [wiki](https://b3rt1ng.github.io/koi-wiki/): [Getting Started](https://b3rt1ng.github.io/koi-wiki/getting-started/) · [CLI Reference](https://b3rt1ng.github.io/koi-wiki/cli-reference/) · [Configuration](https://b3rt1ng.github.io/koi-wiki/configuration/) · [Module Development](https://b3rt1ng.github.io/koi-wiki/modules-overview/) · [Troubleshooting](https://b3rt1ng.github.io/koi-wiki/troubleshooting/)
  
---

### Demo

<img src="https://i.imgur.com/RFD2dkE.gif" alt="demonstration">

> [!TIP]
> This demo runs with dockerized OS. If you want to try yourself, you can use the [Ubuntu images](https://hub.docker.com/_/ubuntu) or the [dockur](https://github.com/dockur/windows) windows
---

## ✨ Features

* **Multi-session**: handle multiple reverse shells simultaneously. List, switch, and background sessions without dropping any.
* **PTY Upgrade**: upgrade a raw shell to a full PTY (Linux via `script`/`socat`, Windows via obfuscated ConPtyShell) for tab completion, Ctrl+C forwarding, and terminal resizing.
* **Modules**: automate post-exploitation tasks, file transfer, enumeration, pivoting, AD collection, and more. Easily extensible with your own modules.
* **Obfuscator**: built-in payload obfuscator with chainable techniques (XOR, hex, format strings, char-array) to evade Defender and EDR solutions.
* **Session logging**: every session is logged automatically. Replay any session with `koireview`. ([docs](https://b3rt1ng.github.io/koi-wiki/logs/))
* **MCP server**: expose your sessions and modules to an LLM client, read-only by default. ([docs](https://b3rt1ng.github.io/koi-wiki/mcp/))
* **Screenable mode**: masks IPs and MAC addresses from output for safe screen sharing during CTFs or live demos.
* **Clean signals**: `Ctrl+Z` backgrounds the session, `Ctrl+C` sends `SIGINT` to the remote, never kills your listener by accident.

> [!NOTE]
> It is now possible to use Koi remotely !
> Read more [here](https://b3rt1ng.github.io/koi-wiki/go-online/)

## 🚧 WIP
* **Tunneling**: once you have your shell, a simple way to tunnel into that network with minimal input would be very convenient. The `ligolo` module automates agent deployment, but native tunnel management is planned.
* **EDR evasion**: Koi bypasses casual and mid-tier EDR solutions, but more aggressive environments (expensive commercial EDR, heavily monitored networks) may still flag activity. Further improvements (TLS transport, HTTP C2) are under consideration.
---

## 🚀 Installation

```bash
# directly from the repo to get the latest version
pipx install git+https://github.com/b3rt1ng/Koi

# or pypi
pipx install koi-handler

# From source if you want to dev your own modules
git clone https://github.com/b3rt1ng/koi
cd koi
pipx install --editable .

# with MCP support (optional extra, see the MCP section)
pipx install "koi-handler[mcp] @ git+https://github.com/b3rt1ng/Koi"
```

_This installation comes with `koifuscator` and `koireview`_

`koifuscator` is the direct shortcut to the obfuscator module.

`koireview` is your way to see the logs of your sessions.

To upgrade:
```
pipx upgrade koi-handler
```

More details in [Getting Started](https://b3rt1ng.github.io/koi-wiki/getting-started/).

---

## 💻 Usage

### Start the listener

```bash
# Default: bind 0.0.0.0:4010
koi

# Custom host/port
koi --host 10.10.14.5 --port 9001
koi -p 9001
```

Once inside, `help` lists every command. The full reference is in the [CLI Reference](https://b3rt1ng.github.io/koi-wiki/cli-reference/), and session handling (tags, backgrounding, screenable mode) in [Session Management](https://b3rt1ng.github.io/koi-wiki/sessions/).

#### Catch a shell

Send a reverse shell yourself or by typing `payloads *interface*` to get pregenerated payloads. Do note that it needs to be a terminal like shell, as Koi is manipulating linux shs, powershells and cmd.

##### Bypass Windows Defender

Koi includes a built-in payload obfuscator to help evade Windows Defender detection. You can chain multiple techniques together though XOR encoding and format transformations are usually sufficient. Keep in mind that stacking too many layers may corrupt the payload and make it unreadable by the target.

<a href="https://asciinema.org/a/1xnYShXuhoBhCUDX"><img src="https://asciinema.org/a/1xnYShXuhoBhCUDX.svg" alt="koi obfuscator demo" width="100%" /></a>

The obfuscator also works for Linux payloads. While most Linux environments don't run antivirus software, bash one-liners are commonly flagged by EDR solutions, IDS rules, or monitored by blue teams watching for known reverse shell patterns. Obfuscating your payload helps fly under the radar in some hardened environments.

Every technique and every supported payload type is listed in [Payloads & Obfuscation](https://b3rt1ng.github.io/koi-wiki/payloads/).

---

## 🔧 PTY Upgrade

Raw shells lack proper terminal support: no tab completion, broken `Ctrl+C`, mangled output. The `upgrade` command fixes this:

```
koi> upgrade 1
  Shell #1 upgraded successfully.
koi> go 1
  # now a full PTY with proper terminal behaviour
```

#### Under the hood
##### For linux:
a simple python pty is spawned
```bash
python3 -c 'import pty; pty.spawn("/bin/bash")'
```
with `TERM=xterm-256color` and some resizing info

##### For windows:
I did not bother making one for CMD, but for powershell the technique uses an obfuscated [conptyshell](https://github.com/antoniococo/conptyshell) to gather a fully implemented shell:

```
1) ConPtyShell is fetched from GitHub and cached locally for offline reuse
2) All IOC identifiers are renamed to random strings (class names, method names, PS function name)
3) Distinctive C# string literals are replaced with runtime char-array constructions (no literal in compiled MSIL)
4) The obfuscated script is served over a temporary HTTP server
5) The invocation command is base64-encoded (-EncodedCommand) with IEX and IWR obfuscated via random split techniques (concat / format string / char-array), so no plaintext cmdlet names appear on the command line
6) The target connects back with a fully interactive PTY shell, registered as a new session
```

Fallback chain and per-OS details in [Upgrading Sessions](https://b3rt1ng.github.io/koi-wiki/upgrading-sessions/).

---

### 🤖 Modules

<a href="https://asciinema.org/a/quY43wqm0jhsoypj"><img src="https://asciinema.org/a/quY43wqm0jhsoypj.svg" alt="koi module download on powershell" width="100%" /></a>

Modules are basically a way to automate actions on your instances. You can run commands and take advantage of your python backend.

If you want to make your own modules, I recommend cloning this repo and installing it with the `--editable` flag. Once you have a shell, you can dev your payload and use the `reload` command to update all modules including the one you're working on.

Check the [Module Development Guide](https://b3rt1ng.github.io/koi-wiki/modules-overview/) in the wiki for a full API reference, or browse the existing modules ([ligolo](src/koi/modules/ligolo.py), [get_users](src/koi/modules/get_users.py)) for inspiration.

Also, if you want to make your own module part of this repo, do not hesitate to make a PR, I will gladly look at it and see if it's interesting to add here <3

---

### 🧠 MCP

Koi can expose its sessions and modules over [MCP](https://modelcontextprotocol.io), so an LLM client can read your session table and drive modules without you copy-pasting anything.

```bash
# read-only: sessions, modules and logs
koi --mcp

# lets the model run commands and modules on targets
koi --mcp --mcp-allow-exec
```

The server runs in the listener process and binds `127.0.0.1:7331`, protected by a bearer token printed on startup. Read-only is the default on purpose.

> [!WARNING]
> With `--mcp-allow-exec` an LLM can run commands on every machine you hold a shell on. Session logs contain output from compromised hosts, which is attacker-controlled text going straight into the model context.

Setup, client configuration and the full tool list are in the [MCP documentation](https://b3rt1ng.github.io/koi-wiki/mcp/).

<div align="center">
  <img src="https://media1.tenor.com/m/pTHWYc7b8TsAAAAd/smiling-friends-dab.gif">
</div>