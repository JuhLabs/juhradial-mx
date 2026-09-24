#!/usr/bin/env python3
"""Write the gettext template for the Qt settings app.

Collects qsTr("...") from settings-qt/qml, _("...") from settings-qt/bridge and
the label cells of the bridge's string tables (TABLES) into
overlay/locales/juhradial-settings.pot (the directory every install layout
already ships). Translators copy it to <lang>/LC_MESSAGES/juhradial-settings.po;
compile with msgfmt.

    python3 settings-qt/tools/extract_strings.py [--out PATH]
"""
import argparse
import ast
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parents[1]
REPO = HERE.parent
QSTR = re.compile(r'qsTr\(\s*"((?:[^"\\]|\\.)*)"')
PYSTR = re.compile(r'\b_\(\s*"((?:[^"\\]|\\.)*)"')
# Module-level tables whose rows reach the UI through _(variable): the listed
# tuple positions are user-facing text; None means every dict value.
TABLES = {
    "bridge/backend.py": {
        "BUTTON_GROUPS": (1,), "BUTTON_ACTIONS": (1,), "MACRO_TEMPLATES": (1, 2),
        "RING_PALETTES": (1,), "HAPTIC_PATTERNS": (1, 2), "HAPTIC_EVENTS": (1, 2),
        "HAPTIC_LEVELS": (1,), "PANEL_FORCES": (1,), "SLICE_TICK_RATES": (1,),
        "TEST_REASONS": None, "THUMBWHEEL_MODES": (1,), "TAB_LABELS": None,
        "SEARCH_INDEX": (1, 2),
    },
}


def collect():
    found = {}
    for pattern, root, glob in ((QSTR, HERE / "qml", "*.qml"), (PYSTR, HERE / "bridge", "*.py")):
        for f in sorted(root.rglob(glob)):
            rel = f.relative_to(REPO).as_posix()
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                for msg in pattern.findall(line):
                    found.setdefault(msg, []).append(f"{rel}:{n}")
    collect_tables(found)
    return found


def _escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def collect_tables(found):
    for rel, tables in TABLES.items():
        path = HERE / rel
        seen = set()
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in tables):
                continue
            name = node.targets[0].id
            seen.add(name)
            fields = tables[name]
            if fields is None:
                cells = node.value.values
            else:
                cells = [row.elts[i] for row in node.value.elts for i in fields]
            for cell in cells:
                if not cell.value:
                    continue
                found.setdefault(_escape(cell.value), []).append(
                    f"{path.relative_to(REPO).as_posix()}:{cell.lineno}")
        missing = set(tables) - seen
        if missing:
            raise SystemExit(f"{rel}: string tables not found: {sorted(missing)}")


def render(found):
    out = ['msgid ""', 'msgstr ""', '"Content-Type: text/plain; charset=UTF-8\\n"', ""]
    for msg in sorted(found):
        out.append("#: " + " ".join(found[msg]))
        if "(s)" in msg:
            # qsTr("%n step(s)", "", n) is looked up as a gettext plural
            out.append(f'msgid "{msg.replace("(s)", "")}"')
            out.append(f'msgid_plural "{msg.replace("(s)", "s")}"')
            out += ['msgstr[0] ""', 'msgstr[1] ""']
        else:
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
