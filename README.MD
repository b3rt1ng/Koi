# koi 🎏
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54) ![Linux](https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black) ![Windows](https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white) ![GitHub last commit (branch)](https://img.shields.io/github/last-commit/b3rt1ng/Koi/main?style=for-the-badge&color=rgb(235%2C%20111%2C%20%2092)) ![GitHub Repo stars](https://img.shields.io/github/stars/b3rt1ng/Koi?style=for-the-badge&labelColor=(169%2C%20169%2C%20169)&color=rgb(255%2C%20116%2C%200))


This project is my shot at making a fast, easy to use (yet feature rich) shell handler with a pretty interface.

Disclaimer: please note that this is still under development, and I am still working on some of the key features, which is talked about in [this section](#-wip).

---

### Demo

<img src="https://i.imgur.com/RFD2dkE.gif" alt="demonstration">

> [!TIP]
> This demo runs with dockerized OS. If you want to try yourself, you can use the [Ubuntu images](https://hub.docker.com/_/ubuntu) or the [dockur](https://github.com/dockur/windows) windows
---

## ✨ Features

* **Multi-session**: Handles multiple reverse shells simultaneously list, switch, and background sessions without dropping any.
* **PTY Upgrade**: Upgrades a raw shell to a full PTY for proper tab completion, Ctrl+C forwarding, and terminal resizing.
* **Clean signals**: `Ctrl+Z` backgrounds the session, `Ctrl+C` sends `SIGINT` to the remote never kills your listener by accident.
* **Koi fish themed UI**: Gradient prompt, status indicators, and session boxes, pentest tooling doesn't have to be ugly.

## 🚧 WIP
* **Windows**: Powershells are now available and upgradable, but needs some testings.
* **Tunneling**: Once you have your shell, a simple way to tunnel in that network would be very convenient, this has yet to be done.
* **Modules**: Modules for linux are easy to implement. Windows on the other hand, is inherently "stranger". I am thinking about a way to make it more dev friendly.
* **Testings**: I've tried my tool on CTF and personal devices but it still needs more testing. As of now, this has been made for linux based shells but I want it to be able to work under windows powershell with all it's implications.
---

## 🚀 Installation

```bash
# directly from the repo
pipx install git+https://github.com/b3rt1ng/Koi

# or pypi
pipx install koi-handler

# From source if you want to dev your own modules
git clone https://github.com/b3rt1ng/koi
cd koi
pipx install --editable .
```

---

## 💻 Usage

### Start the listener

```bash
# Default: bind 0.0.0.0:4444
koi

# Custom host/port
koi --host 10.10.14.5 --port 9001
koi -p 9001
```

#### Catch a shell

Send a reverse shell yourself or by typing `payloads *interface*` to get pregenerated payloads. do note that it needs to be a terminal like shell, as Koi is manipulating linux shs, powershells and cmd.

##### Buypass defender !

Koi provides two obfuscated PowerShell payload variants:

- **`powershell (hex)`** — encodes string literals as hex bytes via `[System.Text.Encoding]::UTF8.GetString([byte[]](0x...))`. Adds obfuscation but does not reliably bypass Windows Defender on its own.
- **`powershell (syntax)`** — splits cmdlet names (`New-Object`, `iex`, `Out-String`...) into randomly concatenated fragments invoked via the `&` call operator, e.g. `&("Ne"+"w-Object")`. The split position and quote style are randomized on each generation, making static signatures ineffective. This variant bypasses Windows Defender.
- **`powershell (hex+syntax)`** — applies both techniques at once: cmdlets are fragmented first, then all string literals (including the ones introduced by the syntax pass) are hex-encoded.

---

## 🔧 PTY Upgrade

Raw shells lack proper terminal support — no tab completion, broken `Ctrl+C`, mangled output. The `upgrade` command fixes this:

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
I did not bothered making one for CMD but for powershell, the technique uses [conptyshell](https://github.com/antoniococo/conptyshell) to gather a fully implemented shell:

```
# 1 Conptyshell is downloaded in memory
# 2 It's sent to your target and executed to be sent back to you
# 3 Koi waits for the shell to reach and puts it as new session
```

> [!WARNING]
> <small>_the origin session will be kept alive but you can still kill it and play with the upgraded shell. Just know that as it's technically running the upgraded session, you won't be able to interact much with it._</small>

---



### 🤖 Modules

<a href="https://asciinema.org/a/quY43wqm0jhsoypj"><img src="https://asciinema.org/a/quY43wqm0jhsoypj.svg" alt="koi module download on powershell" width="100%" /></a>

Modules are basically a way to automate actions on your instances. you can run commands, and take advantage of your python backend.

If you want to make your own modules, I recommend cloning this repo and installing it with the `--editable` flag. Once you have a shell, you can dev your payload and use the `reload` command to update all modules including the one you're working on.

Checkout the [blueprint](src/koi/modules/blueprint.py) to see how you can make your own module or check our examples ([linpeas](src/koi/modules/linpeas.py), [get users](src/koi/modules/get_users.py)) to get inspirations

Also, if you want to make your own module part of this repo, do not hesitate to make a PR, I will gladly look at it and see if it's interesting to add here <3

<div align="center">
  <img src="https://media1.tenor.com/m/pTHWYc7b8TsAAAAd/smiling-friends-dab.gif">
</div>