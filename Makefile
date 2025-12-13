# JuhRadial MX - Unified Build System
# Builds all components: daemon (Rust), kwin-script (TypeScript), widget (QML)
#
# Usage:
#   make build       - Build all components
#   make test        - Run all tests
#   make clean       - Clean build artifacts
#   make daemon      - Build only the Rust daemon
#   make kwin-script - Build only the KWin script
#   make install     - Install to system (requires root)
#   make bench       - Run performance benchmarks

.PHONY: all build test clean daemon kwin-script widget install bench help

# Default target
all: build

# Build all components
build: daemon kwin-script
	@echo "✓ Build complete"
	@echo "Note: Widget (QML) requires KDE Plasma 6 environment"

# Rust daemon
daemon:
	@echo "Building Rust daemon..."
	cd daemon && cargo build --release
	@echo "✓ Daemon built: daemon/target/release/juhradiald"

# KWin script (TypeScript → JavaScript)
kwin-script:
	@echo "Building KWin script..."
	cd kwin-script && npm install && npm run build
	@echo "✓ KWin script built: kwin-script/dist/"

# Plasma widget (no build step, just validate)
widget:
	@echo "Validating Plasma widget..."
	@test -f widget/org.kde.juhradialmx/metadata.json || (echo "❌ Widget metadata.json missing" && exit 1)
	@test -f widget/org.kde.juhradialmx/contents/ui/main.qml || (echo "❌ Widget main.qml missing" && exit 1)
	@echo "✓ Widget structure validated"

# Run all tests
test: test-daemon test-kwin
	@echo "✓ All tests passed"

# Test Rust daemon
test-daemon:
	@echo "Testing Rust daemon..."
	cd daemon && cargo test

# Test KWin script (if tests exist)
test-kwin:
	@echo "KWin script tests: (manual testing required on Linux)"

# Run performance benchmarks
bench:
	@echo "Running performance benchmarks..."
	cd daemon && cargo bench
	@echo "✓ Benchmarks complete"

# Clean all build artifacts
clean:
	@echo "Cleaning build artifacts..."
	cd daemon && cargo clean || true
	cd kwin-script && rm -rf node_modules dist || true
	@echo "✓ Clean complete"

# Install to system (Linux only, requires root)
install: build
	@echo "Installing JuhRadial MX..."
	@echo "Note: This requires root privileges on Linux"
	# Daemon binary
	install -Dm755 daemon/target/release/juhradiald $(DESTDIR)/usr/bin/juhradiald
	# KWin script
	install -Dm644 kwin-script/metadata.json $(DESTDIR)/usr/share/kwin/scripts/juhradial-mx/metadata.json
	install -Dm644 kwin-script/dist/main.js $(DESTDIR)/usr/share/kwin/scripts/juhradial-mx/contents/code/main.js
	# Plasma widget
	cp -r widget/org.kde.juhradialmx $(DESTDIR)/usr/share/plasma/plasmoids/
	# Themes
	cp -r themes/* $(DESTDIR)/usr/share/juhradial/themes/
	# systemd service
	install -Dm644 packaging/systemd/juhradialmx-daemon.service $(DESTDIR)/usr/lib/systemd/user/juhradialmx-daemon.service
	# udev rules
	install -Dm644 packaging/udev/99-juhradialmx.rules $(DESTDIR)/usr/lib/udev/rules.d/99-juhradialmx.rules
	@echo "✓ Installation complete"

# Development helpers
dev-daemon:
	@echo "Starting daemon in development mode..."
	cd daemon && cargo run -- --verbose

# Format code
fmt:
	cd daemon && cargo fmt
	cd kwin-script && npx prettier --write src/

# Lint code
lint:
	cd daemon && cargo clippy -- -D warnings
	cd kwin-script && npx eslint src/

# Help
help:
	@echo "JuhRadial MX Build System"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  build       - Build all components (default)"
	@echo "  test        - Run all tests"
	@echo "  bench       - Run performance benchmarks"
	@echo "  clean       - Clean build artifacts"
	@echo "  daemon      - Build only Rust daemon"
	@echo "  kwin-script - Build only KWin script"
	@echo "  widget      - Validate Plasma widget"
	@echo "  install     - Install to system (requires root)"
	@echo "  fmt         - Format all code"
	@echo "  lint        - Lint all code"
	@echo "  help        - Show this help"
