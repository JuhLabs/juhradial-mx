"""Clipboard helpers for Flow (supports Wayland and X11)"""

import logging
import subprocess

logger = logging.getLogger("juhradial.flow.clipboard")


def get_clipboard() -> str:
    """Get clipboard contents (supports Wayland and X11)"""
    try:
        result = subprocess.run(
            ["wl-paste", "--no-newline"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return result.stdout
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        logger.warning("wl-paste timed out")

    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return result.stdout
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        logger.warning("xclip timed out")

    return ""


def set_clipboard(content: str) -> bool:
    """Set clipboard contents (supports Wayland and X11)"""
    try:
        result = subprocess.run(
            ["wl-copy"],
            input=content,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        logger.warning("wl-copy timed out")

    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=content,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        logger.warning("xclip timed out")

    return False
