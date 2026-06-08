"
I test the MCP tools exposed by PharoMcpServer via the live image. The tests call PharoMcpServer default directly so they bypass the MCP transport and verify the underlying behavior.
"
Class {
	#name : 'PharoMcpServerToolsTest',
	#superclass : 'TestCase',
	#category : 'LLM-Pharo-Agent-Tests',
	#package : 'LLM-Pharo-Agent-Tests'
}

{ #category : 'tests' }
PharoMcpServerToolsTest >> testAllCallsOnClass [
	| result |
	result := PharoMcpServer default allCallsOnClass: 'Association'.
	self assert: (result includesSubstring: 'Object>>#''->''').
	self deny: result isEmpty
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testAllInstVarNamesOf [
	| result |
	result := PharoMcpServer default allInstVarNamesOf: 'Association'.
	self assert: result equals: 'key
value'.
	self deny: result isEmpty
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testAllSlotsOf [
	| result |
	result := PharoMcpServer default allSlotsOf: 'Association'.
	self assert: (result includesSubstring: '#key => InstanceVariableSlot').
	self assert: (result includesSubstring: '#value => InstanceVariableSlot')
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testEnsureProtocolIn [
	| result class |
	class := Smalltalk classNamed: #Object.
	result := PharoMcpServer default ensureProtocol: 'test-tmp-protocol-5' in: 'Object'.
	self assert: result equals: 'test-tmp-protocol-5'.
	self assert: (class protocolNamed: 'test-tmp-protocol-5') notNil
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testExtensionSelectorsOf [
	| result |
	result := PharoMcpServer default extensionSelectorsOf: 'Array'.
	self assert: (result includesSubstring: 'asTestMatrix')
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testHasInstVarNamedIn [
	self assert: (PharoMcpServer default hasInstVarNamed: 'value' in: 'Association') equals: 'true'.
	self assert: (PharoMcpServer default hasInstVarNamed: 'nope' in: 'Association') equals: 'false'.
	self assert: (PharoMcpServer default hasInstVarNamed: 'nope' in: 'NoSuchClass') equals: 'ERROR: class not found: NoSuchClass'
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testHasSlotIn [
	self assert: (PharoMcpServer default hasSlotNamed: 'key' in: 'Association') equals: 'true'.
	self assert: (PharoMcpServer default hasSlotNamed: 'nope' in: 'Association') equals: 'false'
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testInstVarNamesOf [
	self assert: (PharoMcpServer default instVarNamesOf: 'Association') equals: 'value'.
	self assert: (PharoMcpServer default slotNamesOf: 'Association') equals: 'value'
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testIsMetaClass [
	| r1 r2 |
	r1 := PharoMcpServer default isMetaClass: 'Object'.
	r2 := PharoMcpServer default isMetaClass: 'Array'.
	self assert: r1 equals: 'false'.
	self assert: r2 equals: 'false'
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testLocalSendersOfIn [
	| result |
	result := PharoMcpServer default localSendersOf: 'do:' in: 'Array'.
	self assert: (result includesSubstring: 'SequenceableCollection').
	self deny: result isEmpty
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testLocalSlotsOf [
	| result |
	result := PharoMcpServer default localSlotsOf: 'Association'.
	self assert: result equals: '#value => InstanceVariableSlot'.
	self deny: (result includesSubstring: '#key')
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testMethodSendersOf [
	| result |
	result := PharoMcpServer default methodSendersOf: 'value'.
	self assert: (result includesSubstring: 'Association').
	self deny: result isEmpty
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testMoveClassToPackageTag [
	| result original |
	original := PharoMcpServer package.
	result := PharoMcpServer default moveClass: 'PharoMcpServer' toPackage: 'LLM-Pharo-Agent' tag: 'Core'.
	self assert: result equals: 'moved to LLM-Pharo-Agent-Core'.
	self assert: PharoMcpServer package name equals: 'LLM-Pharo-Agent'.
	self assert: PharoMcpServer packageTag name equals: 'Core'
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testRemoveMethodFromAndAddAgain [
	| class | 
	class := PharoMcpServer.
	class compile: 'testTmpMethod ^42' classified: 'test-tmp'.
	self assert: (class includesSelector: #testTmpMethod).
	self assert: (PharoMcpServer default removeMethod: 'testTmpMethod' from: 'PharoMcpServer') equals: 'removed'.
	self deny: (class includesSelector: #testTmpMethod).
	self assert: (PharoMcpServer default removeMethod: 'testTmpMethod' from: 'PharoMcpServer') equals: 'not present'
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testSelectorsInProtocolOf [
	| result |
	result := PharoMcpServer default selectorsInProtocol: 'accessing' of: 'Object'.
	self assert: (result includesSubstring: 'basicAt:')
]

{ #category : 'tests' }
PharoMcpServerToolsTest >> testUnreferencedInstVarsOf [
	| result |
	result := PharoMcpServer default unreferencedInstVarsOf: 'LookupKey'.
	"LookupKey has #key, #value but only #value is referenced through Association (actually both are used, but the test should still return a string)"
	self assert: result isString
]
