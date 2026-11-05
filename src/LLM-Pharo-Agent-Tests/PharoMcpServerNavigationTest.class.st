Class {
	#name : 'PharoMcpServerNavigationTest',
	#superclass : 'TestCase',
	#instVars : [
		'server'
	],
	#category : 'LLM-Pharo-Agent-Tests',
	#package : 'LLM-Pharo-Agent-Tests'
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

{ #category : 'tests - batch' }
PharoMcpServerNavigationTest >> testChangeImpactMergesScansInOneCall [

	| r |
	r := server changeImpactOf: 'Point' selector: 'x'.
	self assert: (r at: 'className') equals: 'Point'.
	self assert: ((r at: 'classReferences') includesKey: 'count').
	self assert: ((r at: 'subclasses') includesKey: 'count').
	self assert: (r includesKey: 'senders').
	self assert: (r includesKey: 'implementors').
	self assert: ((r at: 'senders') at: 'lines') isArray
]

{ #category : 'tests - batch' }
PharoMcpServerNavigationTest >> testClassDigestCoversSidesAndSources [

	| d sides instanceSide |
	d := server
		     classDigestFor: 'Point'
		     side: 'both'
		     includeSources: #( 'x' 'y' ).
	self assert: (d at: 'className') equals: 'Point'.
	self assert: ((d at: 'superclasses') includes: 'Object').
	sides := d at: 'sides'.
	self assert: sides size equals: 2.
	instanceSide := sides detect: [ :s | (s at: 'side') = 'instance' ].
	self assert: (instanceSide at: 'protocols') notEmpty.
	self assert: (instanceSide at: 'sources') size equals: 2.
	self assert:
		((instanceSide at: 'sources') allSatisfy: [ :src | src at: 'found' ])
]

{ #category : 'tests' }
PharoMcpServerNavigationTest >> testHeaderReportsTrueTotalIndependentOfPage [

	| full paged fullTotal |
	full := server methodSendersOf: 'add:'.
	fullTotal := (full lines first substrings: ' ') second asNumber.
	paged := server methodSendersOf: 'add:' offset: 0 limit: 3.
	self
		assert: (paged lines first substrings: ' ') second asNumber
		equals: fullTotal.
	"paged body has at most 3 rows (plus the header line)"
	self assert: paged lines size <= 4
]

{ #category : 'tests - batch' }
PharoMcpServerNavigationTest >> testIsonProjectionRoundTrips [
	"The optional ison format projects via IsonGraphWriter (neutral ISON-Core package). This test depends
	 only on ISON-Core, not on any SMT package."

	| d ison back |
	d := server
		     classDigestFor: 'Point'
		     side: 'instance'
		     includeSources: #( 'x' ).
	ison := server projectResult: d format: 'ison'.
	self assert: (ison beginsWith: '# ison1').
	back := IsonGraphReader new read: ison.
	self assert: (IsonGraphCodec equivalent: d to: back)
]

{ #category : 'tests - batch' }
PharoMcpServerNavigationTest >> testJsonProjectionRoundTrips [

	| d json back |
	d := server
		     classDigestFor: 'Point'
		     side: 'instance'
		     includeSources: #( 'x' ).
	json := server projectResult: d.
	back := STONJSON fromString: json.
	self assert: (back at: 'className') equals: 'Point'.
	self
		assert: ((back at: 'sides') first at: 'definition')
		equals: ((d at: 'sides') first at: 'definition')
]

{ #category : 'tests - batch' }
PharoMcpServerNavigationTest >> testMethodSourcesBatchResolvesAndReportsMissing [

	| r rows byRef |
	r := server methodSourcesFor:
		     #( 'OrderedCollection>>add:' 'OrderedCollection class>>new'
		        'NoSuchClass>>foo' 'Point>>zzzNoSuchSelector' ).
	self assert: (r at: 'count') equals: 4.
	rows := r at: 'results'.
	byRef := Dictionary new.
	rows do: [ :row | byRef at: (row at: 'ref') put: row ].
	self assert: ((byRef at: 'OrderedCollection>>add:') at: 'found').
	self deny: ((byRef at: 'OrderedCollection>>add:') at: 'classSide').
	self assert:
		((byRef at: 'OrderedCollection class>>new') at: 'classSide').
	self deny: ((byRef at: 'NoSuchClass>>foo') at: 'found').
	self deny: ((byRef at: 'Point>>zzzNoSuchSelector') at: 'found')
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
	page1 := (server methodSendersOf: 'add:' offset: 0 limit: 5) lines
		         allButFirst.
	page2 := (server methodSendersOf: 'add:' offset: 5 limit: 5) lines
		         allButFirst.
	both := page1 , page2.
	direct := (server methodSendersOf: 'add:' offset: 0 limit: 10) lines
		          allButFirst.
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
	self assert: before lines first equals: '# 0 result(s)'.
	self assert: server sendersCache notEmpty.
	[
		Object
			compile: 'zzzPharoMcpProbeHost ^ self ' , probeSelector
			classified: 'zzz-test'.
		"SystemAnnouncer MethodAdded must have flushed the cache"
		self assert: server sendersCache isEmpty.
		after := server methodSendersOf: probeSelector.
		self assert: after lines first equals: '# 1 result(s)' ] ensure: [
		Object removeSelector: #zzzPharoMcpProbeHost ]
]

{ #category : 'tests - batch' }
PharoMcpServerNavigationTest >> testRunTestsReportsTypedResult [
	"Targets a dedicated fixture (never this class) so running it through pharo_run_tests cannot recurse
	 into test-running on the single-threaded image."

	| r |
	r := server runTestsFor: 'PharoMcpServerRunTestsFixture'.
	self assert: (r at: 'run') equals: 2.
	self assert: (r at: 'passed') equals: 1.
	self assert: (r at: 'failureCount') equals: 1.
	self assert: ((r at: 'failures') anySatisfy: [ :line |
			 line includesSubstring: 'testFailsOnPurpose' ]).
	self
		assert: (r at: 'run')
		equals:
		(r at: 'passed') + (r at: 'failureCount') + (r at: 'errorCount').
	self assert:
		((server runTestsFor: 'NoSuchClassOrPackageXYZ') includesKey:
			 'error')
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
