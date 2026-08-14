#!/usr/bin/env python3
"""Configurable quick-link submenu (custom URLs replacing the AI defaults).

A submenu-type slice may carry a ``submenu`` list of {label, url} dicts in
config.json. ``submenu_from_config`` turns that into overlay action tuples,
inferring the bundled brand icons by domain and falling back to the painter's
generic browser glyph for everything else. Invalid or empty input returns
None so the caller keeps the default AI links.

Run: python3 -m pytest tests/test_quick_links.py -q
"""

import sys

sys.path.insert(0, "overlay")

from overlay_actions import AI_SUBMENU, submenu_from_config


def test_custom_links_map_to_url_actions():
    links = [
        {"label": "Docs", "url": "https://docs.example.com"},
        {"label": "Tracker", "url": "http://tracker.local"},
    ]
    assert submenu_from_config(links) == [
        ("Docs", "url", "https://docs.example.com", "browser"),
        ("Tracker", "url", "http://tracker.local", "browser"),
    ]


def test_known_domains_keep_brand_icons():
    links = [
        {"label": "Claude", "url": "https://claude.ai"},
        {"label": "GPT", "url": "https://chat.openai.com"},
        {"label": "Gemini", "url": "https://gemini.google.com"},
        {"label": "Pplx", "url": "https://perplexity.ai"},
    ]
    icons = [entry[3] for entry in submenu_from_config(links)]
    assert icons == ["claude", "chatgpt", "gemini", "perplexity"]


def test_invalid_entries_are_skipped():
    links = [
        {"label": "", "url": "https://nolabel.example"},
        {"label": "NoUrl", "url": ""},
        {"label": "BadScheme", "url": "ftp://files.example"},
        "not-a-dict",
        {"label": "Good", "url": "https://good.example"},
    ]
    assert submenu_from_config(links) == [
        ("Good", "url", "https://good.example", "browser")
    ]


def test_capped_at_four_entries():
    links = [
        {"label": f"L{i}", "url": f"https://site{i}.example"} for i in range(6)
    ]
    assert len(submenu_from_config(links)) == 4


def test_empty_or_invalid_input_falls_back():
    assert submenu_from_config([]) is None
    assert submenu_from_config(None) is None
    assert submenu_from_config("https://not-a-list.example") is None
    assert submenu_from_config([{"label": "x", "url": "nope"}]) is None


def test_defaults_unchanged():
    # The fallback the overlay uses when no custom links are configured.
    assert AI_SUBMENU[0] == ("Claude", "url", "https://claude.ai", "claude")
    assert len(AI_SUBMENU) == 4
