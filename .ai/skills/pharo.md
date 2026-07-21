---
name: pharo
description: How to read, write, and verify Pharo Smalltalk code in this repository
when:
  - "src/**/*.st"
  - "**/*.class.st"
  - "**/BaselineOf*/**"
tools:
  - pharo_eval
  - pharo_class_source
  - pharo_method_source
priority: 10
---

## The image is the source of truth, not your memory

You have a live Pharo image. Smalltalk is a small fraction of what you were
trained on, and the class library is enormous. Assume you will get selectors
wrong, and check.

Before you use any selector you have not seen in this repository:

```
pharo_class_source(className: "OrderedCollection")
```

That returns the real selector list. If the selector you had in mind is not in
it, you were about to hallucinate a method. Find the real one.

To check behaviour rather than existence, evaluate it:

```
pharo_eval(code: "(OrderedCollection withAll: #(3 1 2)) asSortedCollection asArray")
```

`pharo_eval` returns the `printString` of the result, or the exception class and
message if it raised. An exception is useful information — it tells you the code
you were about to commit does not work.

## Tonel file format

Source lives in `src/<PackageName>/<ClassName>.class.st`. The format is strict
and a malformed file will not load into an image. The controller runs a Tonel
parser over every changed `.st` file and will refuse to open a PR if it fails.

A class file is a metadata block followed by method chunks:

```smalltalk
Class {
	#name : 'MyClass',
	#superclass : 'Object',
	#instVars : [ 'count' ],
	#category : 'My-Package',
	#package : 'My-Package'
}

{ #category : 'accessing' }
MyClass >> count [

	^ count
]

{ #category : 'accessing' }
MyClass class >> defaultCount [

	^ 0
]
```

Rules that are easy to get wrong:

- Every method needs its own `{ #category : '...' }` chunk header directly above it.
- The receiver before `>>` must match `#name` exactly. Class-side methods use
  `MyClass class >> selector`.
- Both `#category` and `#package` are expected on a class definition.
- Strings are single-quoted and an embedded quote is doubled: `'it''s'`.
- Comments are double-quoted and an embedded double quote is doubled.
- Indentation is tabs, matching the surrounding file.

Package directories also contain a `package.st` holding `Package { #name : '...' }`.

## Tests

Tests live in `src/<PackageName>-Tests/` as subclasses of `TestCase`, one test
class per class under test, named `<ClassName>Test`. Test methods start with
`test` and take no arguments:

```smalltalk
{ #category : 'tests' }
MyClassTest >> testCountStartsAtZero [

	self assert: MyClass new count equals: 0
]
```

Use `assert:equals:` rather than `assert:` on an equality expression — the
failure message is far more useful.

When you change behaviour, update or add the matching test in the `-Tests`
package. A change with no test change should be a deliberate choice you can
justify, not an oversight.

## BaselineOf is high risk

`src/BaselineOf<Project>/BaselineOf<Project>.class.st` declares packages and
external dependencies. Editing it changes what loads for every consumer of this
repository. Do not touch it unless the task is explicitly about dependencies or
packaging, and say so clearly in your summary if you do.

## Before you finish

Re-read the whole method you wrote and check, against the image:

1. Every selector you send exists on the receiver's class.
2. Every global (class name) you reference exists — `pharo_eval(code: "Smalltalk includesKey: #MyClass")`.
3. Cascades (`;`) send to the same receiver you think they do.
4. `^` returns are present where the caller needs a value.
