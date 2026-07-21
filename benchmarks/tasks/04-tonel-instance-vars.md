---
name: tonel-instance-vars
kind: tonel
description: Class with several instance variables and an initialize
expect_class: Connection
expect_selectors: [initialize, host, port]
---

Write the complete Tonel source for a class `Connection` in package `Bench-Core`,
subclassing `Object`, with instance variables `host` and `port`, an `initialize`
method setting host to 'localhost' and port to 4044, and accessors `host` and
`port`.
