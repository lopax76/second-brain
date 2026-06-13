# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Instead, use GitHub's private vulnerability reporting:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe the issue, how to reproduce it, and the impact.

You can expect an initial acknowledgement within a few days. Once a fix is available, we will
coordinate a disclosure timeline with you.

## Scope and threat model

Second Brain is a **local, read-only** tool with **no runtime dependencies** in its core and
**no network access**: it indexes files on disk and writes a derived graph under
`.secondbrain/`. It does not send data anywhere.

Areas where security reports are especially relevant:

- **Viewer output (`view.html`).** The graph data is inlined into an HTML page. We escape it
  so project content cannot break out of its `<script type="application/json">` block or
  inject markup. Reports of escaping/XSS gaps here are in scope.
- **Path handling.** The indexer reads files under the project root. Reports of path traversal
  or following symlinks outside the root are in scope.
- **The optional MCP server.** It exposes read-only queries over stdio. Reports of it exposing
  file contents or escaping the project boundary are in scope.

## Supported versions

The project is in early development (0.x); fixes are applied to the latest `main`.
