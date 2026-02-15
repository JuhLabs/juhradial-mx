#!/bin/bash
#
# JuhRadial MX Universal Installer
# https://github.com/JuhLabs/juhradial-mx
#
# Usage: curl -fsSL https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/install.sh | bash
#
# This script will:
# 1. Detect your Linux distribution
# 2. Install required dependencies
# 3. Clone and build JuhRadial MX
# 4. Install and enable the systemd service
#

set -e

# ── Colors & Formatting ──────────────────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
GRAY='\033[0;90m'

# ── Configuration ────────────────────────────────────────────────────
REPO_URL="https://github.com/JuhLabs/juhradial-mx"
INSTALL_DIR="/opt/juhradial-mx"
BIN_DIR="/usr/local/bin"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
CONFIG_DIR="$HOME/.config/juhradial"
DISTRO_FAMILY=""
TOTAL_STEPS=7
CURRENT_STEP=0
INSTALL_MODE="install"  # "install" or "upgrade"

# ── Output helpers ───────────────────────────────────────────────────
print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}"
    echo "        ╭──────────────────────────────────────────╮"
    echo "        │                                          │"
    echo -e "        │   ${WHITE}JuhRadial MX${CYAN}  ·  Installer             │"
    echo "        │                                          │"
    echo -e "        │   ${RESET}${DIM}Radial menu for MX Master on Linux${RESET}${CYAN}${BOLD}   │"
    echo "        │                                          │"
    echo "        ╰──────────────────────────────────────────╯"
    echo -e "${RESET}"
}

step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo ""
    echo -e "  ${CYAN}${BOLD}[$CURRENT_STEP/$TOTAL_STEPS]${RESET} ${BOLD}$1${RESET}"
    echo -e "  ${GRAY}$(printf '%.0s─' {1..48})${RESET}"
}

log_info() {
    echo -e "  ${BLUE}→${RESET} $1"
}

log_success() {
    echo -e "  ${GREEN}✓${RESET} $1"
}

log_warning() {
    echo -e "  ${YELLOW}!${RESET} ${YELLOW}$1${RESET}"
}

log_error() {
    echo -e "  ${RED}✗${RESET} ${RED}$1${RESET}"
}

log_dim() {
    echo -e "  ${GRAY}  $1${RESET}"
}

# ── Pre-flight checks ───────────────────────────────────────────────
check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_error "Do not run this script as root. It will ask for sudo when needed."
        exit 1
    fi
}

detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO=$ID
        DISTRO_LIKE=$ID_LIKE
        DISTRO_PRETTY="${PRETTY_NAME:-$ID}"
        VERSION=$VERSION_ID
    elif [ -f /etc/lsb-release ]; then
        . /etc/lsb-release
        DISTRO=$DISTRIB_ID
        DISTRO_PRETTY="$DISTRIB_ID $DISTRIB_RELEASE"
        VERSION=$DISTRIB_RELEASE
    else
        DISTRO=$(uname -s)
        DISTRO_PRETTY="$DISTRO"
    fi

    resolve_distro_family
}

resolve_distro_family() {
    DISTRO_FAMILY="$DISTRO"

    case "$DISTRO" in
        arch|manjaro|endeavouros|garuda|artix|cachyos|arcolinux|archcraft)
            DISTRO_FAMILY="arch"
            ;;
        fedora|rhel|centos|rocky|almalinux|nobara|ultramarine)
            DISTRO_FAMILY="fedora"
            ;;
        debian|ubuntu|linuxmint|pop|elementary|kali|zorin|tuxedo|neon|mx)
            DISTRO_FAMILY="debian"
            ;;
        opensuse*|suse*|sles)
            DISTRO_FAMILY="opensuse"
            ;;
    esac

    # Fallback: check ID_LIKE for derivatives we didn't list
    if [ "$DISTRO_FAMILY" = "$DISTRO" ] && [ -n "$DISTRO_LIKE" ]; then
        if [[ "$DISTRO_LIKE" == *"arch"* ]]; then
            DISTRO_FAMILY="arch"
        elif [[ "$DISTRO_LIKE" == *"fedora"* ]] || [[ "$DISTRO_LIKE" == *"rhel"* ]]; then
            DISTRO_FAMILY="fedora"
        elif [[ "$DISTRO_LIKE" == *"debian"* ]] || [[ "$DISTRO_LIKE" == *"ubuntu"* ]]; then
            DISTRO_FAMILY="debian"
        elif [[ "$DISTRO_LIKE" == *"suse"* ]]; then
            DISTRO_FAMILY="opensuse"
        fi
    fi

    # Final fallback: detect by package manager
    if [ "$DISTRO_FAMILY" = "$DISTRO" ] || [ -z "$DISTRO_FAMILY" ]; then
        if command -v pacman &> /dev/null; then
            DISTRO_FAMILY="arch"
        elif command -v apt-get &> /dev/null; then
            DISTRO_FAMILY="debian"
        elif command -v dnf &> /dev/null; then
            DISTRO_FAMILY="fedora"
        elif command -v zypper &> /dev/null; then
            DISTRO_FAMILY="opensuse"
        fi
    fi
}

check_wayland() {
    if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
        WAYLAND_OK=true
    else
        WAYLAND_OK=false
    fi
}

check_desktop() {
    DESKTOP_TYPE="unknown"
    DESKTOP_LABEL="${XDG_CURRENT_DESKTOP:-unknown}"

    # Check compositors / desktop environments
    if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
        DESKTOP_TYPE="hyprland"
        DESKTOP_LABEL="Hyprland"
    elif [ -n "$SWAYSOCK" ] || [ "$XDG_CURRENT_DESKTOP" = "sway" ]; then
        DESKTOP_TYPE="sway"
        DESKTOP_LABEL="Sway"
    elif [[ "$XDG_CURRENT_DESKTOP" == *"KDE"* ]] || [ "$DESKTOP_SESSION" = "plasma" ] || [ "$DESKTOP_SESSION" = "plasmawayland" ]; then
        DESKTOP_TYPE="kde"
        DESKTOP_LABEL="KDE Plasma"
    elif [[ "$XDG_CURRENT_DESKTOP" == *"GNOME"* ]]; then
        DESKTOP_TYPE="gnome"
        DESKTOP_LABEL="GNOME"
    elif [[ "$XDG_CURRENT_DESKTOP" == *"COSMIC"* ]] || pgrep -x cosmic-comp &> /dev/null; then
        DESKTOP_TYPE="cosmic"
        DESKTOP_LABEL="COSMIC"
    elif [[ "$XDG_CURRENT_DESKTOP" == *"X-Cinnamon"* ]]; then
        DESKTOP_TYPE="cinnamon"
        DESKTOP_LABEL="Cinnamon"
    elif [[ "$XDG_CURRENT_DESKTOP" == *"XFCE"* ]]; then
        DESKTOP_TYPE="xfce"
        DESKTOP_LABEL="XFCE"
    elif [[ "$XDG_CURRENT_DESKTOP" == *"Budgie"* ]]; then
        DESKTOP_TYPE="budgie"
        DESKTOP_LABEL="Budgie"
    elif pgrep -x river &> /dev/null; then
        DESKTOP_TYPE="river"
        DESKTOP_LABEL="River"
    elif pgrep -x niri &> /dev/null; then
        DESKTOP_TYPE="niri"
        DESKTOP_LABEL="Niri"
    elif pgrep -x wayfire &> /dev/null; then
        DESKTOP_TYPE="wayfire"
        DESKTOP_LABEL="Wayfire"
    elif [ "$XDG_CURRENT_DESKTOP" = "i3" ] || pgrep -x i3 &> /dev/null; then
        DESKTOP_TYPE="i3"
        DESKTOP_LABEL="i3"
    fi
}

check_existing_install() {
    if [ -d "$INSTALL_DIR" ]; then
        INSTALL_MODE="upgrade"
        # Try to read current version from the installed copy
        if [ -f "$INSTALL_DIR/CHANGELOG.md" ]; then
            INSTALLED_VERSION=$(grep -m1 -oP '## \[?\Kv[0-9]+\.[0-9]+\.[0-9]+' "$INSTALL_DIR/CHANGELOG.md" 2>/dev/null || echo "")
        fi
    fi
}

check_logitech_device() {
    LOGI_DEVICE_FOUND=false

    # Check for Logitech USB devices (vendor ID 046d)
    if command -v lsusb &> /dev/null; then
        if lsusb 2>/dev/null | grep -qi "046d:"; then
            LOGI_DEVICE_FOUND=true
        fi
    fi

    # Fallback: check HID subsystem
    if [ "$LOGI_DEVICE_FOUND" = false ]; then
        if ls /sys/bus/hid/devices/ 2>/dev/null | grep -qi "046D"; then
            LOGI_DEVICE_FOUND=true
        fi
    fi
}

print_system_info() {
    echo ""
    echo -e "  ${BOLD}System${RESET}"
    echo -e "  ${GRAY}$(printf '%.0s─' {1..48})${RESET}"

    # Distro (use PRETTY_NAME for a nicer display)
    echo -e "  ${DIM}Distro${RESET}       ${WHITE}${DISTRO_PRETTY}${RESET} ${GRAY}(${DISTRO_FAMILY})${RESET}"

    # Kernel
    echo -e "  ${DIM}Kernel${RESET}       $(uname -r)"

    # Session
    if [ "$WAYLAND_OK" = true ]; then
        echo -e "  ${DIM}Session${RESET}      ${GREEN}Wayland${RESET}"
    else
        echo -e "  ${DIM}Session${RESET}      ${YELLOW}X11${RESET} ${GRAY}— some features may be limited${RESET}"
    fi

    # Desktop
    case "$DESKTOP_TYPE" in
        hyprland|kde|sway)
            echo -e "  ${DIM}Desktop${RESET}      ${GREEN}${DESKTOP_LABEL}${RESET}"
            ;;
        gnome|cosmic|cinnamon|xfce|budgie|river|niri|wayfire|i3)
            echo -e "  ${DIM}Desktop${RESET}      ${WHITE}${DESKTOP_LABEL}${RESET} ${GRAY}— community supported${RESET}"
            ;;
        *)
            echo -e "  ${DIM}Desktop${RESET}      ${YELLOW}${DESKTOP_LABEL}${RESET} ${GRAY}— works best on KDE/Hyprland${RESET}"
            ;;
    esac

    # Logitech device
    if [ "$LOGI_DEVICE_FOUND" = true ]; then
        echo -e "  ${DIM}Mouse${RESET}        ${GREEN}Logitech receiver detected${RESET}"
    else
        echo -e "  ${DIM}Mouse${RESET}        ${YELLOW}No Logitech receiver found${RESET} ${GRAY}— plug in to continue${RESET}"
    fi

    # logid
    if command -v logid &> /dev/null; then
        echo -e "  ${DIM}logiops${RESET}      ${GREEN}installed${RESET}"
    else
        echo -e "  ${DIM}logiops${RESET}      ${GRAY}not found — will attempt install${RESET}"
    fi

    # Install mode
    if [ "$INSTALL_MODE" = "upgrade" ]; then
        local ver_info=""
        [ -n "$INSTALLED_VERSION" ] && ver_info=" ${GRAY}(${INSTALLED_VERSION})${RESET}"
        echo -e "  ${DIM}Mode${RESET}         ${CYAN}Upgrade${RESET}${ver_info}"
    else
        echo -e "  ${DIM}Mode${RESET}         ${WHITE}Fresh install${RESET}"
    fi

    echo ""
}

# ── Hyprland configuration ──────────────────────────────────────────
configure_hyprland() {
    if [ "$DESKTOP_TYPE" != "hyprland" ]; then
        return 0
    fi

    log_info "Configuring Hyprland window rules..."

    HYPR_CONFIG_DIR="$HOME/.config/hypr"
    RULES_CONTENT='
# ######## JuhRadial MX - Radial Menu Overlay ########
# These rules ensure the radial menu appears correctly as an overlay
windowrulev2 = float, title:^(JuhRadial MX)$
windowrulev2 = noblur, title:^(JuhRadial MX)$
windowrulev2 = noborder, title:^(JuhRadial MX)$
windowrulev2 = noshadow, title:^(JuhRadial MX)$
windowrulev2 = pin, title:^(JuhRadial MX)$
windowrulev2 = noanim, title:^(JuhRadial MX)$'

    # Check if rules already exist
    if grep -q "JuhRadial MX" "$HYPR_CONFIG_DIR"/*.conf "$HYPR_CONFIG_DIR"/**/*.conf 2>/dev/null; then
        log_dim "Hyprland rules already configured"
        return 0
    fi

    # Try dots-hyprland custom rules first (end-4/dots-hyprland structure)
    if [ -f "$HYPR_CONFIG_DIR/custom/rules.conf" ]; then
        echo "$RULES_CONTENT" >> "$HYPR_CONFIG_DIR/custom/rules.conf"
        log_success "Added rules to custom/rules.conf"
    # Try standard hyprland.conf
    elif [ -f "$HYPR_CONFIG_DIR/hyprland.conf" ]; then
        echo "$RULES_CONTENT" >> "$HYPR_CONFIG_DIR/hyprland.conf"
        log_success "Added rules to hyprland.conf"
    # Create a new rules file and source it
    else
        mkdir -p "$HYPR_CONFIG_DIR"
        echo "$RULES_CONTENT" > "$HYPR_CONFIG_DIR/juhradial-rules.conf"

        if [ -f "$HYPR_CONFIG_DIR/hyprland.conf" ]; then
            echo "source=juhradial-rules.conf" >> "$HYPR_CONFIG_DIR/hyprland.conf"
        fi
        log_success "Created juhradial-rules.conf"
    fi

    # Reload Hyprland config if possible
    if command -v hyprctl &> /dev/null; then
        hyprctl reload 2>/dev/null && log_dim "Hyprland config reloaded"
    fi
}

# ── Dependency installation ──────────────────────────────────────────
install_deps_fedora() {
    sudo dnf install -y \
        rust cargo \
        python3 python3-pip \
        python3-pyqt6 qt6-qtsvg \
        python3-gobject gtk4 libadwaita \
        gtk4-layer-shell \
        dbus-devel systemd-devel \
        libevdev-devel hidapi-devel \
        logiops \
        git make
}

install_deps_arch() {
    sudo pacman -S --noconfirm --needed \
        rust \
        python python-pip \
        python-pyqt6 qt6-svg \
        python-gobject gtk4 libadwaita \
        gtk4-layer-shell \
        dbus systemd-libs \
        libevdev hidapi \
        git make base-devel

    # Install logiops from AUR if not present
    if ! command -v logid &> /dev/null; then
        log_info "Installing logiops from AUR..."
        if command -v yay &> /dev/null; then
            yay -S --noconfirm logiops
        elif command -v paru &> /dev/null; then
            paru -S --noconfirm logiops
        else
            log_warning "No AUR helper found. Please install logiops manually."
        fi
    fi
}

install_deps_debian() {
    sudo apt-get update
    sudo apt-get install -y \
        rustc cargo \
        python3 python3-pip python3-venv \
        python3-pyqt6 python3-pyqt6.qtsvg \
        python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
        libdbus-1-dev libsystemd-dev \
        libevdev-dev libhidapi-dev \
        git make build-essential

    if apt-cache show libgtk4-layer-shell0 &> /dev/null; then
        sudo apt-get install -y libgtk4-layer-shell0
    fi

    # logiops needs to be built from source on Debian
    if ! command -v logid &> /dev/null; then
        log_warning "logiops not found. Please install it manually from:"
        log_dim "https://github.com/PixlOne/logiops"
    fi
}

install_deps_opensuse() {
    sudo zypper install -y \
        rust cargo \
        python3 python3-pip \
        python3-qt6 python3-qt6-svg \
        python3-gobject gtk4 libadwaita-devel \
        dbus-1-devel systemd-devel \
        libevdev-devel libhidapi-devel \
        git make

    if ! sudo zypper install -y gtk4-layer-shell; then
        log_warning "gtk4-layer-shell not available on this repo"
    fi
}

install_dependencies() {
    step "Installing dependencies"
    log_info "Package manager: ${BOLD}${DISTRO_FAMILY}${RESET}"

    case $DISTRO_FAMILY in
        fedora)
            install_deps_fedora
            ;;
        arch)
            install_deps_arch
            ;;
        debian)
            install_deps_debian
            ;;
        opensuse)
            install_deps_opensuse
            ;;
        *)
            log_error "Unsupported distribution: $DISTRO"
            log_dim "Please install dependencies manually. See CONTRIBUTING.md"
            exit 1
            ;;
    esac
    log_success "Dependencies ready"
}

# ── Repository ───────────────────────────────────────────────────────
clone_repo() {
    step "Fetching source"

    if [ -d "$INSTALL_DIR" ]; then
        log_info "Updating existing installation..."
        sudo chown -R "$USER:$USER" "$INSTALL_DIR"
        git -C "$INSTALL_DIR" fetch origin
        git -C "$INSTALL_DIR" reset --hard origin/master
        git -C "$INSTALL_DIR" clean -fd
    else
        log_info "Cloning repository..."
        sudo git clone "$REPO_URL" "$INSTALL_DIR"
        sudo chown -R "$USER:$USER" "$INSTALL_DIR"
    fi

    cd "$INSTALL_DIR"
    log_success "Source ready"
}

# ── Build ────────────────────────────────────────────────────────────
build_project() {
    step "Building daemon"
    log_info "Compiling Rust daemon..."
    cd "$INSTALL_DIR"

    cd daemon
    cargo build --release
    cd ..

    log_success "Build complete"
}

# ── Install files ────────────────────────────────────────────────────
install_files() {
    step "Installing files"

    # Install daemon binary
    sudo install -Dm755 daemon/target/release/juhradiald "$BIN_DIR/juhradiald"
    log_success "Daemon binary"

    # Install overlay scripts
    sudo mkdir -p /usr/share/juhradial
    sudo cp -r overlay/*.py /usr/share/juhradial/
    log_success "Overlay scripts"

    # Install locale files
    if [ -d overlay/locales ]; then
        sudo mkdir -p /usr/share/juhradial/locales
        sudo cp -r overlay/locales/* /usr/share/juhradial/locales/
    fi

    # Install 3D radial wheel images
    sudo mkdir -p /usr/share/juhradial/assets/radial-wheels
    sudo cp -r assets/radial-wheels/*.png /usr/share/juhradial/assets/radial-wheels/
    log_success "Theme assets"

    # Install device images (mouse illustrations for settings)
    if [ -d assets/devices ]; then
        sudo mkdir -p /usr/share/juhradial/assets/devices
        sudo cp assets/devices/*.png assets/devices/*.svg /usr/share/juhradial/assets/devices/ 2>/dev/null || true
    fi

    # Install AI assistant icons
    sudo cp assets/ai-*.svg /usr/share/juhradial/assets/ 2>/dev/null || true

    # Install launcher scripts
    sudo install -Dm755 juhradial-mx.sh "$BIN_DIR/juhradial-mx"
    sudo install -Dm755 juhradial-settings.sh "$BIN_DIR/juhradial-settings"

    # Install desktop files
    sudo install -Dm644 juhradial-mx.desktop /usr/share/applications/juhradial-mx.desktop
    sudo install -Dm644 org.kde.juhradialmx.settings.desktop /usr/share/applications/org.kde.juhradialmx.settings.desktop

    # Install icons
    sudo install -Dm644 assets/juhradial-mx.svg /usr/share/icons/hicolor/scalable/apps/juhradial-mx.svg
    log_success "Desktop integration"

    # Install systemd service
    mkdir -p "$SYSTEMD_USER_DIR"
    cp packaging/systemd/juhradialmx-daemon.service "$SYSTEMD_USER_DIR/"

    # Install/update udev rules (always update to fix security issues in older versions)
    if [ -f packaging/udev/99-juhradialmx.rules ]; then
        sudo install -Dm644 packaging/udev/99-juhradialmx.rules /etc/udev/rules.d/
        [ -f /etc/udev/rules.d/99-logitech-hidpp.rules ] && sudo rm -f /etc/udev/rules.d/99-logitech-hidpp.rules
        sudo udevadm control --reload-rules
        sudo udevadm trigger
        log_success "udev rules"
    fi

    # Install logid auto-restart service (triggered by udev on device reconnect)
    if [ -f packaging/systemd/juhradialmx-logid-restart.service ]; then
        sudo install -Dm644 packaging/systemd/juhradialmx-logid-restart.service /etc/systemd/system/
        sudo systemctl daemon-reload
        log_success "Device reconnect service"
    fi

    # Create config directory
    mkdir -p "$CONFIG_DIR"
}

# ── Logiops ──────────────────────────────────────────────────────────
configure_logiops() {
    step "Configuring logiops"

    if ! command -v logid &> /dev/null; then
        log_warning "logiops (logid) not found — skipping"
        return 0
    fi

    if ! command -v systemctl &> /dev/null; then
        log_warning "systemctl not available — skipping"
        return 0
    fi

    if [ -f packaging/logid.cfg ]; then
        if [ -f /etc/logid.cfg ]; then
            sudo cp /etc/logid.cfg /etc/logid.cfg.backup
            log_dim "Backed up existing logid.cfg"
        fi
        sudo cp packaging/logid.cfg /etc/logid.cfg

        if systemctl list-unit-files | grep -q "^logid"; then
            sudo systemctl enable logid
            sudo systemctl restart logid
        else
            log_warning "logid service not found. Please enable it manually."
        fi
        log_success "logiops configured"
    else
        log_warning "logid.cfg not found in packaging/"
    fi
}

# ── Systemd service ─────────────────────────────────────────────────
enable_service() {
    step "Enabling service"

    if ! command -v systemctl &> /dev/null; then
        log_warning "systemctl not available — skipping"
        return 0
    fi

    systemctl --user daemon-reload || log_warning "Failed to reload user systemd"
    systemctl --user enable juhradialmx-daemon || log_warning "Failed to enable service"

    # Restart on upgrade, start on fresh install
    if [ "$INSTALL_MODE" = "upgrade" ]; then
        systemctl --user restart juhradialmx-daemon || log_warning "Failed to restart service"
        log_success "Service restarted"
    else
        systemctl --user start juhradialmx-daemon || log_warning "Failed to start service"
        log_success "Service enabled and started"
    fi
}

# ── Desktop environment ─────────────────────────────────────────────
configure_desktop() {
    step "Desktop integration"

    configure_hyprland

    if [ "$DESKTOP_TYPE" = "hyprland" ]; then
        log_success "Hyprland window rules configured"
    elif [ "$DESKTOP_TYPE" = "kde" ] || [ "$DESKTOP_TYPE" = "sway" ]; then
        log_success "No extra configuration needed for ${DESKTOP_LABEL}"
    else
        log_dim "No desktop-specific configuration applied"
    fi
}

# ── Completion ───────────────────────────────────────────────────────
print_success() {
    # Read new version from the freshly fetched source
    local new_version=""
    if [ -f "$INSTALL_DIR/CHANGELOG.md" ]; then
        new_version=$(grep -m1 -oP '## \[?\Kv[0-9]+\.[0-9]+\.[0-9]+' "$INSTALL_DIR/CHANGELOG.md" 2>/dev/null || echo "")
    fi

    local version_display=""
    if [ -n "$new_version" ]; then
        if [ "$INSTALL_MODE" = "upgrade" ] && [ -n "$INSTALLED_VERSION" ] && [ "$INSTALLED_VERSION" != "$new_version" ]; then
            version_display=" ${GRAY}${INSTALLED_VERSION} → ${RESET}${WHITE}${new_version}${RESET}"
        else
            version_display=" ${WHITE}${new_version}${RESET}"
        fi
    fi

    echo ""
    echo -e "  ${GREEN}${BOLD}╭──────────────────────────────────────────╮${RESET}"
    echo -e "  ${GREEN}${BOLD}│                                          │${RESET}"
    if [ "$INSTALL_MODE" = "upgrade" ]; then
        echo -e "  ${GREEN}${BOLD}│   ✓  JuhRadial MX updated!               │${RESET}"
    else
        echo -e "  ${GREEN}${BOLD}│   ✓  JuhRadial MX installed!             │${RESET}"
    fi
    echo -e "  ${GREEN}${BOLD}│                                          │${RESET}"
    echo -e "  ${GREEN}${BOLD}╰──────────────────────────────────────────╯${RESET}"
    [ -n "$version_display" ] && echo -e "  ${DIM}Version${RESET}${version_display}"
    echo ""
    echo -e "  ${BOLD}Getting started${RESET}"
    echo -e "  ${GRAY}$(printf '%.0s─' {1..48})${RESET}"
    echo -e "  ${WHITE}1.${RESET}  Run ${CYAN}juhradial-mx${RESET} or find it in your app menu"
    echo -e "  ${WHITE}2.${RESET}  Hold the ${BOLD}thumb button${RESET} on your MX Master"
    echo -e "  ${WHITE}3.${RESET}  Right-click the tray icon for ${BOLD}Settings${RESET}"
    echo ""
    echo -e "  ${BOLD}Useful commands${RESET}"
    echo -e "  ${GRAY}$(printf '%.0s─' {1..48})${RESET}"
    echo -e "  ${DIM}Status${RESET}   systemctl --user status juhradialmx-daemon"
    echo -e "  ${DIM}Logs${RESET}     journalctl --user -u juhradialmx-daemon -f"
    echo ""
    echo -e "  ${GRAY}github.com/JuhLabs/juhradial-mx${RESET}"
    echo ""
}

# ── Main ─────────────────────────────────────────────────────────────
main() {
    print_banner
    check_root
    detect_distro
    check_wayland
    check_desktop
    check_existing_install
    check_logitech_device
    print_system_info

    if [ "$INSTALL_MODE" = "upgrade" ]; then
        echo -e "  ${BOLD}Proceed with upgrade?${RESET} ${DIM}[Y/n]${RESET} \c"
    else
        echo -e "  ${BOLD}Proceed with installation?${RESET} ${DIM}[Y/n]${RESET} \c"
    fi
    read -n 1 -r < /dev/tty
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]] && [[ ! -z $REPLY ]]; then
        echo ""
        log_info "Cancelled."
        exit 0
    fi

    install_dependencies
    clone_repo
    build_project
    install_files
    configure_logiops
    configure_desktop
    enable_service
    print_success
}

main "$@"
