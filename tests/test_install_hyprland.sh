#!/usr/bin/env bash
# install.sh configure_hyprland (#179): the overlay rules go into the config
# Hyprland actually loads, in that version's syntax: Lua for hyprland.lua
# (0.55+), rule blocks for hyprland.conf on 0.53+, windowrulev2 before 0.53.
# Rules already in a file of the active type are left alone, and when the
# rules cannot be added the installer prints a manual step, not a success.
# With Hyprland installed, its own parser checks the generated configs.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'chmod -R u+w "$tmp"; rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# The function under test, without running the installer around it.
eval "$(sed -n '/^configure_hyprland() {$/,/^}$/p' "$repo/install.sh")"
log_info() { :; }
log_dim() { echo "$*"; }
log_success() { echo "$*"; }
log_warning() { echo "WARN $*"; }

mkdir -p "$tmp/stubs"
cat > "$tmp/stubs/hyprctl" <<'EOF'
#!/bin/sh
if [ "$1" = version ]; then
    [ -n "$HYPR_TAG" ] || exit 1
    printf '{\n    "version": "%s",\n    "tag": "v%s",\n}\n' "$HYPR_TAG" "$HYPR_TAG"
fi
exit 0
EOF
chmod +x "$tmp/stubs/hyprctl"

# hypr <home> <hyprland version or ""> runs it as the installer does (set -e only).
hypr() {
    (
        set -e +u +o pipefail
        export HOME="$1" HYPR_TAG="$2" PATH="$tmp/stubs:$PATH"
        DESKTOP_TYPE=hyprland
        configure_hyprland
        echo "ok=$HYPR_RULES_OK"
    )
}
home() { mkdir -p "$tmp/$1/.config/hypr" && echo "$tmp/$1"; }

# Lua config next to a stale, unloaded juhradial-rules.conf (the #179 setup).
h="$(home lua)"; cfg="$h/.config/hypr"
echo '-- user config' > "$cfg/hyprland.lua"
printf 'windowrulev2 = float, title:^(JuhRadial MX)$\n' > "$cfg/juhradial-rules.conf"
out="$(hypr "$h" 0.56.2)"
grep -q 'hl.window_rule' "$cfg/hyprland.lua" || fail "lua: no rules in hyprland.lua: $out"
grep -q '^ok=true$' <<< "$out" || fail "lua: not reported as configured: $out"
[ "$(ls "$cfg")" = "$(printf 'hyprland.lua\njuhradial-rules.conf')" ] || fail "lua: extra files: $(ls "$cfg")"
hypr "$h" 0.56.2 > /dev/null
[ "$(grep -c 'juhradial-overlay' "$cfg/hyprland.lua")" = 1 ] || fail "lua: rules added twice"
lua_cfg="$cfg/hyprland.lua"

# Lua rules the user keeps in a module of their own.
h="$(home module)"; cfg="$h/.config/hypr"
mkdir -p "$cfg/modules"
echo 'require("modules.juhradial")' > "$cfg/hyprland.lua"
echo 'hl.window_rule({ name = "jr", match = { class = "^(JuhRadial MX)$" }, float = true })' > "$cfg/modules/juhradial.lua"
out="$(hypr "$h" 0.56.2)"
[ "$(cat "$cfg/hyprland.lua")" = 'require("modules.juhradial")' ] || fail "module: hyprland.lua changed"
grep -q '^ok=true$' <<< "$out" || fail "module: not reported as configured: $out"

# hyprland.conf on 0.53+ gets a rule block, before 0.53 windowrulev2.
h="$(home conf-new)"; cfg="$h/.config/hypr"
echo '# user config' > "$cfg/hyprland.conf"
out="$(hypr "$h" 0.56.2)"
grep -q '^windowrule {$' "$cfg/hyprland.conf" || fail "conf 0.56: no rule block: $out"
! grep -q 'windowrulev2' "$cfg/hyprland.conf" || fail "conf 0.56: windowrulev2 written"
grep -q '^ok=true$' <<< "$out" || fail "conf 0.56: not reported as configured: $out"
conf_cfg="$cfg/hyprland.conf"

h="$(home conf-old)"; cfg="$h/.config/hypr"
echo '# user config' > "$cfg/hyprland.conf"
out="$(hypr "$h" 0.52.2)"
grep -q '^windowrulev2 = float, title:^(JuhRadial MX)\$$' "$cfg/hyprland.conf" || fail "conf 0.52: no windowrulev2: $out"
! grep -q '^windowrule {$' "$cfg/hyprland.conf" || fail "conf 0.52: rule block written"

# Old windowrulev2 rules on 0.53+ are not loaded: warn, do not claim success.
h="$(home conf-stale)"; cfg="$h/.config/hypr"
printf 'windowrulev2 = float, title:^(JuhRadial MX)$\n' > "$cfg/hyprland.conf"
out="$(hypr "$h" 0.56.2)"
grep -q '^WARN ' <<< "$out" && grep -q '^ok=false$' <<< "$out" || fail "stale rules: no warning: $out"
[ "$(wc -l < "$cfg/hyprland.conf")" = 1 ] || fail "stale rules: hyprland.conf changed"

# No way to add the rules: unknown version, no config, read-only config.
h="$(home no-version)"; cfg="$h/.config/hypr"
echo '# user config' > "$cfg/hyprland.conf"
out="$(hypr "$h" "")"
grep -q '^WARN ' <<< "$out" && grep -q '^ok=false$' <<< "$out" || fail "no version: no warning: $out"
[ "$(cat "$cfg/hyprland.conf")" = '# user config' ] || fail "no version: hyprland.conf changed"

h="$(home empty)"; cfg="$h/.config/hypr"
out="$(hypr "$h" 0.56.2)"
grep -q '^WARN ' <<< "$out" && grep -q '^ok=false$' <<< "$out" || fail "no config: no warning: $out"
[ -z "$(ls -A "$cfg")" ] || fail "no config: wrote $(ls -A "$cfg")"

h="$(home read-only)"; cfg="$h/.config/hypr"
echo '-- user config' > "$cfg/hyprland.lua"
chmod a-w "$cfg/hyprland.lua"
out="$(hypr "$h" 0.56.2)"
grep -q '^WARN ' <<< "$out" && grep -q '^ok=false$' <<< "$out" || fail "read-only: no warning: $out"

# Hyprland's own parser on the generated configs, when it is installed.
if command -v Hyprland > /dev/null; then
    for f in "$lua_cfg" "$conf_cfg"; do
        res="$(cd / && Hyprland --verify-config -c "$f" 2>&1 | sed -n '/Config parsing result/,$p')"
        grep -q 'config ok' <<< "$res" || fail "Hyprland rejects $f: $res"
    done
    echo "checked with $(Hyprland --version | head -n 1)"
fi
echo "PASS: install.sh configure_hyprland"
