"""Test-wide setup: the suite asserts English UI text.

The settings app translates from the desktop locale when config.json names no
language, and complete catalogs ship for 18 languages, so a developer on a
non-English desktop would otherwise see translated strings in assertions.
"""
import os

os.environ["LANGUAGE"] = "en"
