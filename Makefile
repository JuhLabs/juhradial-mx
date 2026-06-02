# JuhRadial MX - Build System
#
# Usage:
#   make build   - Build the Rust daemon
#   make test    - Run unit tests
#   make fmt     - Format code with rustfmt
#   make clippy  - Run Rust linter
#   make check   - Run fmt check, clippy, and tests
#   make clean   - Clean build artifacts
#   make run     - Run JuhRadial MX (daemon + overlay)

.PHONY: all build test fmt clippy check clean run help

# Default target
all: build

# Build Rust daemon
build:
	@echo "Building Rust daemon..."
	cd daemon && cargo build --release
	@echo "✓ Daemon built: daemon/target/release/juhradiald"

# Run unit tests
test:
	@echo "Running unit tests..."
	cd daemon && cargo test --lib
	@echo "✓ Tests passed"

# Format code with rustfmt
fmt:
	@echo "Formatting code..."
	cd daemon && cargo fmt
	@echo "✓ Code formatted"

# Run Rust linter
clippy:
	@echo "Running clippy linter..."
	cd daemon && cargo clippy --all-targets -- -D warnings
	@echo "✓ No clippy warnings"

# Run all quality checks
check: fmt clippy test
	@echo "✓ All checks passed"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	cd daemon && cargo clean
	@echo "✓ Clean complete"

# Run JuhRadial MX
run: build
	@echo "Starting JuhRadial MX..."
	./scripts/juhradial-mx.sh

# Help
help:
	@echo "JuhRadial MX Build System"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  build   - Build the Rust daemon (default)"
	@echo "  test    - Run unit tests"
	@echo "  fmt     - Format code with rustfmt"
	@echo "  clippy  - Run Rust linter"
	@echo "  check   - Run fmt check, clippy, and tests"
	@echo "  clean   - Clean build artifacts"
	@echo "  run     - Build and run JuhRadial MX"
	@echo "  help    - Show this help"
