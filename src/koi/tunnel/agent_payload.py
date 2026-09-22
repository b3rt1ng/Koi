from __future__ import annotations

import pathlib
import shutil
import tempfile
import zipapp

_ENGINE = pathlib.Path(__file__).parent / "engine"
_DEFAULT_NAME = "koi_tunnel_agent.pyz"
_SHIM = (
    "import sys\n"
    "from tunel.__main__ import main\n"
    "sys.exit(main(['agent', *sys.argv[1:]]))\n"
)


def build_agent_pyz(dest: pathlib.Path | None = None) -> pathlib.Path:
    if dest is None:
        dest = pathlib.Path(tempfile.gettempdir()) / _DEFAULT_NAME
    dest = pathlib.Path(dest)
    with tempfile.TemporaryDirectory() as tmp:
        staging = pathlib.Path(tmp)
        shutil.copytree(
            _ENGINE, staging / "tunel",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (staging / "__main__.py").write_text(_SHIM)
        zipapp.create_archive(
            staging, target=str(dest), interpreter="/usr/bin/env python3",
        )
    return dest
