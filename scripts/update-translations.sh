#!/bin/bash
#
# JuhRadial MX - Translation Management Script
#
# Usage: ./scripts/update-translations.sh
#
# This script:
# 1. Extracts translatable strings from Python sources into juhradial.pot
# 2. Updates existing .po files with new/changed strings
# 3. Compiles .po files to .mo binary format
#
# SPDX-License-Identifier: GPL-3.0

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOCALE_DIR="$PROJECT_DIR/overlay/locales"
POT_FILE="$LOCALE_DIR/juhradial.pot"

echo "Extracting translatable strings..."
xgettext \
    --language=Python \
    --from-code=UTF-8 \
    --keyword=_ \
    --output="$POT_FILE" \
    --package-name="JuhRadial MX" \
    --package-version="1.0" \
    --msgid-bugs-address="https://github.com/JuhLabs/juhradial-mx/issues" \
    "$PROJECT_DIR"/overlay/*.py

STRING_COUNT=$(grep -c '^msgid ' "$POT_FILE")
echo "Extracted $STRING_COUNT translatable strings"

echo ""
echo "Updating .po files and compiling .mo files..."
for lang_dir in "$LOCALE_DIR"/*/; do
    lang=$(basename "$lang_dir")
    po_file="$lang_dir/LC_MESSAGES/juhradial.po"
    mo_file="$lang_dir/LC_MESSAGES/juhradial.mo"

    if [ -f "$po_file" ]; then
        # Update existing .po with new strings from .pot
        msgmerge --update --backup=none --no-fuzzy-matching "$po_file" "$POT_FILE"
        echo "  Updated: $lang"
    else
        # Create new .po file
        msginit --no-translator --locale="$lang" --input="$POT_FILE" --output="$po_file"
        echo "  Created: $lang"
    fi

    # Compile to .mo
    msgfmt --output="$mo_file" "$po_file"
done

echo ""
echo "Done! Translation files updated."
echo "To add translations, edit the .po files in overlay/locales/<lang>/LC_MESSAGES/"
