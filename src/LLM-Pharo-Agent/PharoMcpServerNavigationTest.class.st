Class {
	#name : 'PharoMcpServerNavigationTest',
	#superclass : 'TestCase',
	#instVars : [
		'server'
	],
	#category : 'LLM-Pharo-Agent-Tests',
	#package : 'LLM-Pharo-Agent',
	#tag : 'Tests'
}

{ #category : 'running' }
PharoMcpServerNavigationTest >> setUp [
	super setUp.
	server := PharoMcpServer new.
	server flushSendersCache
]

{ #category : 'running' }
PharoMcpServerNavigationTest >> tearDown [
	server ifNotNil: [ server flushSendersCache ].
	super tearDown
]

{ #category : 'tests' }
PharoMcpServerNavigationTest >> testHeaderReportsTrueTotalIndependentOfPage [
	| full paged fullTotal |
	full := server methodSendersOf: 'add:'.
	fullTotal := (full lines first substrings: ' ') second asNumber.
	paged := server methodSendersOf: 'add:' offset: 0 limit: 3.
	self assert: ((paged lines first substrings: ' ') second asNumber) equals: fullTotal.
	"paged body has at most 3 rows (plus the header line)"
	self assert: paged lines size <= 4
]

{ #category : 'tests' }
PharoMcpServerNavigationTest >> testOffsetBeyondEndYieldsHeaderOnly [
	| result |
	result := server methodSendersOf: 'add:' offset: 10000000 limit: 5.
	self assert: (result lines first beginsWith: '# ').
	self assert: result lines size equals: 1
]

{ #category : 'tests' }
PharoMcpServerNavigationTest >> testPagingIsDeterministicAndContiguous [
	| page1 page2 both direct |
	page1 := (server methodSendersOf: 'add:' offset: 0 limit: 5) lines allButFirst.
	page2 := (server methodSendersOf: 'add:' offset: 5 limit: 5) lines allButFirst.
	both := page1 , page2.
	direct := (server methodSendersOf: 'add:' offset: 0 limit: 10) lines allButFirst.
	self assert: both equals: direct.
	"stable order: the same call twice is byte-identical"
	self
		assert: (server methodSendersOf: 'add:' offset: 0 limit: 10)
		equals: (server methodSendersOf: 'add:' offset: 0 limit: 10)
]

{ #category : 'tests' }
PharoMcpServerNavigationTest >> testResultIsCachedThenInvalidatedOnCompile [
	| probeSelector before after |
	probeSelector := 'zzzPharoMcpProbeSelector'.
	before := server methodSendersOf: probeSelector.
	self assert: (before lines first) equals: '# 0 result(s)'.
	self assert: server sendersCache notEmpty.
	[
		Object compile: 'zzzPharoMcpProbeHost ^ self ' , probeSelector classified: 'zzz-test'.
		"SystemAnnouncer MethodAdded must have flushed the cache"
		self assert: server sendersCache isEmpty.
		after := server methodSendersOf: probeSelector.
		self assert: (after lines first) equals: '# 1 result(s)' ]
		ensure: [ Object removeSelector: #zzzPharoMcpProbeHost ]
]

{ #category : 'tests' }
PharoMcpServerNavigationTest >> testUnknownClassIsReportedNotRaised [
	self
		assert: (server allCallsOnClass: 'NoSuchClassXYZ')
		equals: 'ERROR: class not found: NoSuchClassXYZ'.
	self
		assert: (server localSendersOf: 'add:' in: 'NoSuchClassXYZ')
		equals: 'ERROR: class not found: NoSuchClassXYZ'
]
