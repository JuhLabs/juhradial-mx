# JuhRadial MX - Build System
#
# Usage:
#   make build   - Build the Rust daemon
#   make clean   - Clean build artifacts
#   make run     - Run JuhRadial MX (daemon + overlay)

.PHONY: all build clean run audit help

# Default target
all: build

# Build Rust daemon
build:
	@echo "Building Rust daemon..."
	cd daemon && cargo build --release
	@echo "✓ Daemon built: daemon/target/release/juhradiald"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	cd daemon && cargo clean
	@echo "✓ Clean complete"

# Run JuhRadial MX
run: build
	@echo "Starting JuhRadial MX..."
	./scripts/juhradial-mx.sh

# Security audit — scans Cargo.lock for known CVEs in transitive deps.
# Requires cargo-audit: `cargo install cargo-audit --locked`.
# Run periodically (weekly or pre-release).
audit:
	@command -v cargo-audit >/dev/null 2>&1 || { \
	  echo "cargo-audit not installed. Run: cargo install cargo-audit --locked"; \
	  exit 1; \
	}
	@echo "Auditing daemon Cargo.lock against RustSec advisory database..."
	cd daemon && cargo audit
	@echo "✓ Audit complete"

# Help
help:
	@echo "JuhRadial MX Build System"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  build  - Build the Rust daemon (default)"
	@echo "  clean  - Clean build artifacts"
	@echo "  run    - Build and run JuhRadial MX"
	@echo "  audit  - Run cargo-audit against Cargo.lock for known CVEs"
	@echo "  help   - Show this help"
