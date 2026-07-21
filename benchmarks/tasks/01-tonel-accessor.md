---
name: tonel-accessor
kind: tonel
description: Write a minimal Tonel class with one accessor
expect_class: Counter
expect_superclass: Object
expect_selectors: [count]
---

Write the complete Tonel source for a class `Counter` in package `Bench-Core`.

It subclasses `Object`, has one instance variable `count`, and one instance-side
method in the `accessing` protocol called `count` that returns the instance
variable.
