# Contributing to JuhRadial MX

First off, thank you for considering contributing to JuhRadial MX! It's people like you that make this project better for everyone.

## Code of Conduct

By participating in this project, you agree to maintain a welcoming, inclusive, and harassment-free environment. Please be respectful and constructive in all interactions.

## How Can I Contribute?

### Reporting Bugs

Before creating a bug report, please check the [existing issues](https://github.com/JuhLabs/juhradial-mx/issues) to avoid duplicates.

When reporting a bug, include:

- **Clear title** describing the issue
- **Steps to reproduce** the behavior
- **Expected behavior** vs **actual behavior**
- **System information**:
  - Linux distribution and version
  - Desktop environment (KDE Plasma version)
  - Logitech mouse model
  - JuhRadial MX version

### Suggesting Features

Feature requests are welcome! Please:

1. Check existing issues/discussions first
2. Describe the problem your feature would solve
3. Propose your solution
4. Consider alternatives you've thought about

### Pull Requests

1. **Fork** the repository
2. **Create a branch** from `master`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes** following our code style
4. **Test thoroughly** on your system
5. **Commit** with clear messages:
   ```bash
   git commit -m "feat: add new radial menu animation"
   ```
6. **Push** and create a Pull Request

## Development Setup

### Prerequisites

- Rust (latest stable)
- Python 3.10+
- KDE Plasma 6 with Wayland

### System Dependencies

**Fedora:**
```bash
sudo dnf install \
  rust cargo \
  python3-pyqt6 python3-pyqt6-svg \
  python3-gobject gtk4 libadwaita \
  dbus-devel systemd-devel \
  libevdev-devel hidapi-devel \
  logiops \
  git make
```

**Arch Linux:**
```bash
sudo pacman -S --needed \
  rust \
  python-pyqt6 python-pyqt6-svg \
  python-gobject gtk4 libadwaita \
  dbus systemd-libs \
  libevdev hidapi \
  git make base-devel

# Install logiops from AUR
yay -S logiops
```

**Debian/Ubuntu:**
```bash
sudo apt install \
  rustc cargo \
  python3-pyqt6 python3-pyqt6.qtsvg \
  python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
  libdbus-1-dev libsystemd-dev \
  libevdev-dev libhidapi-dev \
  git make build-essential
```

### Building

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/juhradial-mx
cd juhradial-mx

# Build the daemon
make build

# Or manually
cd daemon && cargo build --release
```

### Running Locally

```bash
# Start the daemon in verbose mode
./daemon/target/release/juhradiald --verbose

# In another terminal, run the overlay
python3 overlay/juhradial-overlay.py

# Or use the launcher script
./juhradial-mx.sh
```

### Testing

```bash
# Run Rust tests
cd daemon && cargo test

# Lint checks
cd daemon && cargo clippy
```

## Code Style

### Rust (Daemon)

- Follow [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/)
- Use `cargo fmt` before committing
- Run `cargo clippy` and address warnings
- Document public APIs with `///` doc comments

### Python (Overlay)

- Follow PEP 8 style guide
- Use type hints where practical
- Keep functions focused and well-named

## Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style (formatting, no logic change)
- `refactor`: Code refactoring
- `test`: Adding/updating tests
- `chore`: Maintenance tasks

Examples:
```
feat(overlay): add glassmorphic blur effect
fix(daemon): correct battery percentage parsing
docs: update installation instructions
```

## Project Structure

```
juhradial-mx/
├── daemon/           # Rust daemon (input handling, D-Bus, HID++)
│   └── src/
├── overlay/          # Python UI components
│   ├── juhradial-overlay.py   # PyQt6 radial menu
│   └── settings_dashboard.py  # GTK4/Adwaita settings app
├── assets/           # Icons and screenshots
└── packaging/        # Distribution files (systemd, udev, logid.cfg)
```

## Getting Help

- **Questions**: Open a [Discussion](https://github.com/JuhLabs/juhradial-mx/discussions)
- **Bugs**: Open an [Issue](https://github.com/JuhLabs/juhradial-mx/issues)

## Recognition

Contributors will be recognized in:
- The project README
- Release notes

Thank you for helping make JuhRadial MX better!

---

*JuhLabs - Julian Hermstad*
