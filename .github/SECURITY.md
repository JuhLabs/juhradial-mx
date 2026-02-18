# Security Policy

## Supported Versions

We release patches for security vulnerabilities for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.2.9   | :white_check_mark: Current release |
| 0.2.x   | :white_check_mark: |
| 0.1.x   | :x: Upgrade required (critical security fixes in 0.2.1+) |
| < 0.1   | :x:                |

**Note:** JuhRadial MX is in active development. Security updates are provided for the latest release on the master branch. Always run the latest version.

### Recent Security Updates

**v0.2.9 (February 2026):**
- Fixed XWayland `dlsym` null pointer safety — all dynamically resolved X11 symbols are now null-checked before `transmute` to prevent undefined behavior
- Resolved all CodeQL unused-variable warnings (#90, #91, #92) in cursor detection code
- Removed dead assignments in exception handlers across overlay modules

**v0.2.7 (February 2026):**
- CodeQL hotfixes for code scanning alerts

**v0.2.1 (January 2026):** Critical security fixes:
- Fixed command injection vulnerability in radial menu
- Fixed insecure pairing code generation in Flow (now uses cryptographically secure randomness)
- Fixed overly permissive udev rules (MODE=0666 → 0660)
- Added input validation for D-Bus calls and HTTP endpoints

**Users on versions older than 0.2.1 should update immediately.**

## Reporting a Vulnerability

We take the security of JuhRadial MX seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### Preferred Reporting Method: Private Vulnerability Reporting

**GitHub's Private Vulnerability Reporting is the preferred method for security disclosures.**

#### How to Enable and Use Private Vulnerability Reporting:

1. **Repository Maintainers** (one-time setup):
   - Navigate to the repository Settings
   - Go to "Security" → "Code security and analysis"
   - Under "Private vulnerability reporting", click **Enable**
   - This allows security researchers to privately report vulnerabilities

2. **Security Researchers**:
   - Go to the [Security tab](https://github.com/JuhLabs/juhradial-mx/security)
   - Click **"Report a vulnerability"**
   - Fill in the vulnerability details using the private advisory draft
   - Submit the report

This creates a private security advisory that only you and the maintainers can see until it's published.

**Benefits:**
- Secure, encrypted communication
- Automatic CVE assignment (if eligible)
- Collaborative fix development
- Coordinated public disclosure

### Alternative: Email Reporting

If you prefer email or Private Vulnerability Reporting is not available:

- **Email:** [security contact - to be added by repository owner]
- **Subject Line:** `[SECURITY] Brief description of the issue`

**Please include:**
- Type of issue (e.g., buffer overflow, SQL injection, cross-site scripting, privilege escalation)
- Affected component(s) (daemon, overlay, specific file/function)
- Full paths of source file(s) related to the issue
- Location of the affected source code (tag/branch/commit or direct URL)
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit it

### What to Expect

When you report a vulnerability, we commit to:

1. **Acknowledgment:** Within 48 hours of your report
2. **Initial Assessment:** Within 5 business days, we'll provide:
   - Confirmation of the issue or request for more information
   - Our assessment of severity
   - Estimated timeline for a fix
3. **Regular Updates:** At least every 7 days on the progress toward a fix
4. **Resolution:** We aim to release a patch within:
   - **Critical vulnerabilities:** 7 days
   - **High severity:** 30 days
   - **Medium/Low severity:** 90 days
5. **Credit:** We'll acknowledge your contribution (unless you prefer to remain anonymous)

## Security Considerations for JuhRadial MX

JuhRadial MX is a Linux desktop application that:

- **Runs with user privileges** (no elevated permissions required for normal operation)
- **Communicates via D-Bus** for IPC between daemon and overlay
- **GNOME Shell extension** exposes cursor position via a session D-Bus service (`org.juhradial.CursorHelper`)
- **Dynamically loads libX11** via `dlopen`/`dlsym` for XWayland cursor detection (with null-safety checks)
- **Accesses HID devices** via hidraw (requires udev rules for user access)
- **Reads configuration** from `~/.config/juhradial/config.json`
- **Listens to keyboard events** via evdev (F19 key only)

### In-Scope Security Concerns

We particularly care about vulnerabilities that could:

- Allow privilege escalation
- Execute arbitrary code
- Access user data outside the application scope
- Cause denial of service to the system
- Bypass access controls for HID devices
- Inject malicious commands via D-Bus
- Exploit configuration parsing (JSON injection)

### Out-of-Scope

The following are generally considered out of scope:

- Vulnerabilities requiring physical access to the machine
- Social engineering attacks
- Issues in third-party dependencies (report to their maintainers)
- Theoretical vulnerabilities without proof of concept

## Dependency Security

### Automated Scanning: Dependabot

**Repository Maintainers** should enable Dependabot for automated dependency updates:

1. Navigate to repository Settings
2. Go to "Security" → "Code security and analysis"
3. Enable **Dependabot alerts**
4. Enable **Dependabot security updates**

This automatically:
- Scans Rust dependencies (Cargo.toml)
- Scans Python dependencies (requirements files)
- Creates pull requests for security updates
- Provides severity scores and vulnerability details

**Benefit:** Proactive notification and automated fixes for known CVEs in dependencies.

## Code Scanning: CodeQL

We use GitHub's CodeQL to automatically scan for security vulnerabilities:

- **Triggers:** Every push to master and all pull requests
- **Languages:** Python (overlay) and Rust (daemon)
- **Results:** Available in the [Security tab](https://github.com/JuhLabs/juhradial-mx/security/code-scanning)

CodeQL helps identify:
- SQL injection (not applicable to this project)
- Command injection
- Path traversal
- Unsafe deserialization
- Cryptographic weaknesses
- And 100+ other vulnerability patterns

## Responsible Disclosure Timeline

We follow coordinated vulnerability disclosure practices:

1. **Day 0:** Vulnerability reported privately
2. **Day 2:** Acknowledgment sent to reporter
3. **Day 5:** Initial assessment and timeline communicated
4. **Development:** Fix developed and tested (timeline varies by severity)
5. **Day X:** Security patch released
6. **Day X + 7:** Public disclosure and CVE publication (if applicable)

We request that reporters:
- Give us reasonable time to address the issue before public disclosure
- Make a good faith effort to avoid privacy violations, data destruction, or service interruption
- Do not exploit the vulnerability beyond the minimum necessary to demonstrate it

## Security Best Practices for Contributors

If you're contributing code to JuhRadial MX:

- Never commit secrets, API keys, or credentials
- Use parameterized queries for any database operations
- Validate and sanitize all user input
- Use `serde` for safe JSON deserialization in Rust
- Avoid `unwrap()` in Rust code paths that handle external input
- Follow principle of least privilege
- Review the [CONTRIBUTING.md](../CONTRIBUTING.md) for code standards

## Security Tools We Use

- **CodeQL:** Semantic code analysis (see `.github/workflows/codeql.yml`)
- **Dependabot:** Dependency vulnerability scanning
- **Cargo audit:** Rust dependency security audit (`cargo audit` in CI)
- **Clippy:** Rust linting with security-focused rules

## Contact

For general security questions or concerns (non-vulnerabilities):

- Open a [GitHub Discussion](https://github.com/JuhLabs/juhradial-mx/discussions)
- Tag with `security` label

For security vulnerabilities, **always use Private Vulnerability Reporting or direct email** as described above.

## Hall of Fame

We recognize security researchers who have responsibly disclosed vulnerabilities:

*(No vulnerabilities reported yet)*

---

**Thank you for helping keep JuhRadial MX and its users safe!**
