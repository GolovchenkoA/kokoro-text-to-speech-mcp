# TODO: Make my local MCP server installable without editing claude_desktop_config.json

## Question

I added my local MCP server to Claude Code using `claude_desktop_config.json`, which is not user friendly.
What should be done to be able to add the MCP server using **Connectors** and/or **Plugins** settings?

## Answer (summary)

Because the server is **local (stdio)**, there are three options. Which one fits depends on where it should show up:

| Option | Where it appears | Works for local server? | Reach |
|---|---|---|---|
| Desktop Extension (`.mcpb`) | Settings → Extensions | Yes | Claude Desktop only |
| Plugin (with `.mcp.json`) | Plugins / `/plugin` | Yes | Claude Desktop and Claude Code; shareable through a marketplace |
| Custom connector | Settings → Connectors | No. Needs a public HTTPS remote server | Web, desktop and mobile |

**Recommendation:** build a `.mcpb` for one-click installs in Claude Desktop. Build a **plugin** if you want it under Plugins, want to share it, or want to bundle it with skills or commands.

---

## Option 1: Package as a Desktop Extension (.mcpb)

An `.mcpb` is a zip archive with your local MCP server and a `manifest.json`. Claude Desktop installs it in one click, the way a browser installs an extension.

- [ ] Install the CLI: `npm install -g @anthropic-ai/mcpb`
- [ ] In the server's folder, run `mcpb init` to generate `manifest.json` (command, args, env, user-config fields such as API keys and paths)
- [ ] Run `mcpb pack` to build the `.mcpb` file
- [ ] Install it one of these ways:
  - double-click the `.mcpb`, or
  - drag and drop it into the Claude Desktop window, or
  - Settings → Extensions → Advanced settings → Install Extension… → select the file
- [ ] Check that it appears under Settings → Extensions and its tools work

Notes:
- Privately distributed extensions are **not** auto-updated. Users reinstall new `.mcpb` files by hand.
- The directory no longer accepts MCPB submissions. To publish, use a plugin instead.

## Option 2: Wrap it in a plugin (shows up in Plugins settings)

Plugins can bundle MCP servers in `.mcp.json` at the plugin root, or inline in `plugin.json`. The format is the same `mcpServers` block as in `claude_desktop_config.json`.

- [ ] Create the plugin structure:
  ```
  my-plugin/
  ├── .claude-plugin/plugin.json   # name, version, description
  ├── .mcp.json                    # server config
  └── servers/...                  # server code (optional)
  ```
- [ ] Move the `mcpServers` entry from `claude_desktop_config.json` into `.mcp.json`
- [ ] Replace absolute paths with `${CLAUDE_PLUGIN_ROOT}/...`
- [ ] Test locally: `claude --plugin-dir ./my-plugin`, then run `/mcp` to confirm the server is listed
- [ ] Create a marketplace: a git repo containing `.claude-plugin/marketplace.json` that lists the plugin
- [ ] Push it to GitHub or another git host
- [ ] Install: `/plugin marketplace add owner/repo`, then `/plugin install my-plugin@my-marketplace`
- [ ] (Optional) Add skills or commands to the same plugin

Example `.mcp.json`:
```json
{
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["${CLAUDE_PLUGIN_ROOT}/servers/index.js"],
      "env": { "API_KEY": "..." }
    }
  }
}
```

## Option 3: Custom connector (only if needed on web or mobile)

Settings → Connectors → Add custom connector takes **only a remote server URL**. Claude connects from Anthropic's cloud, not from your computer, so the server must be publicly reachable.

- [ ] Add Streamable HTTP transport to the server
- [ ] Host it at a public HTTPS URL (add OAuth for auth)
- [ ] Settings → Connectors → Add custom connector → paste the URL
- [ ] Turn it on in a chat with **+ → Connectors**

## Claude Code specifically

Claude Code doesn't read `claude_desktop_config.json`. Instead:

- [ ] Add the server from the terminal: `claude mcp add <name> -- <command> <args>`, or
- [ ] Import the existing Claude Desktop config: `claude mcp add-from-claude-desktop`

---

## Sources

- [Getting Started with Local MCP Servers on Claude Desktop](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
- [Build an MCPB – Claude docs](https://claude.com/docs/connectors/building/mcpb)
- [Claude Code plugins reference](https://code.claude.com/docs/en/plugins-reference)
- [Custom connectors via remote MCP](https://claude.com/docs/connectors/custom/remote-mcp.md)
- [MCPB repository](https://github.com/modelcontextprotocol/mcpb)
