---
name: review-nil-guard
kind: review
description: Spot an uninitialised instance variable used in arithmetic
expect_file: src/Bench-Core/Counter.class.st
expect_keywords: [nil, initialize]
---

Review this pull request.

Repository: bench/demo
Pull request: #1
Title: Add increment to Counter

Diff:
```diff
diff --git a/src/Bench-Core/Counter.class.st b/src/Bench-Core/Counter.class.st
--- a/src/Bench-Core/Counter.class.st
+++ b/src/Bench-Core/Counter.class.st
@@
 Class {
 	#name : 'Counter',
 	#superclass : 'Object',
 	#instVars : [
 		'count'
 	],
 	#category : 'Bench-Core',
 	#package : 'Bench-Core'
 }
+
+{ #category : 'operations' }
+Counter >> increment [
+
+	count := count + 1.
+	^ count
+]
```

The class has no `initialize` method anywhere in the package.
