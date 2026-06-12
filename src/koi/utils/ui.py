import re
import shutil
import sys
import threading
import time
import importlib.metadata
from random import choice

from koi.utils.config import color

_ANSI = re.compile(r"\033\[[^m]*m")

PUMPKIN     = color("pumpkin")
WHITE       = color("white")
SILVER      = color("silver")
CORAL       = color("coral")
UMBER       = color("umber")
BLUE        = color("blue")
RST = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"

__version__ = importlib.metadata.version("koi-handler")

def bold(t):   return f"{BOLD}{t}{RST}"
def dim(t):    return f"{DIM}{t}{RST}"
def alert(t):  return colored_text(t, CORAL)
def plain(t):  return colored_text(t, WHITE)
def accent(t): return colored_text(t, PUMPKIN)
def muted(t):  return colored_text(t, SILVER)
def cyan(t):   return colored_text(t, BLUE)

MOTD = ["The serene shell handler", 
        "La root est longue mais la voie est libre ;)",
        "流れに逆らう鯉のように",
        "¯＼(º_o)/¯",
        "Do not download and run random modules...",
        "AD is not that scary, I promise!",
        "(⌐▨_▨)",
        "don't forget to star the repo <3",
        "Use koireview to see your shells history",
        "You can use \"koifuscator\" to directly use the obfuscator"
]

def whole_line(char=" "):
    return (char * shutil.get_terminal_size().columns)

def color_signal(signal):
    return f"\033[38;2;{signal[0]};{signal[1]};{signal[2]}m"


def gradient_text(text, start_color=PUMPKIN, end_color=WHITE):
    if not sys.stdout.isatty():
        return text

    result = ""
    length = len(text)
    for i, char in enumerate(text):
        ratio = i / max(length - 1, 1)
        r = int(start_color[0] + ratio * (end_color[0] - start_color[0]))
        g = int(start_color[1] + ratio * (end_color[1] - start_color[1]))
        b = int(start_color[2] + ratio * (end_color[2] - start_color[2]))
        result += f"\033[38;2;{r};{g};{b}m{char}"
    result += RST
    return result


def colored_text(text, foreground_color, background_color=None):
    if not sys.stdout.isatty():
        return str(text)

    r, g, b = foreground_color
    if background_color:
        bg_r, bg_g, bg_b = background_color
        return f"\033[38;2;{r};{g};{b}m\033[48;2;{bg_r};{bg_g};{bg_b}m{text}{RST}"
    else:
        return f"\033[38;2;{r};{g};{b}m{text}{RST}"


def display_art(small: bool = False):
    terminal_width = shutil.get_terminal_size().columns
    art = f"""
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(PUMPKIN)}⡀⡀⡀⡀⡀⡀⡀⡀⡀{color_signal(WHITE)}⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⢀⢠⠰{color_signal(PUMPKIN)}⠠⡱⣳⡳⣟⢞⡝⣝⢮⢪⢮⣪⡪⡢⡢{color_signal(WHITE)}⡀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⢄⠌⢎⠣⠡⠡{color_signal(PUMPKIN)}⡙⢜⠘{color_signal(WHITE)}⠄⡑⠌⠂⠁⠁⠃⠳{color_signal(PUMPKIN)}⡝⣞⢼⢜⣌{color_signal(WHITE)}⠢⠀⠀⠀⠀⠀⠀⠀⠀⠀⡀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⢠⢵⠱⡑⠅⠅⢅⠑⢌⠂⠅⠁⠀⠀⠀⠀⠀⠀⠀⠈⡊⡊{color_signal(PUMPKIN)}⡊⠪⡑{color_signal(WHITE)}⢕⢐⢄⢀⠀⠀⠀⡀⡂⡂⠢⠡⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(PUMPKIN)}oooo    {color_signal(UMBER)}oooo {color_signal(WHITE)}  .oooooo.   oo{color_signal(UMBER)}ooo ⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(WHITE)}⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⢬⢺⢱⢑⢌⢌⢌⠢⠨⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠐⠈⠂⢌⢂⢂⢂⢂⠂⢀⢢⢪⢢⠪⠨⠨⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(PUMPKIN)}`888 {color_signal(UMBER)}  .8P' {color_signal(WHITE)}  d8P'  `Y8b  `{color_signal(UMBER)}888' ⠀⠀⠀⠀⠀{color_signal(WHITE)}⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⢌⢎⢎⢎⢎⢎⢆⠅⠅⠁⠀⠀⠀⠀⠀⠀⠀⠀⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠂⠂⠀⠀⢢⢣⢣⡣⡣⡡⡑⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀ {color_signal(PUMPKIN)}888  d8{color_signal(UMBER)}'  {color_signal(WHITE)}  888      888  8{color_signal(UMBER)}88  ⠀⠀{color_signal(WHITE)}⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⢌⢮⢪⢪⢪⢪⢪⢢⠡⠁⠀⠀⠀⠀⠀⠀⠀{color_signal(UMBER)}⢀⠐⠔⡘⢜⠘⠌⢮⢢{color_signal(WHITE)}⢢⢢⢢⢢⢠⠠⡈⡎⣎⢮⢪⢪⠢⠨⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(PUMPKIN)} 88888[    {color_signal(WHITE)}  888      888  88{color_signal(UMBER)}8  ⠀⠀⠀⠀⠀⠀⠀{color_signal(WHITE)}⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠈⢮{color_signal(CORAL)}⣺⢸⢸⢸⢸⢸⢐{color_signal(WHITE)}⢕⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(UMBER)}⡂⠌⡐⢌⠢⠡⡑⡑⡑{color_signal(WHITE)}⢕⢕⢕⠵⢽⢽⡺⣵⣣⡳⡱⡱⠡⠡⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(PUMPKIN)}⠀ 888`88b.  {color_signal(WHITE)}  888      888  888  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⢵⢯{color_signal(CORAL)}⡺⡸⡸⡸⡸⡸⡐{color_signal(WHITE)}⡐⡐⡐⢄⠀⠀⠀⠀⠀{color_signal(UMBER)}⢑⢈⠢⠡⡑⡐⡐{color_signal(WHITE)}⢌⢂⠢⡑⡑⢕⠳⡱⡱⣱⢹⢜⠌⠌⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(PUMPKIN)}⠀ 888  `88b. {color_signal(WHITE)} {color_signal(SILVER)}`88b   {color_signal(WHITE)} d88'  888  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⢯⣻⡪⡪⠪⡪⡪⡪⡪⡂⡪⡨⢢⠂⠀⠀⠀⠀⠀⠀⠅⡑⡐⡐⢌⢆⠢⡑⡐⢌⠢⡑⠌⢎⢎⢇⢗⢵⡱⡠⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(PUMPKIN)}⠀⠀o888o  o888o {color_signal(WHITE)} {color_signal(SILVER)}`Y8bo{color_signal(WHITE)}od8P'  o888o ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⢹⡾⣝⠆⠅⡂⠌⢎⢎⢎⢪⢈⠪⠀⠀⠀⠀⠀⠀⠀⠀⠐⠐⠈⠆⢇⢕⠐⢌⠢⠑⠌⢌⢆⢂⠊⡎⡎⡮⣺{color_signal(PUMPKIN)}⣦⢀⠀⠀⠀{color_signal(WHITE)}
⠀{color_signal(UMBER)}⠂⢿⡸⣣{color_signal(WHITE)}⡁⡢⠡⠡⡑⠌⢌⢪⢪⠠⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠠⠑⠕⢄⢅⢅⢑⢐⠐⠄⢕⢜⢜{color_signal(PUMPKIN)}⢼⢿⣾⣳⣔⢀⠀⠀⠀{color_signal(WHITE)}⠀⠀{choice(MOTD)}
⠀{color_signal(UMBER)}⠈⠸⡽⣿⣽⣮{color_signal(WHITE)}⡪⡢⡨⡨⡢⡣⡣⠣⠣⡪⡐⠄⢄⠀⠀⠀⠀⠀⠀⠀⠀⠁⠂⡑⡑⡐⠄⠅⢅⢑⠱⡱⡣{color_signal(PUMPKIN)}⡫⣺⢻⡚⣆⠀⠀⠀⠀⠀⠀⠀{color_signal(WHITE)}⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀{color_signal(UMBER)}⠹⡽⣾⣷⡻{color_signal(WHITE)}⡸⡸⡸⡸⡨⠨⡈⡂⡂⠪⡘⢜⢜⢔⢐⠐⠌⠌⠀⠀⠀⠀⢂⠢⠨⠨⡈⡂⠢⡑⢜⢯⣎⢎{color_signal(PUMPKIN)}⢎⢎⢎⢎⠄⠀⠀⠀{color_signal(WHITE)}⠀  V.{__version__}
⠀⠀⠀⠀{color_signal(UMBER)}⠘⢽⢞⢮{color_signal(WHITE)}⢪⢪⢪⠪⡈⡂{color_signal(UMBER)}⡂⠢⡈⠢⠨{color_signal(WHITE)}⡘⢜⢜⠬⡨⡨⡐⡀⠀⠀⠀⠠⠡⠡⢁⠂⠌⠢⡈⡂⠣⡫⣷⠱⡱⡱⡱⡱⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠣⡣⡣⡣⡣⡣⡂⡢{color_signal(UMBER)}⡈⠢⠨⡈⠢⡈⠢{color_signal(WHITE)}⡑⢕⢕⢜⢜⢌⢆⢄⠀⠀⠡⢁⠂⠌⠌⠀⠂⢌⠢⡑⢝⢵⢨⠪⡪⡪⡪⡀ ⠀    By @b3rt1ng
⠀⠀⠀⠀⠀⠀⠀⠀⠑⠕⡕⡕⣕⢕⢜⢌⢆⢎⢆⢪⢢⢪⢢⢣⢣⢣⢣⠣⠣⠡⡡⠀⠂⠌⠈⠀⠀⠀⠠⠑⠌⢌⢪⢣⢣⠡⢣⢣⢣⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(SILVER)}⠀⠀⠀⠀⠀⢀⢐⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(WHITE)}
⠀⠀⠀⠀⠀⠀⠀⠀⠄⢕⢌⢎⢞⡯⣗⣗⣗⡷⣹⣪⣗⢵⢱⢱⢱⢱⢱⢱⠡⡑⡸⠨⠀⠀⠀⠀⠀⠀⠀⠈⠈⡂⠢⠱⣣⢣⢣⠣⡣⣣⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(SILVER)}⠀⠀⠀⢀⢐⢐⢐⠀⠀⡀⠀⠀⠀⠀⠀⠀⠀{color_signal(WHITE)}
⠀⠀⠀⠀⠀⠀⠀⠌⢌⢎⢎⢎⢞⡞⡝⡘⠘⠝⠎⢞⢎⠇⠅⠕⢕⢝⢜⢎⢮⠢⠪⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠌⠌⢌⢪⢳⣕⢕⢕⢕⢧⡂⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(SILVER)}⠀⠀⢀⢐⢔⢐⢐⠐⢄⠑⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(WHITE)}
⠀⠀⠀⠀⠀⠀⠨⠨⡢⡣⡣⡳⢱⠨⠀⠀⠀⠀⠀⠀⠀⠈⠀⠀⠀⠀⠀⠠⠡⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠐⠠⡑⡵⡻⣜⡜⡜⡜⠦⡠⡀⡀⠀⠀⠀⠀⠀⠀{color_signal(SILVER)}⢀⢀⢢⢢⢑⢐⠐⢄⠑⠐⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(WHITE)} 
⠀⠀⠀⠀⠀⠀⠨⠨⠪⠪⠪⡈⠂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠐⠘⢜⢜⢜⢌⠪⠨⠨⡪⡇⡗⡵⣕⢔⠤{color_signal(SILVER)}⢱⢨⢪⠪⠢⢂⠂⠅⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(WHITE)}
⠀⠀⠀⠀⠀⠀⠈⠈⠈⠈⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠠⠡⡑⠅⠅⢅⠑⠌⡂⡂⡑⠠⠡⠁{color_signal(SILVER)}⠁⠁⠂⠈⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀{color_signal(WHITE)}
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠌⠌⠀⠡⠡⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠈⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
"""
    small_art = f"""\
⠀{color_signal(SILVER)}⢠⣀⠀⠈⠑{color_signal(WHITE)}⢶⣦⣤⡴⢶{color_signal(SILVER)}⠶{color_signal(WHITE)}⣶⣶{color_signal(SILVER)}⣤⡀⠀⠀⠀⠀{RST}
⠀⠀{color_signal(SILVER)}⠈⠉⢲⠤⠺{color_signal(WHITE)}⣿{color_signal(PUMPKIN)}⣿⣧{color_signal(WHITE)}⣿{color_signal(CORAL)}⣿{color_signal(WHITE)}⣋{color_signal(SILVER)}⢠{color_signal(PUMPKIN)}⣿{color_signal(WHITE)}⣿{color_signal(SILVER)}⣄⠀⠀⠀{RST}██   {color_signal(PUMPKIN)}██{RST}  {color_signal(SILVER)}████{RST}██  ██ 
⠀⠀⠀{color_signal(SILVER)}⡰⠃⢀⣴{color_signal(WHITE)}⡿{color_signal(SILVER)}⠟⠁⠺{color_signal(WHITE)}⢝⣿⣿{color_signal(CORAL)}⣿{color_signal(PUMPKIN)}⣿⣿{color_signal(WHITE)}⡆⠀⠀{RST}██  {color_signal(PUMPKIN)}█{RST}█  {color_signal(SILVER)}██{RST}    ██ ██ 
⠀⠀{color_signal(SILVER)}⠾⠵⠖⠋⠁⣀⣀⣠{color_signal(WHITE)}⣮⣭⣼⣷⣞⣥{color_signal(PUMPKIN)}⣹{color_signal(WHITE)}⡇⠀⠀{RST}█████   {color_signal(SILVER)}█{RST}█    ██ █{color_signal(PUMPKIN)}█ 
⠀⠀⠀⠀{color_signal(SILVER)}⢀⣤{color_signal(WHITE)}⡺⠿⠿{color_signal(PUMPKIN)}⣿⣿⣿{color_signal(WHITE)}⣶⣇⣨{color_signal(CORAL)}⣿{color_signal(WHITE)}⣿{color_signal(SILVER)}⠁⠀⠀{RST}{color_signal(UMBER)}█{RST}█  ██  ██    ██ {color_signal(PUMPKIN)}██ 
⠀⠀{color_signal(SILVER)}⢠{color_signal(WHITE)}⢶{color_signal(PUMPKIN)}⣿⠿{color_signal(SILVER)}⠃⠀⣀⡁⠀{color_signal(PUMPKIN)}⣿{color_signal(CORAL)}⣿{color_signal(WHITE)}⣼{color_signal(CORAL)}⣿{color_signal(WHITE)}⣿⣏{color_signal(SILVER)}⡑⡄⠀{RST}{color_signal(UMBER)}██{RST}   ██  ██████  {color_signal(PUMPKIN)}██ 
⠀{color_signal(SILVER)}⢰⣁⡐⠰⠆⣰{color_signal(WHITE)}⣶{color_signal(PUMPKIN)}⣿{color_signal(WHITE)}⣿⡿{color_signal(SILVER)}⠛{color_signal(WHITE)}⠻{color_signal(SILVER)}⡋⠀⠉⠉⠁⠀⠀{RST}
⠀⠀{color_signal(SILVER)}⠈{color_signal(WHITE)}⠏{color_signal(SILVER)}⠏⠉⠉⠉⠈⠛⠤⣀⣠{color_signal(WHITE)}⡽⠀⠀⠀⠀⠀⠀{RST}
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀By @b3rt1ng / Version {__version__}{RST}
"""
    if terminal_width < 110 or small:
        print(small_art)
    else:
        print(art)


def print_status_line(text):
    if not sys.stdout.isatty():
        return

    ERASE_LINE = "\033[K"
    terminal_width = shutil.get_terminal_size().columns
    output = str(text)
    if len(output) > terminal_width:
        output = output[:terminal_width - 4] + "..."
    print(f"\r{ERASE_LINE}{output}", end="", flush=True)


def _vlen(s) -> int:
    return len(_ANSI.sub("", str(s)))


def _ansi_tokens(text: str):
    tokens = []
    pos = 0
    for m in _ANSI.finditer(text):
        tokens.extend((False, ch) for ch in text[pos:m.start()])
        tokens.append((True, m.group()))
        pos = m.end()
    tokens.extend((False, ch) for ch in text[pos:])
    return tokens


def _hardbreak_word(word, width):
    chunks, cur, cur_vis = [], "", 0
    for is_ansi, piece in word:
        if is_ansi:
            cur += piece
            continue
        if cur_vis + 1 > width:
            chunks.append(cur)
            cur, cur_vis = "", 0
        cur += piece
        cur_vis += 1
    chunks.append(cur)
    return chunks


def _wrap_ansi(text: str, width: int) -> list[str]:
    text = str(text)
    if width < 1:
        width = 1
    if _vlen(text) <= width:
        return [text]

    words, cur_word = [], []
    for is_ansi, piece in _ansi_tokens(text):
        if not is_ansi and piece == " ":
            if cur_word:
                words.append(cur_word)
                cur_word = []
        else:
            cur_word.append((is_ansi, piece))
    if cur_word:
        words.append(cur_word)

    lines, line, line_vis = [], "", 0
    for word in words:
        wstr = "".join(p for _, p in word)
        wvis = sum(1 for is_ansi, _ in word if not is_ansi)
        if line_vis == 0:
            chunks = _hardbreak_word(word, width)
            lines.extend(chunks[:-1])
            line, line_vis = chunks[-1], _vlen(chunks[-1])
        elif line_vis + 1 + wvis <= width:
            line += " " + wstr
            line_vis += 1 + wvis
        else:
            lines.append(line)
            chunks = _hardbreak_word(word, width)
            lines.extend(chunks[:-1])
            line, line_vis = chunks[-1], _vlen(chunks[-1])
    lines.append(line)
    return lines


def _fit_columns(natural: list[int], budget: int, min_w: int = 3) -> list[int]:
    widths = list(natural)
    n = len(widths)
    if sum(widths) <= budget:
        return widths
    if budget < n * min_w:                     # can't even fit the minimums
        return [min_w] * n

    lo, hi = min_w, max(widths)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if sum(min(w, mid) for w in widths) <= budget:
            lo = mid
        else:
            hi = mid - 1
    widths = [min(w, lo) for w in widths]

    leftover = budget - sum(widths)
    while leftover > 0:
        progressed = False
        for k in range(n):
            if leftover <= 0:
                break
            if widths[k] < natural[k]:
                widths[k] += 1
                leftover -= 1
                progressed = True
        if not progressed:
            break
    return widths

def _make_color_fn(total_rows, total_cols, tl, br):
    denom = max(total_rows + total_cols - 2, 1)
    def _color(row, col):
        ratio = (row + col) / denom
        ratio = 0.0 if ratio < 0 else 1.0 if ratio > 1 else ratio
        r = int(tl[0] + ratio * (br[0] - tl[0]))
        g = int(tl[1] + ratio * (br[1] - tl[1]))
        b = int(tl[2] + ratio * (br[2] - tl[2]))
        return f"\033[38;2;{r};{g};{b}m"
    return _color


def print_report_box(title, data_dict, top_left_color=PUMPKIN, bottom_right_color=CORAL):
    if not data_dict:
        return

    categorized = any(isinstance(v, dict) for v in data_dict.values())

    if categorized:
        all_items = [(k, v) for cat in data_dict.values() for k, v in cat.items()]
    else:
        all_items = list(data_dict.items())

    terminal_width = shutil.get_terminal_size().columns
    max_key_len    = max(_vlen(k) for k, _ in all_items) if all_items else 0

    max_inner_width = max((7 + max_key_len + _vlen(str(v))) for _, v in all_items) if all_items else 0

    header_text = f" {title} "
    inner_width = max(len(header_text) + 4, max_inner_width)
    if inner_width + 2 > terminal_width:
        inner_width = terminal_width - 2

    prefix_len  = max_key_len + 5            # "  " + key + " : "
    value_width = max(1, inner_width - prefix_len)

    def wrap_value(value):
        return _wrap_ansi(str(value), value_width)

    total_cols = inner_width + 2

    # build a render plan up front so we can count physical rows for the gradient
    if categorized:
        plan = []
        for category, items in data_dict.items():
            plan.append(("sep", category, None))
            for k, v in items.items():
                plan.append(("row", k, wrap_value(v)))
    else:
        plan = [("row", k, wrap_value(v)) for k, v in data_dict.items()]

    total_rows = 2 + sum(len(chunks) if kind == "row" else 1 for kind, _, chunks in plan)

    get_diag_color = _make_color_fn(total_rows, total_cols, top_left_color, bottom_right_color)

    white_start = f"\033[38;2;{WHITE[0]};{WHITE[1]};{WHITE[2]}m"

    header_label   = f" {title} "
    header_padding = inner_width - len(header_label)
    left_dashes    = "─" * (header_padding // 2)
    right_dashes   = "─" * (header_padding - header_padding // 2)
    colored_left   = "".join(get_diag_color(0, c) + ch for c, ch in enumerate("╭" + left_dashes))
    colored_right  = "".join(
        get_diag_color(0, 1 + len(left_dashes) + len(header_label) + c) + ch
        for c, ch in enumerate(right_dashes + "╮")
    )
    top_line = colored_left + gradient_text(header_label, PUMPKIN, WHITE) + colored_right
    print("\n" + top_line + RST)

    r_idx = 0

    def print_row(key, chunks):
        nonlocal r_idx
        pad_len = max_key_len - _vlen(key)
        for i, chunk in enumerate(chunks):
            r_idx += 1
            left_char  = get_diag_color(r_idx, 0) + "│" + RST
            right_char = get_diag_color(r_idx, total_cols - 1) + "│" + RST
            if i == 0:
                line_content = f"  {key}{' ' * pad_len} : {chunk}"
            else:
                line_content = f"{' ' * prefix_len}{chunk}"
            right_pad = " " * max(0, inner_width - _vlen(line_content))
            print(f"{left_char}{white_start}{line_content}{right_pad}{RST}{right_char}")

    def print_separator(label: str):
        nonlocal r_idx
        r_idx += 1
        left_char  = get_diag_color(r_idx, 0) + "├" + RST
        right_char = get_diag_color(r_idx, total_cols - 1) + "┤" + RST
        label_text    = f" {label} "
        padding       = inner_width - len(label_text)
        left_dashes   = "─" * (padding // 2)
        right_dashes  = "─" * (padding - padding // 2)
        colored_left  = "".join(get_diag_color(r_idx, c) + ch for c, ch in enumerate(left_dashes))
        colored_right = "".join(get_diag_color(r_idx, len(left_dashes) + len(label_text) + c) + ch for c, ch in enumerate(right_dashes))
        print(f"{left_char}{colored_left}{gradient_text(label_text, PUMPKIN, WHITE)}{colored_right}{RST}{right_char}")

    for kind, key, chunks in plan:
        if kind == "sep":
            print_separator(key)
        else:
            print_row(key, chunks)

    r_idx += 1
    bottom_border = "╰" + "─" * inner_width + "╯"
    bottom_line   = "".join(get_diag_color(r_idx, c) + char for c, char in enumerate(bottom_border))
    print(bottom_line + RST)

def print_table(
    title: str,
    headers: list,
    rows: list,
    top_left_color=PUMPKIN,
    bottom_right_color=CORAL,
) -> None:
    if not headers or not rows:
        return

    terminal_width = shutil.get_terminal_size().columns
    n_cols = len(headers)

    col_widths = [_vlen(str(h)) for h in headers]
    for row in rows:
        for i in range(min(n_cols, len(row))):
            col_widths[i] = max(col_widths[i], _vlen(str(row[i])))

    # inner_width = sum(w + 2 padding) + (n_cols - 1 separators) = sum(w) + 3*n_cols - 1
    max_inner = terminal_width - 2
    col_widths = _fit_columns(col_widths, max_inner - (3 * n_cols - 1))
    inner_width = sum(w + 2 for w in col_widths) + (n_cols - 1)

    # pre-wrap every cell so a row can span several physical lines
    def wrap_cells(cells):
        return [
            _wrap_ansi(str(cells[i]) if i < len(cells) else "", col_widths[i])
            for i in range(n_cols)
        ]

    header_wrapped = wrap_cells(headers)
    rows_wrapped   = [wrap_cells(row) for row in rows]

    def row_height(wrapped):
        return max(len(cell) for cell in wrapped)

    total_cols = inner_width + 2
    total_rows = 2 + row_height(header_wrapped) + 1 + sum(row_height(w) for w in rows_wrapped)

    get_color = _make_color_fn(total_rows, total_cols, top_left_color, bottom_right_color)

    r_idx = 0

    header_label   = f" {title} "
    header_padding = inner_width - len(header_label)
    left_dashes    = "─" * (header_padding // 2)
    right_dashes   = "─" * (header_padding - header_padding // 2)
    colored_left   = "".join(get_color(0, c) + ch for c, ch in enumerate("╭" + left_dashes))
    colored_right  = "".join(
        get_color(0, 1 + len(left_dashes) + len(header_label) + c) + ch
        for c, ch in enumerate(right_dashes + "╮")
    )
    print("\n" + colored_left + gradient_text(header_label, top_left_color, WHITE) + colored_right + RST)

    white_start = f"\033[38;2;{WHITE[0]};{WHITE[1]};{WHITE[2]}m"

    def render_row(wrapped, bold=False):
        nonlocal r_idx
        for line_idx in range(row_height(wrapped)):
            r_idx += 1
            left    = get_color(r_idx, 0) + "│" + RST
            right   = get_color(r_idx, total_cols - 1) + "│" + RST
            content = ""
            col_pos = 1
            for i in range(n_cols):
                chunk = wrapped[i][line_idx] if line_idx < len(wrapped[i]) else ""
                pad   = col_widths[i] - _vlen(chunk)
                if bold:
                    content += f" {BOLD}{white_start}{chunk}{RST}" + " " * (pad + 1)
                else:
                    content += f" {white_start}{chunk}{RST}" + " " * (pad + 1)
                col_pos += col_widths[i] + 2
                if i < n_cols - 1:
                    content += get_color(r_idx, col_pos) + "│" + RST
                    col_pos += 1
            print(f"{left}{content}{right}")

    def render_hsep(left_ch="├", right_ch="┤", mid_ch="┼"):
        nonlocal r_idx
        r_idx += 1
        line    = get_color(r_idx, 0) + left_ch
        col_pos = 1
        for i, w in enumerate(col_widths):
            for j in range(w + 2):
                line += get_color(r_idx, col_pos + j) + "─"
            col_pos += w + 2
            if i < n_cols - 1:
                line += get_color(r_idx, col_pos) + mid_ch
                col_pos += 1
        line += get_color(r_idx, col_pos) + right_ch
        print(line + RST)

    render_row(header_wrapped, bold=True)
    render_hsep()

    for wrapped in rows_wrapped:
        render_row(wrapped)

    r_idx += 1
    line    = get_color(r_idx, 0) + "╰"
    col_pos = 1
    for i, w in enumerate(col_widths):
        for j in range(w + 2):
            line += get_color(r_idx, col_pos + j) + "─"
        col_pos += w + 2
        if i < n_cols - 1:
            line += get_color(r_idx, col_pos) + "┴"
            col_pos += 1
    line += get_color(r_idx, col_pos) + "╯"
    print(line + RST)

def notify(msg_type, text):
    prefixes = {
        'new':     (PUMPKIN,  "▶", f"{BOLD}{color_signal(WHITE)}New session"),
        'info':    (WHITE,  "?", "Info"),
        'error':   (CORAL,  "✖", "Error"),
        'warning': (CORAL,  "!", "Warning"),
        'status':  (SILVER, "⚡", "Status"),
        'success': (PUMPKIN,  "✔", "Success"),
    }
    
    if msg_type not in prefixes:
        print(f"  {text}")
        return

    color, icon, label = prefixes[msg_type]
    prefix = f"  {colored_text(icon, color)}  "
    
    if msg_type == 'new':
        print(f"{prefix}{label} {text}")
    else:
        print(f"{prefix}{text}")

class Spinner:
    _FRAMES = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]

    def __init__(self, message: str = "Loading..."):
        self.message   = message
        self._stop_ev  = threading.Event()
        self._thread   = None

    def start(self):
        self._stop_ev.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop_ev.set()
        if self._thread:
            self._thread.join()
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def _spin(self):
        i = 0
        while not self._stop_ev.is_set():
            frame = colored_text(self._FRAMES[i % len(self._FRAMES)], PUMPKIN)
            sys.stdout.write(f"\r  {frame}  {colored_text(self.message, SILVER)}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()
        
class ProgressBar:
    def __init__(self, total: int, width: int = 20, prefix: str = ""):
        self.total = total
        self.width = width
        self.prefix = prefix
        self._current = 0

    def update(self, current: int):
        self._current = current
        pct = int(current / self.total * 100) if self.total else 0
        bar = ("─" * (pct // (100 // self.width))).ljust(self.width)
        suffix = f"{current}/{self.total} bytes" if self.total else f"{current} bytes"
        print_status_line(
            f"  [{colored_text(f'{bar}', PUMPKIN)}] "
            f"{colored_text(f'{pct:3d}%', WHITE)}  "
            f"{colored_text(suffix, SILVER)}"
            + (f"  {self.prefix}" if self.prefix else "")
        )

    def done(self):
        self.update(self.total if self.total else self._current)
        print()
        
def breaker_with_text(test: str = ""):
    cols = shutil.get_terminal_size().columns

    if not test:
        print(gradient_text("─" * cols, PUMPKIN, SILVER))
        return

    text = f" {test} "
    vlen = len(_ANSI.sub("", text))

    if vlen >= cols:
        print(colored_text(_ANSI.sub("", text)[:cols], WHITE) + RST)
        return

    left_len = (cols - vlen) // 2
    right_len = cols - vlen - left_len

    print(
        gradient_text("─" * left_len, PUMPKIN, SILVER)
        + colored_text(text, WHITE)
        + gradient_text("─" * right_len, SILVER, PUMPKIN)
        + RST
    )
    
def yesno(question: str, prechosen: bool = True) -> bool:
    choice_hint = "[Y/n]" if prechosen else "[y/N]"

    while True:
        answer = input(f"  {color_signal(PUMPKIN)}?  {color_signal(WHITE)}{question} {color_signal(SILVER)}{choice_hint}{color_signal(WHITE)} ").strip().lower()

        if answer == "":
            return prechosen
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False


def platform_badge(platform) -> str:
    _NAMES = {
        "linux":       "Linux",
        "windows_cmd": "cmd",
        "windows_ps":  "PowerShell",
        "any":         "any",
    }
    _COLORS = {
        "linux":       alert,
        "windows_cmd": cyan,
        "windows_ps":  cyan,
        "any":         muted,
    }

    def _os_tag(p: str) -> str:
        return _COLORS.get(p, muted)(_NAMES.get(p, p))

    ob, cb = muted("["), muted("]")
    if isinstance(platform, list):
        inner = muted(", ").join(_os_tag(p) for p in platform)
        return f"{ob}{inner}{cb}"
    return f"{ob}{_os_tag(platform)}{cb}"


def print_payloads(iface: str | None, port: int) -> None:
    from koi.utils.payloads import PayloadGenerator
    gen = PayloadGenerator(port=port)

    def _show(label: str, payloads: dict) -> None:
        print()
        breaker_with_text(label)
        for name, payload in payloads.items():
            print(f"  {bold(accent(name))}: {muted(payload)}")
            print()
        breaker_with_text()

    if iface is None:
        all_payloads = gen.for_all()
        if not all_payloads:
            notify('error', "No network interfaces found.")
            return
        interfaces = gen.get_interfaces()
        for name, payloads in all_payloads.items():
            _show(f"{name}  {interfaces[name]}", payloads)
    else:
        payloads = gen.for_interface(iface)
        if payloads is None:
            notify('error', f"Interface {accent(iface)} not found.")
            notify('status', muted("Available: " + ", ".join(gen.get_interfaces().keys())))
            return
        _show(iface, payloads)
