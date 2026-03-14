import shutil
import sys
import threading
import time
from random import choice

PUMPKIN     = (255, 116,   0)
WHITE       = (255, 255, 255)
SILVER      = (169, 169, 169)
CORAL       = (235, 111,  92)
UMBER       = (123,  62,   0)
RST = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"

def _b(t):  return f"{BOLD}{t}{RST}"
def _d(t):  return f"{DIM}{t}{RST}"
def _r(t):  return colored_text(t, CORAL)
def _g(t):  return colored_text(t, UMBER)
def _c(t):  return colored_text(t, WHITE)
def _p(t):  return colored_text(t, PUMPKIN)
def _y(t):  return colored_text(t, CORAL)
def _o(t):  return colored_text(t, PUMPKIN)
def _gr(t): return colored_text(t, SILVER)

MOTD = ["The serene shell handler", 
        "This has to be legal, right?",
        "La root est longue mais la voie est libre",
        "Koi: Flowing through the network.",
        "Don't tell my mom I'm doing this.",
        "流れに逆らう鯉のように",
        "¯＼(º_o)/¯"
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


def display_art():
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
    small_art = r"""
      :::    ::: :::::::: ::::::::::: 
     :+:   :+: :+:    :+:    :+:      
    +:+  +:+  +:+    +:+    +:+       
   +#++:++   +#+    +:+    +#+        
  +#+  +#+  +#+    +#+    +#+         
 #+#   #+# #+#    #+#    #+#          
###    ### ######## ###########       
        By @b3rt1ng                                           
"""
    if terminal_width < 139:
        print(gradient_text(small_art, WHITE, PUMPKIN))
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


def format_keywords(keywords_dict):
    if not keywords_dict:
        return ""

    parts = []
    for keyword, count in keywords_dict.items():
        key_colored   = colored_text(keyword, PUMPKIN)
        count_colored = colored_text(count,   CORAL)
        parts.append(f"{key_colored}: {count_colored}")

    return " " + colored_text(f"\033[0m[{', '.join(parts)}]", UMBER)


def print_report_box(title, data_dict, top_left_color=PUMPKIN, bottom_right_color=CORAL):
    if not data_dict:
        return

    import re
    _ansi = re.compile(r"\033\[[^m]*m")
    def _len(s): return len(_ansi.sub("", str(s)))

    terminal_width = shutil.get_terminal_size().columns
    max_key_len = max(_len(k) for k in data_dict.keys()) if data_dict else 0
    
    max_inner_width = 0
    if data_dict:
        max_inner_width = max(7 + max_key_len + _len(v) for v in data_dict.values())
        
    header_text = f" {title} "
    inner_width = max(len(header_text) + 4, max_inner_width)
    
    if inner_width + 2 > terminal_width:
        inner_width = terminal_width - 2

    total_rows = len(data_dict) + 2
    total_cols = inner_width + 2

    def get_diag_color(row, col):
        ratio = (row + col) / max((total_rows + total_cols - 2), 1)
        r = int(top_left_color[0] + ratio * (bottom_right_color[0] - top_left_color[0]))
        g = int(top_left_color[1] + ratio * (bottom_right_color[1] - top_left_color[1]))
        b = int(top_left_color[2] + ratio * (bottom_right_color[2] - top_left_color[2]))
        return f"\033[38;2;{r};{g};{b}m"

    white_start = f"\033[38;2;{WHITE[0]};{WHITE[1]};{WHITE[2]}m"

    top_border = "╭" + header_text.center(inner_width, "─") + "╮"
    top_line = "".join(get_diag_color(0, c) + char for c, char in enumerate(top_border))
    print("\n" + top_line + RST)

    for r_idx, (key, value) in enumerate(sorted(data_dict.items()), start=1):
        left_char = get_diag_color(r_idx, 0) + "│" + RST
        
        pad_len = max_key_len - _len(key)
        line_content = f"  {key}{' ' * pad_len} : {value}"
        right_pad = " " * max(0, inner_width - _len(line_content))
        
        right_char = get_diag_color(r_idx, total_cols - 1) + "│" + RST
        
        print(f"{left_char}{white_start}{line_content}{right_pad}{RST}{right_char}")

    bottom_border = "╰" + "─" * inner_width + "╯"
    bottom_line = "".join(get_diag_color(total_rows - 1, c) + char for c, char in enumerate(bottom_border))
    print(bottom_line + RST)

def notify(msg_type, text):
    prefixes = {
        'new':     (PUMPKIN,  "▶", f"{BOLD}{color_signal(WHITE)}New session"),
        'info':    (WHITE,  "ℹ", "Info"),
        'error':   (CORAL,  "✖", "Error"),
        'warning': (CORAL,  "!", "Warning"),
        'status':  (SILVER, "⚡", "Status")
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
        
def breaker():
    print(gradient_text(whole_line("─"), PUMPKIN, SILVER))

if __name__ == "__main__":
    display_art()
    print_report_box("Example Report", {"Keyword1": 10, "Keyword2": 5, "Keyword3": 15})
    print_status_line("Processing...")