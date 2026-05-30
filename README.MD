# koi 🎏
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54) ![Linux](https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black) ![Windows](https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white) ![GitHub last commit (branch)](https://img.shields.io/github/last-commit/b3rt1ng/Koi/main?style=for-the-badge&color=rgb(235%2C%20111%2C%20%2092)) ![GitHub Repo stars](https://img.shields.io/github/stars/b3rt1ng/Koi?style=for-the-badge&labelColor=(169%2C%20169%2C%20169)&color=rgb(255%2C%20116%2C%200)) ![PyPI - Version](https://img.shields.io/pypi/v/koi-handler?style=for-the-badge&color=rgb(235%2C%20111%2C%20%2092))


This project is my shot at making a fast, easy to use (yet feature rich) shell handler with a pretty interface.

Disclaimer: please note that this is still under development, and I am still working on some of the key features, which is talked about in [this section](#-wip).

#### NEW WIKI [HERE](https://b3rt1ng.github.io/koi-wiki/) !!

## 📑 Table of Contents

[✨ Features](#-features) | [🚧 WIP](#-wip) | [🚀 Installation](#-installation) | [💻 Usage](#-usage) | [🔧 PTY Upgrade](#-pty-upgrade) | [🤖 Modules](#-modules)
  
---

### Demo

<img src="https://i.imgur.com/RFD2dkE.gif" alt="demonstration">

> [!TIP]
> This demo runs with dockerized OS. If you want to try yourself, you can use the [Ubuntu images](https://hub.docker.com/_/ubuntu) or the [dockur](https://github.com/dockur/windows) windows
---

## ✨ Features

* **Multi-session**: Handles multiple reverse shells simultaneously list, switch, and background sessions without dropping any.
* **PTY Upgrade**: Upgrades a raw shell to a full PTY for proper tab completion, Ctrl+C forwarding, and terminal resizing.
* **Modules**: Various modules to automate post exploitation tasks such as easy upload and download, simple information gathering and more 
* **Obfuscator**: Easy to use payload obfuscator, chaining obfuscation techniques to evade defender.
* **Clean signals**: `Ctrl+Z` backgrounds the session, `Ctrl+C` sends `SIGINT` to the remote never kills your listener by accident.
* **Koi fish themed UI**: sick UI, pentest tooling doesn't have to be ugly.

## 🚧 WIP
* **Windows**: Powershells are now available and upgradable with in-memory obfuscation to evade Windows Defender, but needs more testing.
* **Tunneling**: Once you have your shell, a simple way to tunnel in that network with few inputs would be very convenient.
* **EDR proof**: Koi is indeed conveinient but it's a rather "loud" method. While the payloads does bypass casual / low tier EDR, it can get flagged on more expensives solutions. I'm working on ways to make it even less flaggable (tls, http ?)
* **Logging**: right now, koi logs your sessions interraction, it's conveinient when doing pentest reports. Yet this feature is still a bit too primitive and needs  more upgrading. It's now a thing but it's  not the best (yet)
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
```

_This installation comes with `koifuscator` and `koireview`_

`koifuscator` is the direct shortcut to the obfuscator module.

`koireview` is your way to see the logs of your sessions.
> 
To upgrade:
```
pipx upgrade koi-handler
```

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

#### Catch a shell

Send a reverse shell yourself or by typing `payloads *interface*` to get pregenerated payloads. do note that it needs to be a terminal like shell, as Koi is manipulating linux shs, powershells and cmd.

##### Bypass Windows Defender

Koi includes a built-in payload obfuscator to help evade Windows Defender detection. You can chain multiple techniques together though XOR encoding and format transformations are usually sufficient. Keep in mind that stacking too many layers may corrupt the payload and make it unreadable by the target.

<a href="https://asciinema.org/a/1xnYShXuhoBhCUDX"><img src="https://asciinema.org/a/1xnYShXuhoBhCUDX.svg" alt="koi obfuscator demo" width="100%" /></a>

The obfuscator also works for Linux payloads. While most Linux environments don't run antivirus software, bash one-liners are commonly flagged by EDR solutions, IDS rules, or monitored by blue teams watching for known reverse shell patterns. Obfuscating your payload helps fly under the radar in some hardened environments.

---

## 🔧 PTY Upgrade

Raw shells lack proper terminal support, no tab completion, broken `Ctrl+C`, mangled output. The `upgrade` command fixes this:

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
I did not bothered making one for CMD but for powershell, the technique uses an obfuscated [conptyshell](https://github.com/antoniococo/conptyshell) to gather a fully implemented shell:

```
1) ConPtyShell is fetched from GitHub and kept in memory
2) All IOC identifiers are renamed to random strings (class names, method names, PS function name)
3) Distinctive C# string literals are replaced with runtime char-array constructions (no literal in compiled MSIL)
4) The obfuscated script is served over a temporary HTTP server and executed on the target via IEX(IWR ...)
5) The target connects back with a fully interactive PTY shell, registered as a new session
```

---



### 🤖 Modules

<a href="https://asciinema.org/a/quY43wqm0jhsoypj"><img src="https://asciinema.org/a/quY43wqm0jhsoypj.svg" alt="koi module download on powershell" width="100%" /></a>

Modules are basically a way to automate actions on your instances. you can run commands, and take advantage of your python backend.

If you want to make your own modules, I recommend cloning this repo and installing it with the `--editable` flag. Once you have a shell, you can dev your payload and use the `reload` command to update all modules including the one you're working on.

Checkout the [blueprint](src/koi/modules/blueprint.py) to see how you can make your own module or check our examples ([linpeas](src/koi/modules/ligolo.py), [get users](src/koi/modules/get_users.py)) to get inspirations

Also, if you want to make your own module part of this repo, do not hesitate to make a PR, I will gladly look at it and see if it's interesting to add here <3

<div align="center">
  <img src="https://media1.tenor.com/m/pTHWYc7b8TsAAAAd/smiling-friends-dab.gif">
</div>