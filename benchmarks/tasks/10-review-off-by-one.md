---
name: review-off-by-one
kind: review
description: Spot an off-by-one in a loop bound
expect_file: src/Bench-Core/Registry.class.st
expect_keywords: [index, bound, "off-by-one", range, error]
---

Review this pull request.

Repository: bench/demo
Pull request: #2
Title: Add elementsBefore: to Registry

Diff:
```diff
diff --git a/src/Bench-Core/Registry.class.st b/src/Bench-Core/Registry.class.st
--- a/src/Bench-Core/Registry.class.st
+++ b/src/Bench-Core/Registry.class.st
@@
+{ #category : 'querying' }
+Registry >> elementsBefore: anIndex [
+
+	| result |
+	result := OrderedCollection new.
+	1 to: anIndex do: [ :each |
+		result add: (items at: each) ].
+	^ result
+]
```

`items` is an `OrderedCollection`. The method is documented as returning the
elements strictly before `anIndex`.
