# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✓         |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Use GitHub's [private security advisory](https://github.com/Pixerova/claude-lens/security/advisories/new) feature to report vulnerabilities confidentially. This ensures the issue can be assessed and patched before public disclosure.

### What to include

A good report helps us move quickly. Please include:

- A clear description of the vulnerability and its potential impact
- Steps to reproduce (a minimal proof of concept is ideal)
- The version of claude-lens you are running
- Your macOS version and architecture (Apple Silicon or Intel)
- Any relevant logs from `~/.claude-lens/` (redact your OAuth token if present)

### What to expect

- **Acknowledgement** within 5 business days
- **Initial assessment** (confirmed / not a vulnerability / needs more info) within 10 business days
- **Patch timeline** communicated once confirmed; critical issues prioritized for next release

We follow coordinated disclosure: we ask that you allow us reasonable time to patch before publishing details publicly. In return, we will credit you in the release notes unless you prefer to remain anonymous.

## Scope

### In scope

- OAuth token storage and retrieval (macOS Keychain integration)
- The local HTTP sidecar (port 8765) — unauthorized access, request injection
- Insecure handling of session log files read from disk
- Dependency vulnerabilities with a plausible exploit path

### Out of scope

- Vulnerabilities in Anthropic's own API or Claude products
- Attacks that require physical access to the user's machine
- Social engineering
- Denial of service against the local sidecar

## Security Design Notes

For contributors and auditors, the key security boundaries in claude-lens are:

- **OAuth token** — stored exclusively in macOS Keychain via the `keyring` library; never written to disk or logged
- **External communication** — only to `api.anthropic.com` over HTTPS
- **Local IPC** — sidecar listens on `127.0.0.1:8765` only; not exposed to the network
- **Content Security Policy** — frontend is restricted to `connect-src http://localhost:8765`
- **File access** — sidecar reads session logs read-only; it writes only to `~/.claude-lens/`
