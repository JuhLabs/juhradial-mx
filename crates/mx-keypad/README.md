# mx-keypad

An independent protocol crate owned and maintained by Julian Hermstad, licensed
under MIT OR Apache-2.0. It is separate from the GPL-3.0 daemon that consumes it.
Dependencies are limited to std and libc. Linux hidraw access needs input-group
permissions, not elevated privileges.

Protocol details follow the owner's measured 046d:c354 device and Julusian's
MIT-licensed `@logitech-mx-creative-console/core` 0.2.x reference (imageWriter,
mx-creative-keypad input and model). The implementation is original Rust.

Keys are numbered 1 through 9. `KeyWindow::new` gives their 118x118 panel windows.
`image_packets` accepts JPEG bytes without decoding them. Control builders do not
write anything. The brightness builder is unused: persistence has not been measured.

From the repository root:

```sh
cargo test --offline --manifest-path crates/mx-keypad/Cargo.toml
cargo clippy --offline --manifest-path crates/mx-keypad/Cargo.toml
cargo run --offline --manifest-path crates/mx-keypad/Cargo.toml --example probe -- 30
```

Run the probe only when another keypad driver is not using this device. It prints
the selected node, initializes the device, paints red/green/blue columns, prints
key down/up and page-button events for 30 seconds, and resets to the logo. Let the
timer expire to ensure the reset runs. An I/O failure also attempts the reset.
The probe does not change brightness. Test fixtures are tiny solid-colour JPEGs.
