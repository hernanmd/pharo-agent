---
name: tonel-class-side
kind: tonel
description: Distinguish class-side from instance-side methods
expect_class: Greeter
expect_selectors: [greeting]
expect_class_selectors: [default]
---

Write the complete Tonel source for a class `Greeter` in package `Bench-Core`,
subclassing `Object`, with:

- a class-side method `default` that returns `self new`
- an instance-side method `greeting` that returns the string 'hello'
