#!/bin/sh
# Append the clipboard text to $HOME/<note path> (default Notes/inbox.md).
note="$HOME/${1:-Notes/inbox.md}"
mkdir -p "$(dirname "$note")"
if command -v wl-paste >/dev/null 2>&1 && [ -n "$WAYLAND_DISPLAY" ]; then
    text=$(wl-paste --no-newline 2>/dev/null)
elif command -v xclip >/dev/null 2>&1; then
    text=$(xclip -selection clipboard -o 2>/dev/null)
else
    text=""
fi
[ -n "$text" ] || exit 0
printf '\n## %s\n\n%s\n' "$(date '+%Y-%m-%d %H:%M')" "$text" >> "$note"
command -v notify-send >/dev/null 2>&1 && notify-send -a "JuhRadial MX" "Saved to $(basename "$note")"
exit 0
