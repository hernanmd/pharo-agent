Class {
	#name : 'PharoMcpServerTest',
	#superclass : 'TestCase',
	#instVars : [
		'server',
		'generatedClassName',
		'generatedPackageName'
	],
	#category : 'LLM-Pharo-Agent-Tests',
	#package : 'LLM-Pharo-Agent-Tests'
}

{ #category : 'running' }
PharoMcpServerTest >> setUp [

	super setUp.
	server := PharoMcpServer new.
	generatedClassName := 'PharoMcpServerGeneratedTestClass'.
	generatedPackageName := 'LLM-Pharo-Agent-Generated-Tests'.
	self removeGeneratedArtifacts
]

{ #category : 'running' }
PharoMcpServerTest >> tearDown [

	self removeGeneratedArtifacts.
	super tearDown
]

{ #category : 'private' }
PharoMcpServerTest >> generatedClass [

	^ Smalltalk globals at: generatedClassName asSymbol ifAbsent: [ nil ]
]

{ #category : 'private' }
PharoMcpServerTest >> removeGeneratedArtifacts [

	(Smalltalk globals includesKey: generatedClassName asSymbol) ifTrue: [
		server mutateImageDuring: [
			(Smalltalk globals at: generatedClassName asSymbol) removeFromSystem ] ].
	(PackageOrganizer default hasPackage: generatedPackageName) ifTrue: [
		server mutateImageDuring: [
			PackageOrganizer default removePackage: generatedPackageName ] ]
]

{ #category : 'running' }
PharoMcpServerTest >> testCompileMethodSourceCreatesClassSideMethod [

	| behavior |
	server
		createClassNamed: generatedClassName
		superclassName: 'Object'
		packageName: generatedPackageName
		tag: nil
		instanceVariables: nil
		classVariables: nil.

	server
		compileMethodSource: 'answer ^ 42'
		forClassNamed: generatedClassName
		protocol: 'testing'
		classSide: true.

	behavior := self generatedClass classSide.
	self assert: (behavior includesSelector: #answer).
	self assert: (behavior perform: #answer) equals: 42
]

{ #category : 'running' }
PharoMcpServerTest >> testCompileMethodSourceCreatesInstanceSideMethod [

	| instance behavior |
	server
		createClassNamed: generatedClassName
		superclassName: 'Object'
		packageName: generatedPackageName
		tag: nil
		instanceVariables: nil
		classVariables: nil.

	server
		compileMethodSource: 'value ^ 41'
		forClassNamed: generatedClassName
		protocol: 'testing'
		classSide: false.

	behavior := self generatedClass.
	self assert: (behavior includesSelector: #value).
	instance := behavior new.
	self assert: instance value equals: 41
]

{ #category : 'running' }
PharoMcpServerTest >> testCreateClassNamedCreatesClassAndPackage [

	| createdClass result |
	result := server
		          createClassNamed: generatedClassName
		          superclassName: 'Object'
		          packageName: generatedPackageName
		          tag: nil
		          instanceVariables: 'left right'
		          classVariables: 'Counter'.

	createdClass := self generatedClass.
	self assert: result equals: 'Created class ', generatedClassName, ' in package ', generatedPackageName.
	self assert: createdClass notNil.
	self assert: createdClass superclass equals: Object.
	self assert: createdClass package name equals: generatedPackageName.
	self assert: (createdClass slots collect: [ :slot | slot name ]) equals: #( 'left' 'right' ).
	self assert: createdClass classVarNames asArray equals: #( 'Counter' )
]

{ #category : 'running' }
PharoMcpServerTest >> testNormalizedNamesFromStringSupportsSpacesAndCommas [

	self
		assert: (server normalizedNamesFrom: ' first, second  third ')
		equals: #( 'first' 'second' 'third' )
]
