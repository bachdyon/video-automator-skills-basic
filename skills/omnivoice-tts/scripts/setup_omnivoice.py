#!/usr/bin/env python3
"""Create an isolated runtime for the k2-fsa OmniVoice skill."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV = REPO_ROOT / ".cache" / "omnivoice-tts" / "venv"
REQUIREMENTS = Path(__file__).with_name("requirements.txt")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-dir", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--recreate", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env_dir = args.env_dir.expanduser().resolve()
    if sys.version_info[:2] not in {(3, 11), (3, 12)}:
        print(
            "Run this installer with Python 3.11 or 3.12 "
            "(for example: python3.11 setup_omnivoice.py).",
            file=sys.stderr,
        )
        return 2

    if args.recreate and env_dir.exists():
        print(
            f"Refusing to delete existing environment automatically: {env_dir}\n"
            "Move it aside manually, then rerun without --recreate.",
            file=sys.stderr,
        )
        return 2

    env_dir.parent.mkdir(parents=True, exist_ok=True)
    python_bin = env_dir / "bin" / "python"
    if os.name == "nt":
        python_bin = env_dir / "Scripts" / "python.exe"

    if not python_bin.exists():
        subprocess.run(
            [args.python, "-m", "venv", str(env_dir)],
            check=True,
        )

    env = os.environ.copy()
    env["PIP_CACHE_DIR"] = str(REPO_ROOT / ".cache" / "pip")
    subprocess.run(
        [
            str(python_bin),
            "-m",
            "pip",
            "install",
            "--progress-bar",
            "off",
            "-r",
            str(REQUIREMENTS),
        ],
        check=True,
        env=env,
    )
    subprocess.run(
        [
            str(python_bin),
            "-c",
            (
                "import omnivoice, torch, torchaudio; "
                "assert torch.__version__.split('+')[0] == "
                "torchaudio.__version__.split('+')[0], "
                "(torch.__version__, torchaudio.__version__); "
                "print('OmniVoice import: OK'); "
                "print('Torch:', torch.__version__); "
                "print('Torchaudio:', torchaudio.__version__)"
            ),
        ],
        check=True,
        env=env,
    )
    print(f"Installed OmniVoice runtime at {env_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
