# HOWTO: Configuring MCP Clients (Claude, Warp, Gemini, VS Code) for Hath0r-MCP

This guide provides step-by-step instructions to configure **Hath0r-MCP** in your favorite AI development tools and environments: **Claude (Desktop & Code)**, **Warp**, **Gemini (Antigravity & CLI)**, and **VS Code (Roo Code, Cline, Continue, GitHub Copilot)**.

---

## 1. Service Endpoints & Health Check

Hath0r-MCP runs as a FastMCP Streamable HTTP server. Ensure the container or native server is running:

| Property | Value |
|---|---|
| **Canonical Cloud URL** | `https://mcp.hath0r-cli.com` |
| **MCP Endpoint** | `https://mcp.hath0r-cli.com/mcp` |
| **Health Probe** | `https://mcp.hath0r-cli.com/health` |
| **Readiness Probe** | `https://mcp.hath0r-cli.com/ready` |
| **Protocol** | Streamable HTTP (FastMCP) / JSON-RPC 2.0 |
| **Local Docker (dev)** | `http://127.0.0.1:38083` (container port 8083) |

### Verify Service Health
```bash
# Check health probe
curl -fsS https://mcp.hath0r-cli.com/health

# Verify tools via Hath0r CLI
hath0r mcp check
```

Expected response: `{"status":"healthy","service":"hath0r-mcp"}`

---

## 2. Claude Setup

### A. Claude Desktop (macOS)
Claude Desktop configuration is stored at:
`~/Library/Application Support/Claude/claude_desktop_config.json`

Add the `hath0r-mcp` entry under `mcpServers`:

```json
{
  "mcpServers": {
    "hath0r-mcp": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://mcp.hath0r-cli.com/mcp"
      ]
    }
  }
}
```

*Alternative (Direct Python stdio mode inside the repository):*
```json
{
  "mcpServers": {
    "hath0r-mcp": {
      "command": "/Users/raybayly/Development/OpenSource/hath0r-mcp/.venv/bin/python",
      "args": [
        "-m",
        "knowledgebase.cli.main"
      ],
      "cwd": "/Users/raybayly/Development/OpenSource/hath0r-mcp"
    }
  }
}
```

### B. Claude Code (CLI)
Add Hath0r-MCP directly to Claude Code CLI:
```bash
claude mcp add --transport http hath0r-mcp https://mcp.hath0r-cli.com/mcp
```

Verify connection in Claude:
Ask Claude: `"Use suite_info tool from hath0r-mcp to list available knowledge documents."`

---

## 3. Warp Terminal Setup

Warp integrates Model Context Protocol servers natively to enrich terminal AI commands and agent workflows.

### Warp Configuration (`~/.warp/mcp_servers.json`)
Open or create `~/.warp/mcp_servers.json`:

```json
{
  "mcpServers": {
    "hath0r-mcp": {
      "url": "https://mcp.hath0r-cli.com/mcp"
    }
  }
}
```

*Or configure via Warp UI:*
1. Open Warp **Settings** (`Cmd + ,`).
2. Navigate to **AI** > **MCP Servers**.
3. Click **Add Server**:
   - **Name**: `hath0r-mcp`
   - **URL / Endpoint**: `https://mcp.hath0r-cli.com/mcp`
4. Click **Save** and verify the status indicator shows active.

---

## 4. Google Gemini & Antigravity Setup

### A. Google Antigravity IDE
Antigravity discovers MCP servers declared in the user or workspace configuration:
`~/.gemini/antigravity/settings.json` or `.gemini/settings.json`:

```json
{
  "mcpServers": {
    "hath0r-mcp": {
      "url": "https://mcp.hath0r-cli.com/mcp"
    }
  }
}
```

### B. Gemini CLI / Extensions
For Gemini CLI integrations:
```bash
gemini mcp add hath0r-mcp https://mcp.hath0r-cli.com/mcp
```

---

## 5. VS Code Setup

VS Code supports MCP via multiple AI agent extensions: **Roo Code**, **Cline**, **Continue**, and **GitHub Copilot**.

### A. Roo Code / Cline
In VS Code, open the extension settings (or edit `~/Library/Application Support/Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json`):

```json
{
  "mcpServers": {
    "hath0r-mcp": {
      "url": "https://mcp.hath0r-cli.com/mcp",
      "transport": "streamable-http",
      "autoApprove": [
        "suite_info",
        "kb_search",
        "kb_get_document"
      ]
    }
  }
}
```

### B. Continue Extension (`~/.continue/config.json`)
Add under `experimental.modelContextProtocolServers`:

```json
{
  "experimental": {
    "modelContextProtocolServers": [
      {
        "transport": {
          "type": "http",
          "url": "https://mcp.hath0r-cli.com/mcp"
        }
      }
    ]
  }
}
```

### C. Workspace-level `.vscode/mcp.json`
Create `.vscode/mcp.json` in the root of your project:

```json
{
  "servers": {
    "hath0r-mcp": {
      "type": "http",
      "url": "https://mcp.hath0r-cli.com/mcp"
    }
  }
}
```

---

## 6. Available Tools in Hath0r-MCP

Once connected, your AI assistant will have access to:
1. `suite_info()`: Returns suite metadata, ATC control tower reference, and all bundled reference document IDs.
2. `kb_search(query, limit=5)`: Case-insensitive lexical word search across reference docs.
3. `kb_get_document(document_id)`: Safe document content retrieval by document ID.
