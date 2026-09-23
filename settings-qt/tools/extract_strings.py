#!/usr/bin/env python3
"""Write the gettext template for the Qt settings app.

Collects qsTr("...") from settings-qt/qml and _("...") from settings-qt/bridge
into overlay/locales/juhradial-settings.pot (the directory every install layout
already ships). Translators copy it to <lang>/LC_MESSAGES/juhradial-settings.po;
compile with msgfmt.

    python3 settings-qt/tools/extract_strings.py [--out PATH]
"""
import argparse
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parents[1]
REPO = HERE.parent
QSTR = re.compile(r'qsTr\(\s*"((?:[^"\\]|\\.)*)"')
PYSTR = re.compile(r'\b_\(\s*"((?:[^"\\]|\\.)*)"')


def collect():
    found = {}
    for pattern, root, glob in ((QSTR, HERE / "qml", "*.qml"), (PYSTR, HERE / "bridge", "*.py")):
        for f in sorted(root.rglob(glob)):
            rel = f.relative_to(REPO).as_posix()
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                for msg in pattern.findall(line):
                    found.setdefault(msg, []).append(f"{rel}:{n}")
    return found


def render(found):
    out = ['msgid ""', 'msgstr ""', '"Content-Type: text/plain; charset=UTF-8\\n"', ""]
    for msg in sorted(found):
        out.append("#: " + " ".join(found[msg]))
        out.append(f'msgid "{msg}"')
        out.append('msgstr ""')
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(REPO / "overlay" / "locales" / "juhradial-settings.pot"))
    args = ap.parse_args()
    found = collect()
    pathlib.Path(args.out).write_text(render(found), encoding="utf-8")
    print(f"{len(found)} strings -> {args.out}")


if __name__ == "__main__":
    main()
