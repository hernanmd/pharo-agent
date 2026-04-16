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

