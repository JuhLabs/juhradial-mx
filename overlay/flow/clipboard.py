"""Clipboard helpers for Flow (supports Wayland and X11)"""

import logging
import subprocess
import time

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
        logger.debug("wl-paste not found, trying xclip")
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
        logger.debug("xclip not found")
    except subprocess.TimeoutExpired:
        logger.warning("xclip timed out")

    return ""


def set_clipboard(content: str, retries: int = 3) -> bool:
    """Set clipboard contents (supports Wayland and X11).

    Retries on failure since wl-copy can race with Wayland seat changes
    during Flow device switches.
    """
    for attempt in range(retries):
        if _try_set_clipboard(content):
            return True
        if attempt < retries - 1:
            time.sleep(0.3)
            logger.debug("Clipboard set retry %d/%d", attempt + 2, retries)
    logger.warning("Clipboard set failed after %d attempts", retries)
    return False


def _try_set_clipboard(content: str) -> bool:
    """Single attempt to set clipboard."""
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
        logger.debug("wl-copy not found, trying xclip")
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
        logger.debug("xclip not found")
    except subprocess.TimeoutExpired:
        logger.warning("xclip timed out")

    return False
