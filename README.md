# PharoAgent

[![Pharo 13 & 14](https://img.shields.io/badge/Pharo-13%20%7C%2014-2c98f0.svg)](https://github.com/pharo-llm/pharo-agent)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/pharo-llm/pharo-agent/blob/master/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/pharo-llm/pharo-agent/pulls)
[![Status: Active](https://img.shields.io/badge/status-active-success.svg)](https://github.com/pharo-llm/pharo-agent)
[![CI](https://github.com/pharo-llm/chatpharo/actions/workflows/CI.yml/badge.svg)](https://github.com/pharo-llm/pharo-agent/actions/workflows/CI.yml)


PharoAgent is a lightweight TCP server for Pharo that lets external tools send Smalltalk snippets for evaluation and trigger browser navigation commands.

To install stable version of `PharoAgent` in your image you can use:

```smalltalk
Metacello new
  githubUser: 'pharo-llm' project: 'pharo-agent' commitish: 'X.X.X' path: 'src';
  baseline: 'LLMPharoAgent';
  load
```


For development version install it with this:

```smalltalk
Metacello new
  githubUser: 'pharo-llm' project: 'pharo-agent' commitish: 'main' path: 'src';
  baseline: 'LLMPharoAgent';
  load.
```

## Start the agent

In the Playground, run:

```smalltalk
PharoAgent start
````

To use a custom port:

```smalltalk
PharoAgent startOn: 4044
```

## Restart cleanly

If you reloaded the class and want a fresh restart, run:

```smalltalk
PharoAgent stop.
PharoAgent resetDefault.
PharoAgent start
```

## Evaluate an expression

```bash
echo "3 + 4" | nc localhost 4044
```

Expected output:

```text
7
```

## Open a class browser

```bash
echo "OPEN_CLASS_BROWSER String" | nc localhost 4044
```


## Talk to the live image from Claude Code, Codex, or Qwen (MCP)

PharoAgent ships with an MCP server (`LLM-Pharo-MCP`) that exposes the running
image over HTTP so CLI agents like [Claude Code](https://claude.com/claude-code),
Codex, or Qwen Code can talk directly to it — evaluate Smalltalk, open browsers,
read class and method source, create classes, and compile methods — without
spawning a fresh headless Pharo per call.

### Start the MCP server

In a Playground:

```smalltalk
PharoAgent startMcp.
"or on a custom port"
PharoAgent startMcpOn: 4046.
```

The server listens on `http://localhost:4046/mcp` by default. Override with the
`PHARO_MCP_PORT` environment variable before launching the image.

To stop it:

```smalltalk
PharoAgent stopMcp.
```

### Configure your CLI agent

The repo ships a ready-to-use `.mcp.json` at the root:

```json
{
  "mcpServers": {
    "pharo": {
      "type": "http",
      "url": "http://localhost:4046/mcp"
    }
  }
}
```

Claude Code picks it up automatically when started from the repo root. For
Codex, Qwen or any other MCP-speaking client, point its MCP config at the same
URL.

### Registered tools

| Tool                         | Description                                                   |
| ---------------------------- | ------------------------------------------------------------- |
| `pharo_eval`                 | Evaluate a Smalltalk expression, returns its `printString`    |
| `pharo_open_class_browser`   | Open a System Browser on the given class                      |
| `pharo_open_method_browser`  | Open a System Browser on `ClassName>>selector`                |
| `pharo_class_source`         | Return the class definition and its selector list             |
| `pharo_method_source`        | Return the source of a single method                          |
| `pharo_create_class`         | Create a class in the live image                              |
| `pharo_compile_method`       | Compile an instance-side or class-side method                 |

### Registered resources

| URI                                       | Description                             |
| ----------------------------------------- | --------------------------------------- |
| `pharo://system/info`                     | Pharo version, package count, image path |
| `pharo://class/{className}`               | Class definition + method list          |
| `pharo://method/{className}/{selector}`   | Source of a single method               |

### Example terminal-driven edits

Once the MCP server is running, a connected terminal agent can ask Pharo to do
real image edits such as:

- create `MyCounter` as a subclass of `Object` in package `Demo-Core`
- compile `value ^ 42` on `MyCounter`
- compile `default ^ self new` on the class side of `MyCounter`
