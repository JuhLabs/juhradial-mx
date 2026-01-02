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

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/JuhLabs/juhradial-mx"
INSTALL_DIR="/opt/juhradial-mx"
BIN_DIR="/usr/local/bin"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
CONFIG_DIR="$HOME/.config/juhradial"

print_banner() {
    echo -e "${CYAN}"
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║                                                      ║"
    echo "║           JuhRadial MX Installer                     ║"
    echo "║     Beautiful radial menu for MX Master on Linux     ║"
    echo "║                                                      ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

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
        VERSION=$VERSION_ID
    elif [ -f /etc/lsb-release ]; then
        . /etc/lsb-release
        DISTRO=$DISTRIB_ID
        VERSION=$DISTRIB_RELEASE
    else
        DISTRO=$(uname -s)
    fi

    log_info "Detected: $DISTRO $VERSION"
}

check_wayland() {
    if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
        log_success "Wayland session detected"
    else
        log_warning "X11 session detected. JuhRadial MX works best on Wayland."
        log_warning "Some features may be limited on X11."
    fi
}

check_desktop() {
    # Detect desktop environment / compositor
    DESKTOP_TYPE="unknown"

    if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
        DESKTOP_TYPE="hyprland"
        log_success "Hyprland detected"
    elif [ "$XDG_CURRENT_DESKTOP" = "KDE" ] || [ "$DESKTOP_SESSION" = "plasma" ]; then
        DESKTOP_TYPE="kde"
        log_success "KDE Plasma detected"
    elif [ "$XDG_CURRENT_DESKTOP" = "sway" ]; then
        DESKTOP_TYPE="sway"
        log_success "Sway detected"
    else
        log_warning "Desktop detected: $XDG_CURRENT_DESKTOP"
        log_warning "JuhRadial MX works best on KDE Plasma or Hyprland."
    fi
}

configure_hyprland() {
    # Configure Hyprland window rules for overlay
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
        log_info "Hyprland rules already configured"
        return 0
    fi

    # Try dots-hyprland custom rules first (end-4/dots-hyprland structure)
    if [ -f "$HYPR_CONFIG_DIR/custom/rules.conf" ]; then
        echo "$RULES_CONTENT" >> "$HYPR_CONFIG_DIR/custom/rules.conf"
        log_success "Added rules to custom/rules.conf (dots-hyprland)"
    # Try standard hyprland.conf
    elif [ -f "$HYPR_CONFIG_DIR/hyprland.conf" ]; then
        echo "$RULES_CONTENT" >> "$HYPR_CONFIG_DIR/hyprland.conf"
        log_success "Added rules to hyprland.conf"
    # Create a new rules file and source it
    else
        mkdir -p "$HYPR_CONFIG_DIR"
        echo "$RULES_CONTENT" > "$HYPR_CONFIG_DIR/juhradial-rules.conf"

        # Try to source it from main config
        if [ -f "$HYPR_CONFIG_DIR/hyprland.conf" ]; then
            echo "source=juhradial-rules.conf" >> "$HYPR_CONFIG_DIR/hyprland.conf"
        fi
        log_success "Created juhradial-rules.conf"
    fi

    # Reload Hyprland config if possible
    if command -v hyprctl &> /dev/null; then
        hyprctl reload 2>/dev/null && log_info "Hyprland config reloaded"
    fi
}

install_deps_fedora() {
    log_info "Installing dependencies for Fedora/RHEL..."
    sudo dnf install -y \
        rust cargo \
        python3 python3-pip \
        python3-pyqt6 python3-pyqt6-svg \
        python3-gobject gtk4 libadwaita \
        dbus-devel systemd-devel \
        libevdev-devel hidapi-devel \
        logiops \
        git make
}

install_deps_arch() {
    log_info "Installing dependencies for Arch Linux..."
    sudo pacman -S --noconfirm --needed \
        rust \
        python python-pip \
        python-pyqt6 python-pyqt6-svg \
        python-gobject gtk4 libadwaita \
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
    log_info "Installing dependencies for Debian/Ubuntu..."
    sudo apt-get update
    sudo apt-get install -y \
        rustc cargo \
        python3 python3-pip python3-venv \
        python3-pyqt6 python3-pyqt6.qtsvg \
        python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
        libdbus-1-dev libsystemd-dev \
        libevdev-dev libhidapi-dev \
        git make build-essential

    # logiops needs to be built from source on Debian
    if ! command -v logid &> /dev/null; then
        log_warning "logiops not found. Please install it manually from:"
        log_warning "https://github.com/PixlOne/logiops"
    fi
}

install_deps_opensuse() {
    log_info "Installing dependencies for openSUSE..."
    sudo zypper install -y \
        rust cargo \
        python3 python3-pip \
        python3-qt6 python3-qt6-svg \
        python3-gobject gtk4 libadwaita-devel \
        dbus-1-devel systemd-devel \
        libevdev-devel libhidapi-devel \
        git make
}

install_dependencies() {
    case $DISTRO in
        fedora|rhel|centos)
            install_deps_fedora
            ;;
        arch|manjaro|endeavouros)
            install_deps_arch
            ;;
        debian|ubuntu|linuxmint|pop)
            install_deps_debian
            ;;
        opensuse*|suse*)
            install_deps_opensuse
            ;;
        *)
            log_error "Unsupported distribution: $DISTRO"
            log_error "Please install dependencies manually. See CONTRIBUTING.md"
            exit 1
            ;;
    esac
    log_success "Dependencies installed"
}

clone_repo() {
    log_info "Cloning JuhRadial MX repository..."

    if [ -d "$INSTALL_DIR" ]; then
        log_info "Existing installation found. Updating..."
        cd "$INSTALL_DIR"
        sudo git pull
    else
        sudo git clone "$REPO_URL" "$INSTALL_DIR"
        sudo chown -R $USER:$USER "$INSTALL_DIR"
    fi

    cd "$INSTALL_DIR"
    log_success "Repository ready"
}

build_project() {
    log_info "Building JuhRadial MX..."
    cd "$INSTALL_DIR"

    # Build Rust daemon
    log_info "Building Rust daemon..."
    cd daemon
    cargo build --release
    cd ..

    log_success "Build complete"
}

install_files() {
    log_info "Installing files..."

    # Install daemon binary
    sudo install -Dm755 daemon/target/release/juhradiald "$BIN_DIR/juhradiald"

    # Install overlay scripts
    sudo mkdir -p /usr/share/juhradial
    sudo cp -r overlay/*.py /usr/share/juhradial/

    # Install launcher scripts
    sudo install -Dm755 juhradial-mx.sh "$BIN_DIR/juhradial-mx"
    sudo install -Dm755 juhradial-settings.sh "$BIN_DIR/juhradial-settings"

    # Install desktop files
    sudo install -Dm644 juhradial-mx.desktop /usr/share/applications/juhradial-mx.desktop
    sudo install -Dm644 org.kde.juhradialmx.settings.desktop /usr/share/applications/org.kde.juhradialmx.settings.desktop

    # Install icons
    sudo install -Dm644 assets/juhradial-mx.svg /usr/share/icons/hicolor/scalable/apps/juhradial-mx.svg

    # Install systemd service
    mkdir -p "$SYSTEMD_USER_DIR"
    cp packaging/systemd/juhradialmx-daemon.service "$SYSTEMD_USER_DIR/"

    # Install udev rules
    if [ -f packaging/udev/99-logitech-hidpp.rules ]; then
        sudo install -Dm644 packaging/udev/99-logitech-hidpp.rules /etc/udev/rules.d/
        sudo udevadm control --reload-rules
        sudo udevadm trigger
    fi

    # Create config directory
    mkdir -p "$CONFIG_DIR"

    log_success "Files installed"
}

configure_logiops() {
    log_info "Configuring logiops..."

    if [ -f packaging/logid.cfg ]; then
        if [ -f /etc/logid.cfg ]; then
            sudo cp /etc/logid.cfg /etc/logid.cfg.backup
            log_info "Backed up existing logid.cfg"
        fi
        sudo cp packaging/logid.cfg /etc/logid.cfg

        # Enable and start logid service
        sudo systemctl enable logid
        sudo systemctl restart logid
        log_success "logiops configured"
    else
        log_warning "logid.cfg not found in packaging/"
    fi
}

enable_service() {
    log_info "Enabling JuhRadial MX service..."

    systemctl --user daemon-reload
    systemctl --user enable juhradialmx-daemon
    systemctl --user start juhradialmx-daemon

    log_success "Service enabled and started"
}

print_success() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                      ║${NC}"
    echo -e "${GREEN}║       JuhRadial MX installed successfully!           ║${NC}"
    echo -e "${GREEN}║                                                      ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "To start using JuhRadial MX:"
    echo ""
    echo "  1. Run: juhradial-mx"
    echo "     Or find 'JuhRadial MX' in your application menu"
    echo ""
    echo "  2. Hold the gesture button (thumb button) on your MX Master"
    echo "     to open the radial menu"
    echo ""
    echo "  3. Right-click the tray icon to access Settings"
    echo ""

    if [ "$DESKTOP_TYPE" = "hyprland" ]; then
        echo -e "${CYAN}Hyprland window rules have been configured automatically.${NC}"
        echo ""
    fi

    echo "Service status: systemctl --user status juhradialmx-daemon"
    echo "View logs: journalctl --user -u juhradialmx-daemon -f"
    echo ""
    echo -e "${CYAN}Thank you for using JuhRadial MX!${NC}"
    echo -e "${CYAN}https://github.com/JuhLabs/juhradial-mx${NC}"
    echo ""
}

# Main installation flow
main() {
    print_banner
    check_root
    detect_distro
    check_wayland
    check_desktop

    echo ""
    read -p "Continue with installation? [Y/n] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]] && [[ ! -z $REPLY ]]; then
        log_info "Installation cancelled."
        exit 0
    fi

    install_dependencies
    clone_repo
    build_project
    install_files
    configure_logiops
    configure_hyprland
    enable_service
    print_success
}

# Run main function
main "$@"
