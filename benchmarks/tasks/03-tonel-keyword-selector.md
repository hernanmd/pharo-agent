---
name: tonel-keyword-selector
kind: tonel
description: Write a multi-keyword selector correctly
expect_class: Registry
expect_selectors: ["at:put:", "initialize"]
---

Write the complete Tonel source for a class `Registry` in package `Bench-Core`,
subclassing `Object`, with one instance variable `items`, and:

- an instance-side method `initialize` that sets `items` to a new `Dictionary`
- an instance-side method `at: aKey put: aValue` that stores the value in `items`
  and returns the value
