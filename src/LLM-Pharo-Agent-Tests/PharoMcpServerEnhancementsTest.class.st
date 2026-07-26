Class {
	#name : 'PharoMcpServerEnhancementsTest',
	#superclass : 'TestCase',
	#instVars : [
		'server',
		'mcp'
	],
	#category : 'LLM-Pharo-Agent-Tests',
	#package : 'LLM-Pharo-Agent-Tests'
}

{ #category : 'running' }
PharoMcpServerEnhancementsTest >> setUp [
	super setUp.
	server := PharoMcpServer new.
	server class readOnlyMode: false.
	mcp := McpServer name: MCPConstants mcpServerName version: MCPConstants mcpServerVersion.
	mcp maxResultBytes: server class maxResultBytesDefault.
	server instVarNamed: 'server' put: mcp.
	server registerToolsOn: mcp.
	server registerDiscoveryToolsOn: mcp.
	server registerRemoveMethodSideToolOn: mcp.
	server applyReadOnlyGateOn: mcp
]

{ #category : 'running' }
PharoMcpServerEnhancementsTest >> tearDown [
	server class readOnlyMode: false.
	server class maxResultBytesDefault: nil.
	super tearDown
]

{ #category : 'tests' }
PharoMcpServerEnhancementsTest >> testBooleanFromRecognizesSideEnum [
	"Locks the fix for the pharo_compile_method side: 'class' bug.
	 The 'side' enum must coerce to a boolean so class-side compilation lands
	 on the metaclass instead of silently compiling on the instance side."
	| s |
	s := PharoMcpServer new.
	self assert: (s booleanFrom: 'class' default: false).
	self assert: (s booleanFrom: 'classSide' default: false).
	self deny: (s booleanFrom: 'instance' default: true).
	self deny: (s booleanFrom: 'instanceSide' default: true).
	"legacy boolean spellings still work"
	self assert: (s booleanFrom: 'true' default: false).
	self deny: (s booleanFrom: 'false' default: true).
	self assert: (s booleanFrom: nil default: true).
	self assert: (s booleanFrom: true default: false)
]

{ #category : 'tests' }
PharoMcpServerEnhancementsTest >> testCompileMethodToolSideClassLandsOnMetaclass [
	"End-to-end: invoking pharo_compile_method with side: 'class' must compile on
	 the metaclass. Regression guard for the root-cause fix in booleanFrom:default:."
	| target params result text |
	target := self class name asString.
	(self class class includesSelector: #zzSideProbe3) ifTrue: [ self class class removeSelector: #zzSideProbe3 ].
	params := Dictionary new
		at: 'name' put: 'pharo_compile_method';
		at: 'arguments' put: (Dictionary new
			at: 'className' put: target;
			at: 'selector' put: 'zzSideProbe3';
			at: 'sourceCode' put: 'zzSideProbe3
	^ 7';
			at: 'protocol' put: 'testing';
			at: 'side' put: 'class';
			yourself);
		yourself.
	result := mcp handleToolsCall: (McpJsonRpcRequest id: 1 method: 'tools/call' params: params).
	text := (result result at: 'content') first at: 'text'.
	self deny: (text asString includesSubstring: 'ERROR') description: 'compile should succeed, got: ' , text asString.
	self assert: (self class class includesSelector: #zzSideProbe3) description: 'method must be on the metaclass (class side)'.
	self deny: (self class includesSelector: #zzSideProbe3) description: 'method must NOT be on the instance side'.
	self assert: (self class perform: #zzSideProbe3) equals: 7.
	(self class class includesSelector: #zzSideProbe3) ifTrue: [ self class class removeSelector: #zzSideProbe3 ]
]

{ #category : 'tests' }
PharoMcpServerEnhancementsTest >> testDestructiveToolRunsWhenReadOnlyDisabled [
	| result params |
	server class readOnlyMode: false.
	params := Dictionary new at: 'name' put: 'pharo_eval'; at: 'arguments' put: (Dictionary new at: 'code' put: '6 * 7'; yourself); yourself.
	result := mcp handleToolsCall: (McpJsonRpcRequest id: 1 method: 'tools/call' params: params).
	self deny: (result result at: 'isError' ifAbsent: [ false ]).
	self assert: (((result result at: 'content') first at: 'text') includesSubstring: '42')
]

{ #category : 'tests' }
PharoMcpServerEnhancementsTest >> testMaxResultBytesDefaultBounded [
	| result params text |
	mcp maxResultBytes: 500.
	params := Dictionary new at: 'name' put: 'pharo_eval'; at: 'arguments' put: (Dictionary new at: 'code' put: '(String new: 5000 withAll: $x)'; yourself); yourself.
	result := mcp handleToolsCall: (McpJsonRpcRequest id: 1 method: 'tools/call' params: params).
	text := (result result at: 'content') first at: 'text'.
	self assert: text size <= 700.
	self assert: (text includesSubstring: 'truncated from')
]

{ #category : 'tests' }
PharoMcpServerEnhancementsTest >> testReadOnlyGateAllowsReadTool [
	| result params |
	server class readOnlyMode: true.
	params := Dictionary new at: 'name' put: 'pharo_class_source'; at: 'arguments' put: (Dictionary new at: 'className' put: 'Object'; yourself); yourself.
	result := mcp handleToolsCall: (McpJsonRpcRequest id: 1 method: 'tools/call' params: params).
	self deny: (result result at: 'isError' ifAbsent: [ false ]).
	self assert: (((result result at: 'content') first at: 'text') includesSubstring: 'Object')
]

{ #category : 'tests' }
PharoMcpServerEnhancementsTest >> testReadOnlyGateBlocksDestructiveTool [
	| result params |
	server class readOnlyMode: true.
	params := Dictionary new at: 'name' put: 'pharo_compile_method'; at: 'arguments' put: Dictionary new; yourself.
	result := mcp handleToolsCall: (McpJsonRpcRequest id: 1 method: 'tools/call' params: params).
	self assert: (result result at: 'isError' ifAbsent: [ false ]).
	self assert: (((result result at: 'content') first at: 'text') includesSubstring: 'Read-only mode')
]

{ #category : 'tests' }
PharoMcpServerEnhancementsTest >> testRemoveMethodDefaultsToInstanceSide [
	"Without side, pharo_remove_method removes the instance-side method and leaves
	 any class-side method of the same name untouched."
	| target params result |
	target := self class name asString.
	(self class includesSelector: #zzRemoveProbeIS) ifTrue: [ self class removeSelector: #zzRemoveProbeIS ].
	(self class class includesSelector: #zzRemoveProbeIS) ifTrue: [ self class class removeSelector: #zzRemoveProbeIS ].
	self class compile: 'zzRemoveProbeIS
	^ 5' classified: 'testing'.
	self class class compile: 'zzRemoveProbeIS
	^ 5' classified: 'testing'.
	self assert: (self class includesSelector: #zzRemoveProbeIS).
	self assert: (self class class includesSelector: #zzRemoveProbeIS).
	params := Dictionary new
		at: 'name' put: 'pharo_remove_method';
		at: 'arguments' put: (Dictionary new
			at: 'className' put: target;
			at: 'selector' put: 'zzRemoveProbeIS';
			yourself);
		yourself.
	result := mcp handleToolsCall: (McpJsonRpcRequest id: 1 method: 'tools/call' params: params).
	self deny: (result result at: 'isError' ifAbsent: [ false ]).
	self assert: ((result result at: 'content') first at: 'text') equals: 'removed'.
	self deny: (self class includesSelector: #zzRemoveProbeIS) description: 'instance-side method should be removed'.
	self assert: (self class class includesSelector: #zzRemoveProbeIS) description: 'class-side method of same name must be untouched'.
	(self class class includesSelector: #zzRemoveProbeIS) ifTrue: [ self class class removeSelector: #zzRemoveProbeIS ].
	(self class includesSelector: #zzRemoveProbeIS) ifTrue: [ self class removeSelector: #zzRemoveProbeIS ]
]

{ #category : 'tests' }
PharoMcpServerEnhancementsTest >> testRemoveMethodSideClassRemovesMetaclassMethod [
	| target params result |
	target := self class name asString.
	(self class class includesSelector: #zzRemoveProbeCS) ifTrue: [ self class class removeSelector: #zzRemoveProbeCS ].
	self class class compile: 'zzRemoveProbeCS
	^ 5' classified: 'testing'.
	self assert: (self class class includesSelector: #zzRemoveProbeCS).
	params := Dictionary new
		at: 'name' put: 'pharo_remove_method';
		at: 'arguments' put: (Dictionary new
			at: 'className' put: target;
			at: 'selector' put: 'zzRemoveProbeCS';
			at: 'side' put: 'class';
			yourself);
		yourself.
	result := mcp handleToolsCall: (McpJsonRpcRequest id: 1 method: 'tools/call' params: params).
	self deny: (result result at: 'isError' ifAbsent: [ false ]).
	self assert: ((result result at: 'content') first at: 'text') equals: 'removed'.
	self deny: (self class class includesSelector: #zzRemoveProbeCS).
	(self class class includesSelector: #zzRemoveProbeCS) ifTrue: [ self class class removeSelector: #zzRemoveProbeCS ]
]

{ #category : 'tests' }
PharoMcpServerEnhancementsTest >> testToolGetReturnsFullSchema [
	| result params text |
	params := Dictionary new at: 'name' put: 'pharo_tool_get'; at: 'arguments' put: (Dictionary new at: 'name' put: 'pharo_eval'; yourself); yourself.
	result := mcp handleToolsCall: (McpJsonRpcRequest id: 1 method: 'tools/call' params: params).
	self deny: (result result at: 'isError' ifAbsent: [ false ]).
	text := (result result at: 'content') first at: 'text'.
	self assert: (text includesSubstring: 'pharo_eval').
	self assert: (text includesSubstring: 'code')
]

{ #category : 'tests' }
PharoMcpServerEnhancementsTest >> testToolSearchReturnsMatchingTools [
	| result params text |
	params := Dictionary new at: 'name' put: 'pharo_tool_search'; at: 'arguments' put: (Dictionary new at: 'query' put: 'compile'; yourself); yourself.
	result := mcp handleToolsCall: (McpJsonRpcRequest id: 1 method: 'tools/call' params: params).
	self deny: (result result at: 'isError' ifAbsent: [ false ]).
	text := (result result at: 'content') first at: 'text'.
	self deny: (text includesSubstring: 'No tools matched').
	self assert: (text includesSubstring: 'pharo_compile_method')
]
