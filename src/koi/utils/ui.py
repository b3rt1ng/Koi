import re
import shutil
import sys
import threading
import time
from random import choice

_ANSI = re.compile(r"\033\[[^m]*m")

PUMPKIN     = (248, 101, 70)
WHITE       = (255, 255, 255)
SILVER      = (169, 169, 169)
CORAL       = (235, 111,  92)
UMBER       = (123,  62,   0)
BLUE        = (118, 241, 245)
RST = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"

def _b(t):  return f"{BOLD}{t}{RST}"
def _d(t):  return f"{DIM}{t}{RST}"
def _r(t):  return colored_text(t, CORAL)
_y = _r
def _c(t):  return colored_text(t, WHITE)
def _p(t):  return colored_text(t, PUMPKIN)
def _gr(t): return colored_text(t, SILVER)
def _bl(t): return colored_text(t, BLUE)

MOTD = ["The serene shell handler", 
        "This has to be legal, right?",
        "La root est longue mais la voie est libre ;)",
        "Don't tell my mom I'm doing this.",
        "流れに逆らう鯉のように",
        "¯＼(º_o)/¯",
        "Do not download and run random modules...",
        "AD is not that scary, I promise!"
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
⠀⢹⡾⣝⠆⠅⡂⠌⢎⢎⢎⢪⢈⠪⠀⠀⠀⠀⠀⠀⠀⠀⠐⠐⠈⠆⢇⢕⠐⢌⠢⠑⠌⢌⢆⢂⠊⡎⡎⡮⣺{color_signal(PUMPKIN)}⣦⢀⠀⠀⠀{color_signal(WHITE)}⠀⠀⠀
⠀{color_signal(UMBER)}⠂⢿⡸⣣{color_signal(WHITE)}⡁⡢⠡⠡⡑⠌⢌⢪⢪⠠⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠠⠑⠕⢄⢅⢅⢑⢐⠐⠄⢕⢜⢜{color_signal(PUMPKIN)}⢼⢿⣾⣳⣔⢀⠀⠀⠀{color_signal(WHITE)}⠀⠀{choice(MOTD)}
⠀{color_signal(UMBER)}⠈⠸⡽⣿⣽⣮{color_signal(WHITE)}⡪⡢⡨⡨⡢⡣⡣⠣⠣⡪⡐⠄⢄⠀⠀⠀⠀⠀⠀⠀⠀⠁⠂⡑⡑⡐⠄⠅⢅⢑⠱⡱⡣{color_signal(PUMPKIN)}⡫⣺⢻⡚⣆⠀⠀⠀⠀⠀⠀⠀{color_signal(WHITE)}⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀{color_signal(UMBER)}⠹⡽⣾⣷⡻{color_signal(WHITE)}⡸⡸⡸⡸⡨⠨⡈⡂⡂⠪⡘⢜⢜⢔⢐⠐⠌⠌⠀⠀⠀⠀⢂⠢⠨⠨⡈⡂⠢⡑⢜⢯⣎⢎{color_signal(PUMPKIN)}⢎⢎⢎⢎⠄⠀⠀⠀{color_signal(WHITE)}⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
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
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀By @b3rt1ng⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀{RST}
"""
    if terminal_width < 139 or small:
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


def print_report_box(title, data_dict, top_left_color=PUMPKIN, bottom_right_color=CORAL):
    if not data_dict:
        return

    def _len(s): return len(_ANSI.sub("", str(s)))

    categorized = any(isinstance(v, dict) for v in data_dict.values())

    if categorized:
        all_items = [(k, v) for cat in data_dict.values() for k, v in cat.items()]
    else:
        all_items = list(data_dict.items())

    terminal_width = shutil.get_terminal_size().columns
    max_key_len    = max(_len(k) for k, _ in all_items) if all_items else 0

    max_inner_width = max((7 + max_key_len + _len(str(v))) for _, v in all_items) if all_items else 0

    header_text = f" {title} "
    inner_width = max(len(header_text) + 4, max_inner_width)
    if inner_width + 2 > terminal_width:
        inner_width = terminal_width - 2

    total_cols = inner_width + 2

    if categorized:
        total_rows = sum(len(items) for items in data_dict.values()) + len(data_dict) + 2
    else:
        total_rows = len(all_items) + 2

    def get_diag_color(row, col):
        ratio = (row + col) / max((total_rows + total_cols - 2), 1)
        r = int(top_left_color[0] + ratio * (bottom_right_color[0] - top_left_color[0]))
        g = int(top_left_color[1] + ratio * (bottom_right_color[1] - top_left_color[1]))
        b = int(top_left_color[2] + ratio * (bottom_right_color[2] - top_left_color[2]))
        return f"\033[38;2;{r};{g};{b}m"

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

    def print_row(key, value):
        nonlocal r_idx
        r_idx += 1
        left_char  = get_diag_color(r_idx, 0) + "│" + RST
        right_char = get_diag_color(r_idx, total_cols - 1) + "│" + RST
        pad_len      = max_key_len - _len(key)
        line_content = f"  {key}{' ' * pad_len} : {value}"
        right_pad    = " " * max(0, inner_width - _len(line_content))
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

    if categorized:
        categories = list(data_dict.items())
        for cat_idx, (category, items) in enumerate(categories):
            print_separator(category)
            for key, value in items.items():
                print_row(key, value)
    else:
        for key, value in data_dict.items():
            print_row(key, value)

    r_idx += 1
    bottom_border = "╰" + "─" * inner_width + "╯"
    bottom_line   = "".join(get_diag_color(r_idx, c) + char for c, char in enumerate(bottom_border))
    print(bottom_line + RST)

def notify(msg_type, text):
    prefixes = {
        'new':     (PUMPKIN,  "▶", f"{BOLD}{color_signal(WHITE)}New session"),
        'info':    (WHITE,  "ℹ", "Info"),
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

    def __init__(self, message: str = "Loading…"):
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


def print_payloads(iface: str | None, port: int) -> None:
    from koi.utils.payloads import PayloadGenerator
    gen = PayloadGenerator(port=port)

    def _show(label: str, payloads: dict) -> None:
        print()
        breaker_with_text(label)
        for name, payload in payloads.items():
            print(f"  {_b(_p(name))}: {_gr(payload)}")
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
            notify('error', f"Interface {_p(iface)} not found.")
            notify('status', _gr("Available: " + ", ".join(gen.get_interfaces().keys())))
            return
        _show(iface, payloads)
