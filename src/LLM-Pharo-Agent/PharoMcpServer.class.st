Class {
	#name : 'PharoMcpServer',
	#superclass : 'Object',
	#instVars : [
		'server',
		'transport',
		'port'
	],
	#classVars : [
		'DefaultInstance'
	],
	#category : 'LLM-Pharo-Agent-Core',
	#package : 'LLM-Pharo-Agent',
	#tag : 'Core'
}

{ #category : 'accessing' }
PharoMcpServer class >> default [

	^ DefaultInstance ifNil: [ DefaultInstance := self new ]
]

{ #category : 'accessing' }
PharoMcpServer class >> defaultPort [

	^ 4046
]

{ #category : 'accessing' }
PharoMcpServer class >> portFromEnvironment [

	| value |
	value := OSPlatform current environment
		         at: 'PHARO_MCP_PORT'
		         ifAbsent: [ self defaultPort printString ].
	^ value asNumber
]

{ #category : 'accessing' }
PharoMcpServer class >> resetDefault [

	<script>
	DefaultInstance ifNotNil: [
			[ DefaultInstance stop ]
				on: Exception
				do: [ :ex |
						Transcript
							show: ex printString;
							cr ] ].
	DefaultInstance := nil
]

{ #category : 'accessing' }
PharoMcpServer class >> start [

	^ self startOn: self portFromEnvironment
]

{ #category : 'accessing' }
PharoMcpServer class >> startOn: aPortNumber [

	| instance |
	instance := self default.
	instance port: aPortNumber.
	instance start.
	^ instance
]

{ #category : 'accessing' }
PharoMcpServer class >> stop [

	DefaultInstance ifNotNil: [ DefaultInstance stop ]
]

{ #category : 'helpers - slots' }
PharoMcpServer >> addInstanceVariable: aName in: className [
	^ self addInstanceVariables: { aName } in: className
]

{ #category : 'helpers - slots' }
PharoMcpServer >> addInstanceVariables: nameList in: className [
	"Add the given instance variables to className (skipping names already present), preserving methods.
	 nameList may be a string (comma/space separated) or a collection. Answers a status string."
	| toAdd result |
	toAdd := (self normalizedNamesFrom: nameList) collect: [ :each | each asSymbol ].
	toAdd ifEmpty: [ ^ 'ERROR: no instance variable names provided' ].
	result := self
		updateSlotsInClassNamed: className
		with: [ :current |
			| set |
			set := current asOrderedCollection.
			toAdd do: [ :n | (set includes: n) ifFalse: [ set add: n ] ].
			set asArray ].
	result isString ifTrue: [ ^ result ].
	^ 'Added instance variables to ' , className , '. Current: ' , String cr , (String cr join: result)
]

{ #category : 'reflection' }
PharoMcpServer >> allCallsOnClass: aClassName [
	"Answer a textual list of every method that refers to the given class, either by its global binding or by using its name as a literal. Returns the string ERROR: ... if the class is not found."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self methodsAsLines: class allCallsOn
]

{ #category : 'reflection' }
PharoMcpServer >> allInstVarNamesOf: aClassName [
	"Answer a textual list of every instance variable name known to the class hierarchy."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines: class allInstVarNames
]

{ #category : 'reflection' }
PharoMcpServer >> allSlotsOf: aClassName [
	"Answer a textual list of all slots visible in the class hierarchy, one slot per line, formatted as name=>(classOfSlot)."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines:
		  (class allSlots collect: [ :s | s printString ])
]

{ #category : 'private' }
PharoMcpServer >> behaviorNamed: aName classSide: aBoolean [

	| behavior |
	behavior := self classNamed: aName.
	behavior ifNil: [ ^ nil ].
	^ aBoolean
		  ifTrue: [ behavior classSide ]
		  ifFalse: [ behavior ]
]

{ #category : 'private - formatting' }
PharoMcpServer >> booleanAsText: aBoolean [
	"Answer true/false as the strings true/false."

	^ aBoolean
		  ifTrue: [ 'true' ]
		  ifFalse: [ 'false' ]
]

{ #category : 'private' }
PharoMcpServer >> booleanFrom: anObject default: aBoolean [

	anObject ifNil: [ ^ aBoolean ].
	anObject class = Boolean ifTrue: [ ^ anObject ].
	(anObject isString or: [ anObject respondsTo: #asString ]) ifTrue: [
		| value |
		value := anObject asString trimBoth asLowercase.
		(#( 'true' 'yes' '1' ) includes: value) ifTrue: [ ^ true ].
		(#( 'false' 'no' '0' ) includes: value) ifTrue: [ ^ false ] ].
	^ aBoolean
]

{ #category : 'helpers - class comment' }
PharoMcpServer >> classCommentOf: aClassName [
	| class |

	(class := self classNamed: aClassName)
		ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ class comment
]

{ #category : 'helpers - class comment' }
PharoMcpServer >> classHasComment: aClassName [
	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self booleanAsText: class hasComment
]

{ #category : 'private' }
PharoMcpServer >> classNamed: aName [

	^ Smalltalk globals at: aName trimBoth asSymbol ifAbsent: [ nil ]
]

{ #category : 'helpers - class side' }
PharoMcpServer >> classSideSourceFor: aClassName [

	| class stream |

	(class := self classNamed: aClassName)
		ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	class := class classSide.
	stream := String new writeStream.
	stream
		nextPutAll: class definitionString;
		cr;
		cr;
		nextPutAll: '"--- methods ---"';
		cr.
	(class selectors asSortedCollection: [ :a :b | a < b ]) do: [ :sel |
			stream
				nextPutAll: sel;
				cr ].
	^ stream contents
]

{ #category : 'private' }
PharoMcpServer >> classSourceFor: aClassName [

	| class stream |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	stream := String new writeStream.
	stream
		nextPutAll: class definitionString;
		cr;
		cr;
		nextPutAll: '"--- methods ---"';
		cr.
	(class selectors asSortedCollection: [ :a :b | a < b ]) do: [ :sel |
			stream
				nextPutAll: sel;
				cr ].
	^ stream contents
]

{ #category : 'compilation' }
PharoMcpServer >> compileMethodSource: sourceCode forClassNamed: className protocol: protocolName classSide: classSideBoolean [

	| behavior selector unescaped |
	behavior := self behaviorNamed: className classSide: classSideBoolean.
	behavior 
		ifNil: [ ^ 'ERROR: class not found: ' , className ].
	unescaped := self unescapeSmalltalkSource: sourceCode.
	selector := self mutateImageDuring: [
		            behavior compile: unescaped classified: protocolName ].
	^ 'Compiled ' , behavior name , '>>' , selector
]

{ #category : 'private' }
PharoMcpServer >> createClassNamed: className superclassName: superclassName packageName: packageName tag: tagName instanceVariables: instanceVariables classVariables: classVariables [

	| existingClass superclass builder createdClass sharedVariableNames |
	existingClass := self classNamed: className.
	existingClass ifNotNil: [ ^ 'ERROR: class already exists: ' , className ].
	superclass := self classNamed: superclassName.
	superclass ifNil: [ ^ 'ERROR: superclass not found: ' , superclassName ].
	PackageOrganizer default ensurePackage: packageName.
	builder := superclass << className asSymbol.
	builder package: packageName.
	tagName ifNotNil: [
		| trimmedTag |
		trimmedTag := tagName trimBoth.
		trimmedTag ifNotEmpty: [ builder tag: trimmedTag ] ].
	builder slots: (self normalizedNamesFrom: instanceVariables).
	sharedVariableNames := self normalizedNamesFrom: classVariables.
	sharedVariableNames isEmpty ifFalse: [ builder sharedVariables: sharedVariableNames ].
	createdClass := self mutateImageDuring: [ builder install ].
	^ 'Created class ' , createdClass name , ' in package ' , createdClass package name
]

{ #category : 'private' }
PharoMcpServer >> deferToUi: aBlock [
	"Run the given block on the UI process so that opening a browser
	 works even when called from a background process (HTTP handler)."

	self currentWorld worldState defer: aBlock
]

{ #category : 'modification' }
PharoMcpServer >> ensureProtocol: aProtocol in: aClassName [
	"Ensure the given protocol exists on the class (creating it if necessary). Returns the protocol name."

	| class protocol |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	protocol := class ensureProtocol: aProtocol.
	^ protocol name asString
]

{ #category : 'evaluation' }
PharoMcpServer >> evaluateSource: aString [
	"Evaluate the given Smalltalk source and return its printString. Errors
	 bubble up to the caller (McpTool catches them and reports them as tool errors)."
	| result unescaped |
	unescaped := self unescapeSmalltalkSource: aString.
	result := OpalCompiler new
			source: unescaped;
			evaluate.
	^ result 
		ifNil: [ 'nil' ] 
		ifNotNil: [ result printString ]
]

{ #category : 'reflection' }
PharoMcpServer >> extensionSelectorsOf: aClassName [
	"Answer a textual list of the extension selectors (methods defined outside the class own package) for the given class."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines: class extensionSelectors
]

{ #category : 'reflection' }
PharoMcpServer >> hasInstVarNamed: aName in: aClassName [
	"Answer true if the given class defines an instance variable with the given name."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self booleanAsText: (class hasInstVarNamed: aName)
]

{ #category : 'reflection' }
PharoMcpServer >> hasSlotNamed: aName in: aClassName [
	"Answer true if a slot with the given name exists in the class hierarchy. Wraps Class>>hasSlot: by first resolving the slot by name from allSlots."

	| class slot |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	slot := class allSlots
		        detect: [ :s | s name = aName asSymbol ]
		        ifNone: [ ^ self booleanAsText: false ].
	^ self booleanAsText: (class hasSlot: slot)
]

{ #category : 'iceberg' }
PharoMcpServer >> iceRepositoryNamed: aString [
	"Answer the IceRepository matching aString, or nil if not found"

	^ IceRepository registry
		  detect: [ :r | r name = aString ]
		  ifNone: [ nil ]
]

{ #category : 'initialization' }
PharoMcpServer >> initialize [

	super initialize.
	port := self class defaultPort.
	server := nil.
	transport := nil
]

{ #category : 'reflection' }
PharoMcpServer >> instVarNamesOf: aClassName [
	"Answer a textual list of the instance variable names defined locally on the class (not inherited)."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines: class instVarNames
]

{ #category : 'reflection' }
PharoMcpServer >> isMetaClass: aClassName [
	"Answer true if the class side of the given class is a metaclass. Direct wrapper of Class>>isMeta which is true for metaclasses and false for regular classes."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self booleanAsText: class isMeta
]

{ #category : 'accessing' }
PharoMcpServer >> isRunning [

	^ transport isNotNil and: [ transport isRunning ]
]

{ #category : 'reflection' }
PharoMcpServer >> localSendersOf: aSymbolString in: aClassName [
	"Answer a textual list of every method in the given class hierarchy that sends aSymbol."

	| class selector |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	selector := aSymbolString trimBoth asSymbol.
	^ self methodsAsLines: (class allLocalCallsOn: selector)
]

{ #category : 'reflection' }
PharoMcpServer >> localSlotsOf: aClassName [
	"Answer a textual list of slots defined locally on the class (not inherited), one per line."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines:
		  (class localSlots collect: [ :s | s printString ])
]

{ #category : 'reflection' }
PharoMcpServer >> methodSendersOf: aSelector [
	"Answer a textual list of every method in the image that sends the given selector."

	| selector |
	selector := aSelector trimBoth asSymbol.
	^ self methodsAsLines:
		  (SystemNavigation default allSendersOf: selector)
]

{ #category : 'private' }
PharoMcpServer >> methodSourceFor: aClassName selector: aSelector [

	| class selector |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	selector := aSelector trimBoth asSymbol.
	(class includesSelector: selector) ifFalse: [
		^ 'ERROR: selector not found: ' , aClassName , '>>' , aSelector ].
	^ (class >> selector) sourceCode
]

{ #category : 'helpers - method source' }
PharoMcpServer >> methodSourceFor: aClassName selector: aSelector classSide: classSideBoolean [

	| behavior selector |
	behavior := self
		            behaviorNamed: aClassName
		            classSide: classSideBoolean.
	behavior 
		ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	selector := aSelector trimBoth asSymbol.
	(behavior includesSelector: selector) 
		ifFalse: [ ^ 'ERROR: selector not found: ' , behavior name , '>>' , aSelector ].
	^ (behavior >> selector) sourceCode
]

{ #category : 'private - formatting' }
PharoMcpServer >> methodsAsLines: methods [
	"Answer a newline-joined textual list of method references, one per line."

	^ String cr join:
		  (methods asOrderedCollection collect: [ :m | m printString ])
]

{ #category : 'modification' }
PharoMcpServer >> moveClass: aClassName toPackage: aPackage tag: aTag [
	"Move the named class to the given package and tag. Returns 'moved to <package>-<tag>' on success or an ERROR string."
	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	class package: aPackage tag: aTag.
	^ 'moved to ' , aPackage , '-' , aTag
]

{ #category : 'private' }
PharoMcpServer >> mutateImageDuring: aBlock [
	"Evaluate aBlock with EpMonitor disabled, returning the block's result."

	| result |
	(Smalltalk globals includesKey: #EpMonitor) ifTrue: [
			(Smalltalk globals at: #EpMonitor) current disableDuring: [
				result := aBlock value ].
			^ result ].
	^ aBlock value
]

{ #category : 'private' }
PharoMcpServer >> normalizedNamesFrom: anObject [

	anObject ifNil: [ ^ #(  ) ].
	anObject isString ifTrue: [
		| trimmed |
		trimmed := anObject trimBoth.
		trimmed isEmpty ifTrue: [ ^ #(  ) ].
		^ (((trimmed copyReplaceAll: ',' with: ' ') substrings: ' ')
			   collect: [ :each | each trimBoth ])
			  select: [ :each | each isNotEmpty ] ].
	((anObject respondsTo: #collect:) and: [ anObject respondsTo: #asArray ]) ifTrue: [
		^ ((anObject collect: [ :each | each asString trimBoth ])
			   select: [ :each | each isNotEmpty ]) asArray ].
	^ { anObject asString trimBoth }
]

{ #category : 'accessing' }
PharoMcpServer >> port [

	^ port
]

{ #category : 'accessing' }
PharoMcpServer >> port: aPortNumber [

	port := aPortNumber asNumber
]

{ #category : 'helpers - protocols' }
PharoMcpServer >> protocolNamesOf: aClassName side: sideString [

	| behavior |
	behavior := self
		            behaviorNamed: aClassName
		            classSide: (self booleanFrom: sideString default: false).
	behavior ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines: behavior protocolNames asSortedCollection
]

{ #category : 'tool registration' }
PharoMcpServer >> registerIcebergTools2On: aServer [

	"IceRepository: modifiedPackages"
	aServer addTool: (McpTool
		name: 'pharo_ice_modified_packages'
		description: 'Answer the list of modified package names in the IceRepository.'
		inputSchema: (McpSchema
			object: {('repositoryName' -> McpSchema string)}
			required: #('repositoryName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					McpToolResult successText: (self stringsAsLines: (repo modifiedPackages collect: [:p | p name]))]]).

	"IceRepository: packageNamed:"
	aServer addTool: (McpTool
		name: 'pharo_ice_package_named'
		description: 'Answer the IcePackage with the given name in the IceRepository, or an error if not found.'
		inputSchema: (McpSchema
			object: {(
				'repositoryName' -> McpSchema string).
				('packageName' -> McpSchema string)}
			required: #('repositoryName' 'packageName'))
		handler: [:args |
			| repo pkg |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					pkg := [repo packageNamed: (args at: 'packageName')] on: Error do: [ nil ].
					pkg
						ifNil: [ McpToolResult errorText: 'Package not found: ' , (args at: 'packageName') ]
						ifNotNil: [ McpToolResult successText: pkg printString ]]]).

	"IceRepository: hasIncomingCommits"
	aServer addTool: (McpTool
		name: 'pharo_ice_has_incoming'
		description: 'Answer true if the IceRepository has incoming commits from its remote.'
		inputSchema: (McpSchema
			object: {('repositoryName' -> McpSchema string)}
			required: #('repositoryName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					McpToolResult successText: repo hasIncomingCommits printString]]).

	"IceRepository: hasOutgoingCommits"
	aServer addTool: (McpTool
		name: 'pharo_ice_has_outgoing'
		description: 'Answer true if the IceRepository has outgoing commits to its remote.'
		inputSchema: (McpSchema
			object: {('repositoryName' -> McpSchema string)}
			required: #('repositoryName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					McpToolResult successText: repo hasOutgoingCommits printString]]).

	"IceRepository: loadedPackages"
	aServer addTool: (McpTool
		name: 'pharo_ice_loaded_packages'
		description: 'Answer the list of loaded package names in the IceRepository.'
		inputSchema: (McpSchema
			object: {('repositoryName' -> McpSchema string)}
			required: #('repositoryName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					McpToolResult successText: (self stringsAsLines: (repo loadedPackages collect: [:p | p name]))]]).

	"IceRepository: isModified"
	aServer addTool: (McpTool
		name: 'pharo_ice_is_modified'
		description: 'Answer true if the IceRepository has uncommitted changes.'
		inputSchema: (McpSchema
			object: {('repositoryName' -> McpSchema string)}
			required: #('repositoryName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					McpToolResult successText: repo isModified printString]]).

	"IceRepository: includesPackageNamed:"
	aServer addTool: (McpTool
		name: 'pharo_ice_includes_package'
		description: 'Answer true if the IceRepository includes a package with the given name.'
		inputSchema: (McpSchema
			object: {(
				'repositoryName' -> McpSchema string).
				('packageName' -> McpSchema string)}
			required: #('repositoryName' 'packageName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					McpToolResult successText: (repo includesPackageNamed: (args at: 'packageName')) printString]])
]

{ #category : 'tool registration' }
PharoMcpServer >> registerIcebergTools3On: aServer [

	"IceRepository: push"
	aServer addTool: (McpTool
		name: 'pharo_ice_push'
		description: 'Push outgoing commits from the IceRepository to its remote. Returns the push result.'
		inputSchema: (McpSchema
			object: {('repositoryName' -> McpSchema string)}
			required: #('repositoryName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					repo push.
					McpToolResult successText: 'Pushed']]).

	"IceRepository: pull"
	aServer addTool: (McpTool
		name: 'pharo_ice_pull'
		description: 'Pull incoming commits from the remote into the IceRepository. Returns the pull result.'
		inputSchema: (McpSchema
			object: {('repositoryName' -> McpSchema string)}
			required: #('repositoryName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					repo pull.
					McpToolResult successText: 'Pulled']]).

	"IceRepository: remotes"
	aServer addTool: (McpTool
		name: 'pharo_ice_remotes'
		description: 'Answer the list of remote names in the IceRepository.'
		inputSchema: (McpSchema
			object: {('repositoryName' -> McpSchema string)}
			required: #('repositoryName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					McpToolResult successText: (self stringsAsLines: (repo remotes collect: [:r | r name]))]]).

	"IceRepository: remoteBranchNames"
	aServer addTool: (McpTool
		name: 'pharo_ice_remote_branches'
		description: 'Answer the list of remote branch names in the IceRepository.'
		inputSchema: (McpSchema
			object: {('repositoryName' -> McpSchema string)}
			required: #('repositoryName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					McpToolResult successText: (self stringsAsLines: repo remoteBranchNames)]]).

	"IceRepository: localBranchNames"
	aServer addTool: (McpTool
		name: 'pharo_ice_local_branches'
		description: 'Answer the list of local branch names in the IceRepository.'
		inputSchema: (McpSchema
			object: {('repositoryName' -> McpSchema string)}
			required: #('repositoryName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					McpToolResult successText: (self stringsAsLines: repo localBranchNames)]]).

	"IceRepository: remoteNamed:"
	aServer addTool: (McpTool
		name: 'pharo_ice_remote_named'
		description: 'Answer the remote with the given name in the IceRepository. Returns the remote URL.'
		inputSchema: (McpSchema
			object: {(
				'repositoryName' -> McpSchema string).
				('remoteName' -> McpSchema string)}
			required: #('repositoryName' 'remoteName'))
		handler: [:args |
			| repo remote |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					remote := repo remoteNamed: (args at: 'remoteName') ifAbsent: [ nil ].
					remote
						ifNil: [ McpToolResult errorText: 'Remote not found: ' , (args at: 'remoteName') ]
						ifNotNil: [ McpToolResult successText: remote url ]]]).

	"IceRepository: discardChanges"
	aServer addTool: (McpTool
		name: 'pharo_ice_discard_changes'
		description: 'Discard all uncommitted changes in the IceRepository. Returns ok on success.'
		inputSchema: (McpSchema
			object: {('repositoryName' -> McpSchema string)}
			required: #('repositoryName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					repo discardChanges.
					McpToolResult successText: 'Changes discarded']]).

	"IceRepository: notifyPackageModified:"
	aServer addTool: (McpTool
		name: 'pharo_ice_notify_package_modified'
		description: 'Notify the IceRepository that the given package has been modified. Useful after external code changes.'
		inputSchema: (McpSchema
			object: {(
				'repositoryName' -> McpSchema string).
				('packageName' -> McpSchema string)}
			required: #('repositoryName' 'packageName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					repo notifyPackageModified: (args at: 'packageName').
					McpToolResult successText: 'Notified']])
]

{ #category : 'tool registration' }
PharoMcpServer >> registerIcebergToolsOn: aServer [

	"IceRepository: commitWithMessage:"
	aServer addTool: (McpTool
		name: 'pharo_ice_commit'
		description: 'Commit all changes in the IceRepository with the given message. Returns the commit short ID on success.'
		inputSchema: (McpSchema
			object: {(
				'repositoryName' -> McpSchema string).
				('message' -> McpSchema string)}
			required: #('repositoryName' 'message'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					| commit |
					commit := repo commitWithMessage: (args at: 'message').
					McpToolResult successText: commit id printString]]).

	"IceRepository: createBranch:"
	aServer addTool: (McpTool
		name: 'pharo_ice_create_branch'
		description: 'Create a new branch with the given name in the IceRepository. Returns the branch name on success.'
		inputSchema: (McpSchema
			object: {(
				'repositoryName' -> McpSchema string).
				('branchName' -> McpSchema string)}
			required: #('repositoryName' 'branchName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					repo createBranch: (args at: 'branchName').
					McpToolResult successText: (args at: 'branchName')]]).

	"IceRepository: checkoutBranch:"
	aServer addTool: (McpTool
		name: 'pharo_ice_checkout_branch'
		description: 'Checkout the given branch in the IceRepository. Returns the branch name on success.'
		inputSchema: (McpSchema
			object: {(
				'repositoryName' -> McpSchema string).
				('branchName' -> McpSchema string)}
			required: #('repositoryName' 'branchName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					repo checkoutBranch: (args at: 'branchName').
					McpToolResult successText: (args at: 'branchName')]]).

	"IceRepository: switchToBranchNamed:"
	aServer addTool: (McpTool
		name: 'pharo_ice_switch_branch'
		description: 'Switch the IceRepository to the given branch. Returns the branch name on success.'
		inputSchema: (McpSchema
			object: {(
				'repositoryName' -> McpSchema string).
				('branchName' -> McpSchema string)}
			required: #('repositoryName' 'branchName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					repo switchToBranchNamed: (args at: 'branchName').
					McpToolResult successText: (args at: 'branchName')]]).

	"IceRepository: hasLocalBranchNamed:"
	aServer addTool: (McpTool
		name: 'pharo_ice_has_local_branch'
		description: 'Answer true if the IceRepository has a local branch with the given name.'
		inputSchema: (McpSchema
			object: {(
				'repositoryName' -> McpSchema string).
				('branchName' -> McpSchema string)}
			required: #('repositoryName' 'branchName'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					McpToolResult successText: (repo hasLocalBranchNamed: (args at: 'branchName')) printString]]).

	"IceRepository: checkout:"
	aServer addTool: (McpTool
		name: 'pharo_ice_checkout'
		description: 'Checkout the given commitish (branch name, tag, or commit ID) in the IceRepository. Returns the commitish on success.'
		inputSchema: (McpSchema
			object: {(
				'repositoryName' -> McpSchema string).
				('commitish' -> McpSchema string)}
			required: #('repositoryName' 'commitish'))
		handler: [:args |
			| repo |
			repo := self iceRepositoryNamed: (args at: 'repositoryName').
			repo
				ifNil: [ McpToolResult errorText: 'Repository not found: ' , (args at: 'repositoryName') ]
				ifNotNil: [
					repo checkout: (args at: 'commitish').
					McpToolResult successText: (args at: 'commitish')]])
]

{ #category : 'tool registration' }
PharoMcpServer >> registerNewToolsOn: aServer [

	"Tool 1: pharo_class_side_source"
	aServer addTool: (McpTool
		name: 'pharo_class_side_source'
		description: 'Return the class definition and selector list for the class side (metaclass) of the given class.'
		inputSchema: (McpSchema
			object: {('className' -> McpSchema string)}
			required: #('className'))
		handler: [:args |
			McpToolResult successText:
				(self classSideSourceFor: (args at: 'className'))]).

	"Tool 2: pharo_class_side_method_source"
	aServer addTool: (McpTool
		name: 'pharo_class_side_method_source'
		description: 'Return the source of a single method on the class side (metaclass) of the given class.'
		inputSchema: (McpSchema
			object: {(
				'className' -> McpSchema string).
				('selector' -> McpSchema string)}
			required: #('className' 'selector'))
		handler: [:args |
			McpToolResult successText: (self
				methodSourceFor: (args at: 'className')
				selector: (args at: 'selector')
				classSide: true)]).

	"Tool 3: pharo_class_comment"
	aServer addTool: (McpTool
		name: 'pharo_class_comment'
		description: 'Return the class comment of the given class.'
		inputSchema: (McpSchema
			object: {('className' -> McpSchema string)}
			required: #('className'))
		handler: [:args |
			McpToolResult successText:
				(self classCommentOf: (args at: 'className'))]).

	"Tool 4: pharo_class_has_comment"
	aServer addTool: (McpTool
		name: 'pharo_class_has_comment'
		description: 'Answer true if the given class has a non-empty comment.'
		inputSchema: (McpSchema
			object: {('className' -> McpSchema string)}
			required: #('className'))
		handler: [:args |
			McpToolResult successText:
				(self classHasComment: (args at: 'className'))]).

	"Tool 5: pharo_subclasses"
	aServer addTool: (McpTool
		name: 'pharo_subclasses'
		description:'Answer the subclass names of the given class. Set direct to true for only direct subclasses, false (default) for all subclasses.'
		inputSchema: (McpSchema
			object: {(
				'className' -> McpSchema string).
				('direct' -> (McpSchema string: 'true for direct subclasses only, false (default) for all subclasses'))}
			required: #('className'))
		handler: [:args |
			McpToolResult successText: (self
				subclassesOf: (args at: 'className')
				direct: (self booleanFrom: (args at: 'direct' ifAbsent: ['false']) default: false))]).

	"Tool 6: pharo_superclasses"
	aServer addTool: (McpTool
		name: 'pharo_superclasses'
		description: 'Answer the superclass names of the given class, from immediate superclass up to Object.'
		inputSchema: (McpSchema
			object: {('className' -> McpSchema string)}
			required: #('className'))
		handler: [:args |
			McpToolResult successText:
				(self superclassesOf: (args at: 'className'))]).

	"Tool 7: pharo_compile_method"
	aServer addTool: (McpTool
		name: 'pharo_compile_method'
		description:'Compile a method in the given class. Returns the compiled selector on success. Optionally specify a protocol and/or class side (metaclass).'
		inputSchema: (McpSchema
			object: {(
				'className' -> McpSchema string).
				('selector' -> (McpSchema string: 'The method selector, used to validate after compilation')).
				('sourceCode' -> McpSchema string).
				('protocol' -> (McpSchema string: 'Optional protocol/category name')).
				('side' -> (McpSchema string: 'instance (default) or class'))}
			required: #('className' 'selector' 'sourceCode'))
		handler: [:args |
			McpToolResult successText: (self
				compileMethodSource: (args at: 'sourceCode')
				forClassNamed: (args at: 'className')
				protocol: (args at: 'protocol' ifAbsent: [nil])
				classSide: (self booleanFrom: (args at: 'side' ifAbsent: ['instance']) default: false))]).

	"Tool 8: pharo_create_class"
	aServer addTool: (McpTool
		name: 'pharo_create_class'
		description:'Create a new class using Fluid syntax (<<). Requires superclass name, class name, package. Optionally tag, instance variables (comma/space-separated), class variables.'
		inputSchema: (McpSchema
			object: {(
				'className' -> (McpSchema string: 'Name of the new class to create')).
				('superclassName' -> (McpSchema string: 'Name of the superclass')).
				('packageName' -> McpSchema string).
				('tag' -> (McpSchema string: 'Optional tag within the package')).
				('instanceVariables' -> (McpSchema string: 'Optional comma or space-separated instance variable names')).
				('classVariables' -> (McpSchema string: 'Optional comma or space-separated class variable names'))}
			required: #('className' 'superclassName' 'packageName'))
		handler: [:args |
			McpToolResult successText: (self
				createClassNamed: (args at: 'className')
				superclassName: (args at: 'superclassName')
				packageName: (args at: 'packageName')
				tag: (args at: 'tag' ifAbsent: [nil])
				instanceVariables: (args at: 'instanceVariables' ifAbsent: [nil])
				classVariables: (args at: 'classVariables' ifAbsent: [nil]))]).

	"Tool 9: pharo_protocol_names"
	aServer addTool: (McpTool
		name: 'pharo_protocol_names'
		description: 'Answer the list of protocol (category) names for the given class. Set side to class for class-side protocols.'
		inputSchema: (McpSchema
			object: {(
				'className' -> McpSchema string).
				('side' -> (McpSchema string: 'instance (default) or class'))}
			required: #('className'))
		handler: [:args |
			McpToolResult successText: (self
				protocolNamesOf: (args at: 'className')
				side: (args at: 'side' ifAbsent: ['instance']))]).

	self registerIcebergToolsOn: aServer.
	self registerIcebergTools2On: aServer.
	self registerIcebergTools3On: aServer
]

{ #category : 'accessing' }
PharoMcpServer >> registerResourcesOn: aServer [

	aServer addResource: (McpResource
			 uri: 'pharo://system/info'
			 name: 'Pharo System Info'
			 description: 'Pharo version and image identity'
			 mimeType: 'text/plain'
			 handler: [ { (McpContentItem text: self systemInfoString) } ]).

	aServer addResourceTemplate: (McpResourceTemplate
			 uriTemplate: 'pharo://class/{className}'
			 name: 'Class Source'
			 description: 'Definition and method list of a class'
			 mimeType: 'text/plain'
			 handler: [ :params |
					 { (McpContentItem text:
						  (self classSourceFor: (params at: 'className'))) } ]).

	aServer addResourceTemplate: (McpResourceTemplate
			 uriTemplate: 'pharo://method/{className}/{selector}'
			 name: 'Method Source'
			 description: 'Source code of a single method'
			 mimeType: 'text/plain'
			 handler: [ :params |
					 { (McpContentItem text: (self
							   methodSourceFor: (params at: 'className')
							   selector: (params at: 'selector'))) } ])
]

{ #category : 'helpers - slots' }
PharoMcpServer >> registerSlotToolsOn: aServer [
	"Register tools to add/remove instance variables (slots) on an existing class via
	 ShiftClassBuilder (fillFor: + install), preserving methods. Mirrors createClassNamed:..."

	aServer addTool: (McpTool
		name: 'pharo_add_instance_variable'
		description: 'Add a single instance variable (slot) to an existing class, preserving its methods. Returns the new slot list.'
		inputSchema: (McpSchema
			object: {
				('className' -> McpSchema string).
				('instanceVariable' -> (McpSchema string: 'Name of the instance variable to add')) }
			required: #('className' 'instanceVariable'))
		handler: [ :args |
			McpToolResult successText: (self
				addInstanceVariable: (args at: 'instanceVariable')
				in: (args at: 'className')) ]).

	aServer addTool: (McpTool
		name: 'pharo_remove_instance_variable'
		description: 'Remove a single instance variable (slot) from an existing class, preserving its methods. Returns the removed name and the new slot list.'
		inputSchema: (McpSchema
			object: {
				('className' -> McpSchema string).
				('instanceVariable' -> (McpSchema string: 'Name of the instance variable to remove')) }
			required: #('className' 'instanceVariable'))
		handler: [ :args |
			McpToolResult successText: (self
				removeInstanceVariable: (args at: 'instanceVariable')
				in: (args at: 'className')) ]).

	aServer addTool: (McpTool
		name: 'pharo_add_instance_variables'
		description: 'Add multiple instance variables (slots) to an existing class, preserving its methods. Names already present are skipped. Returns the new slot list.'
		inputSchema: (McpSchema
			object: {
				('className' -> McpSchema string).
				('instanceVariables' -> (McpSchema string: 'Comma or space-separated instance variable names to add')) }
			required: #('className' 'instanceVariables'))
		handler: [ :args |
			McpToolResult successText: (self
				addInstanceVariables: (args at: 'instanceVariables')
				in: (args at: 'className')) ]).

	aServer addTool: (McpTool
		name: 'pharo_remove_instance_variables'
		description: 'Remove multiple instance variables (slots) from an existing class, preserving its methods. Absent names are reported but ignored. Returns the new slot list.'
		inputSchema: (McpSchema
			object: {
				('className' -> McpSchema string).
				('instanceVariables' -> (McpSchema string: 'Comma or space-separated instance variable names to remove')) }
			required: #('className' 'instanceVariables'))
		handler: [ :args |
			McpToolResult successText: (self
				removeInstanceVariables: (args at: 'instanceVariables')
				in: (args at: 'className')) ]).
]

{ #category : 'tools' }
PharoMcpServer >> registerToolsOn: aServer [

	aServer addTool: (McpTool
			 name: 'pharo_eval'
			 description:
			 'Evaluate a Smalltalk expression in the live Pharo image. Returns the printString of the result.'
			 inputSchema: (McpSchema
					  object:
					  { ('code' -> (McpSchema string: 'Smalltalk source to evaluate')) }
					  required: #( 'code' ))
			 handler: [ :args |
				 McpToolResult successText:
					 (self evaluateSource: (args at: 'code')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_open_class_browser'
			 description:
			 'Open a System Browser on the given class in the running image.'
			 inputSchema: (McpSchema
					  object: { ('className'
						   ->
						   (McpSchema string: 'Fully-qualified class name, e.g. String')) }
					  required: #( 'className' ))
			 handler: [ :args |
					 | name class |
					 name := (args at: 'className') trimBoth.
					 class := self classNamed: name.
					 class
						 ifNil: [ McpToolResult errorText: 'Class not found: ' , name ]
						 ifNotNil: [
								 self deferToUi: [ Smalltalk tools browser openOnClass: class ].
								 McpToolResult successText:
									 'Browser requested for class ' , name ] ]).

	aServer addTool: (McpTool
			 name: 'pharo_open_method_browser'
			 description:
			 'Open a System Browser on the given method. Reference format: ClassName>>selector.'
			 inputSchema: (McpSchema
					  object: { ('reference'
						   ->
						   (McpSchema string:
							    'Method reference like String>>asUppercase')) }
					  required: #( 'reference' ))
			 handler: [ :args |
					 | ref parts class selector |
					 ref := (args at: 'reference') trimBoth.
					 parts := ref substrings: '>>'.
					 parts size = 2
						 ifFalse: [
								 McpToolResult errorText:
									 'Method reference must look like ClassName>>selector' ]
						 ifTrue: [
								 class := self classNamed: parts first.
								 class
									 ifNil: [
									 McpToolResult errorText: 'Class not found: ' , parts first ]
									 ifNotNil: [
											 selector := parts second trimBoth asSymbol.
											 (class includesSelector: selector)
												 ifFalse: [
												 McpToolResult errorText: 'Selector not found: ' , ref ]
												 ifTrue: [
														 self deferToUi: [
															 Smalltalk tools browser
																 openOnClass: class
																 selector: selector ].
														 McpToolResult successText:
															 'Browser requested for method ' , ref ] ] ] ]).

	aServer addTool: (McpTool
			 name: 'pharo_class_source'
			 description:
			 'Return the class definition and the list of selectors for a class.'
			 inputSchema: (McpSchema
					  object: { ('className' -> McpSchema string) }
					  required: #( 'className' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self classSourceFor: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_method_source'
			 description: 'Return the source of a single method.'
			 inputSchema: (McpSchema
					  object: {
							  ('className' -> McpSchema string).
							  ('selector' -> McpSchema string) }
					  required: #( 'className' 'selector' ))
			 handler: [ :args |
					 McpToolResult successText: (self
							  methodSourceFor: (args at: 'className')
							  selector: (args at: 'selector')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_class_references'
			 description:
			 'Answer every method in the image that refers to the given class by name or as a global binding. Returns one method per line as Class>>selector.'
			 inputSchema: (McpSchema
					  object: { ('className' -> McpSchema string) }
					  required: #( 'className' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self allCallsOnClass: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_method_senders'
			 description:
			 'Answer every method in the image that sends the given selector. Returns one method per line as Class>>selector.'
			 inputSchema: (McpSchema
					  object: { ('selector' -> McpSchema string) }
					  required: #( 'selector' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self methodSendersOf: (args at: 'selector')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_local_senders'
			 description:
			 'Answer every method in the given class hierarchy that sends the given selector. Returns one method per line as Class>>selector.'
			 inputSchema: (McpSchema
					  object: {
							  ('className' -> McpSchema string).
							  ('selector' -> McpSchema string) }
					  required: #( 'className' 'selector' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self
							  localSendersOf: (args at: 'selector')
							  in: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_selectors_in_protocol'
			 description:
			 'Answer every selector of the class hierarchy that lives in the named protocol.'
			 inputSchema: (McpSchema
					  object: {
							  ('className' -> McpSchema string).
							  ('protocol' -> McpSchema string) }
					  required: #( 'className' 'protocol' ))
			 handler: [ :args |
					 McpToolResult successText: (self
							  selectorsInProtocol: (args at: 'protocol')
							  of: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_extension_selectors'
			 description:
			 'Answer every extension selector (method defined in another package than the class own) on the class.'
			 inputSchema: (McpSchema
					  object: { ('className' -> McpSchema string) }
					  required: #( 'className' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self extensionSelectorsOf: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_has_inst_var_named'
			 description:
			 'Answer true if the class hierarchy defines an instance variable with the given name.'
			 inputSchema: (McpSchema
					  object: {
							  ('className' -> McpSchema string).
							  ('name' -> McpSchema string) }
					  required: #( 'className' 'name' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self
							  hasInstVarNamed: (args at: 'name')
							  in: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_has_slot'
			 description:
			 'Answer true if the class hierarchy defines a slot with the given name.'
			 inputSchema: (McpSchema
					  object: {
							  ('className' -> McpSchema string).
							  ('name' -> McpSchema string) }
					  required: #( 'className' 'name' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self
							  hasSlotNamed: (args at: 'name')
							  in: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_all_inst_var_names'
			 description:
			 'Answer every instance variable name known to the class hierarchy.'
			 inputSchema: (McpSchema
					  object: { ('className' -> McpSchema string) }
					  required: #( 'className' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self allInstVarNamesOf: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_inst_var_names'
			 description:
			 'Answer the instance variable names declared locally on the class (not inherited).'
			 inputSchema: (McpSchema
					  object: { ('className' -> McpSchema string) }
					  required: #( 'className' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self instVarNamesOf: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_slot_names'
			 description:
			 'Answer the slot names declared locally on the class (not inherited).'
			 inputSchema: (McpSchema
					  object: { ('className' -> McpSchema string) }
					  required: #( 'className' ))
			 handler: [ :args |
				 McpToolResult successText:
					 (self slotNamesOf: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_all_slots'
			 description:
			 'Answer every slot visible in the class hierarchy, one per line, formatted as name=>(SlotClass).'
			 inputSchema: (McpSchema
					  object: { ('className' -> McpSchema string) }
					  required: #( 'className' ))
			 handler: [ :args |
				 McpToolResult successText:
					 (self allSlotsOf: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_local_slots'
			 description:
			 'Answer every slot declared locally on the class (not inherited), one per line, formatted as name=>(SlotClass).'
			 inputSchema: (McpSchema
					  object: { ('className' -> McpSchema string) }
					  required: #( 'className' ))
			 handler: [ :args |
				 McpToolResult successText:
					 (self localSlotsOf: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_unreferenced_inst_vars'
			 description:
			 'Answer the slot names known to the class hierarchy that are not referenced by any method.'
			 inputSchema: (McpSchema
					  object: { ('className' -> McpSchema string) }
					  required: #( 'className' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self unreferencedInstVarsOf: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_is_meta'
			 description:
			 'Answer true if the class side of the given class is a metaclass. Direct wrapper of Class>>isMeta.'
			 inputSchema: (McpSchema
					  object: { ('className' -> McpSchema string) }
					  required: #( 'className' ))
			 handler: [ :args |
				 McpToolResult successText:
					 (self isMetaClass: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_ensure_protocol'
			 description:
			 'Ensure the named protocol exists on the class, creating it if necessary. Returns the protocol name.'
			 inputSchema: (McpSchema
					  object: {
							  ('className' -> McpSchema string).
							  ('protocol' -> McpSchema string) }
					  required: #( 'className' 'protocol' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self
							  ensureProtocol: (args at: 'protocol')
							  in: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_remove_method'
			 description:
			 'Remove the named method from the given class. Returns "removed" on success, "not present" if the method was not present.'
			 inputSchema: (McpSchema
					  object: {
							  ('className' -> McpSchema string).
							  ('selector' -> McpSchema string) }
					  required: #( 'className' 'selector' ))
			 handler: [ :args |
					 McpToolResult successText:
						 (self
							  removeMethod: (args at: 'selector')
							  from: (args at: 'className')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_move_class_to_package_tag'
			 description: 'Move the named class to the given package and tag.'
			 inputSchema: (McpSchema
					  object: {
							  ('className' -> McpSchema string).
							  ('package' -> McpSchema string).
							  ('tag' -> McpSchema string) }
					  required: #( 'className' 'package' 'tag' ))
			 handler: [ :args |
					 McpToolResult successText: (self
							  moveClass: (args at: 'className')
							  toPackage: (args at: 'package')
							  tag: (args at: 'tag')) ]).
	self registerNewToolsOn: aServer
]

{ #category : 'helpers - slots' }
PharoMcpServer >> removeInstanceVariable: aName in: className [
	^ self removeInstanceVariables: { aName } in: className
]

{ #category : 'helpers - slots' }
PharoMcpServer >> removeInstanceVariables: nameList in: className [
	"Remove the given instance variables from className (ignoring absent names), preserving methods.
	 nameList may be a string (comma/space separated) or a collection. Answers a status string."
	| toRemove removed result |
	toRemove := (self normalizedNamesFrom: nameList) collect: [ :each | each asSymbol ].
	toRemove ifEmpty: [ ^ 'ERROR: no instance variable names provided' ].
	removed := OrderedCollection new.
	result := self
		updateSlotsInClassNamed: className
		with: [ :current |
			| set |
			set := current asOrderedCollection.
			toRemove do: [ :n |
				(set includes: n)
					ifTrue: [ set remove: n. removed add: n ]
					ifFalse: [ removed add: ('(absent) ' , n asString) ] ].
			set asArray ].
	result isString ifTrue: [ ^ result ].
	^ 'Removed from ' , className , ': ' , (String cr join: removed) , String cr , 'Current: ' , String cr , (String cr join: result)
]

{ #category : 'modification' }
PharoMcpServer >> removeMethod: aSelector from: aClassName [
	"Remove the named method from the given class. Returns 'removed' on success, 'not present' if the selector was not present, or 'ERROR: ...' on failure."

	| class selector |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	selector := aSelector trimBoth asSymbol.
	(class includesSelector: selector) ifFalse: [ ^ 'not present' ].
	class removeSelector: selector.
	^ 'removed'
]

{ #category : 'reflection' }
PharoMcpServer >> selectorsInProtocol: aProtocolName of: aClassName [
	"Answer a textual list of every selector in the given protocol across the class hierarchy."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines: (class allSelectorsInProtocol: aProtocolName)
]

{ #category : 'accessing' }
PharoMcpServer >> server [

	^ server
]

{ #category : 'reflection' }
PharoMcpServer >> slotNamesOf: aClassName [
	"Answer a textual list of slot names defined locally on the class (not inherited)."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines: class slotNames
]

{ #category : 'starting' }
PharoMcpServer >> start [
	self isRunning ifTrue: [ ^ self ].
	transport := McpHttpTransport new port: port; yourself.
	server := McpServer name: MCPConstants mcpServerName version: MCPConstants mcpServerVersion.
	server transport: transport.
	self registerToolsOn: server.
	self registerResourcesOn: server.
	self registerSlotToolsOn: server.
	server start.
	Transcript
		show: '[PharoMcpServer] MCP server listening on http://localhost:';
		show: port printString;
		show: '/mcp';
		cr.
	^ self
]

{ #category : 'starting' }
PharoMcpServer >> stop [

	server ifNotNil: [
			[ server stop ]
				on: Exception
				do: [ :ex |
						Transcript
							show: ex printString;
							cr ].
			server := nil ].
	transport := nil
]

{ #category : 'private - formatting' }
PharoMcpServer >> stringsAsLines: aCollection [
	"Answer a newline-joined list of strings, one per line."

	^ String cr join: aCollection asOrderedCollection
]

{ #category : 'helpers - hierarchy' }
PharoMcpServer >> subclassesOf: aClassName direct: directBoolean [
	| class |
	class := self classNamed: aClassName.
	class 
		ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines: (directBoolean
		ifTrue: [ class subclasses collect: #name ]
		ifFalse: [ class allSubclasses collect: #name])
]

{ #category : 'helpers - hierarchy' }
PharoMcpServer >> superclassesOf: aClassName [
	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines: (class allSuperclasses collect: #name)
]

{ #category : 'starting' }
PharoMcpServer >> systemInfoString [

	^ String streamContents: [ :s |
			  s
				  nextPutAll: 'Pharo: ';
				  print: SystemVersion current;
				  cr.
			  s
				  nextPutAll: 'Packages loaded: ';
				  print: PackageOrganizer default packages size;
				  cr.
			  s
				  nextPutAll: 'Image: ';
				  nextPutAll: Smalltalk image imagePath;
				  cr ]
]

{ #category : 'starting' }
PharoMcpServer >> transport [

	^ transport
]

{ #category : 'private' }
PharoMcpServer >> unescapeSmalltalkSource: aString [
	"Replace common escape sequences with their actual characters.
	 LLMs often send literal backslash-r/t/n instead of actual CR/TAB/CR characters."
	| result |
	result := aString copyReplaceAll: '\r' with: String cr.
	result := result copyReplaceAll: '\t' with: String tab.
	result := result copyReplaceAll: '\n' with: String cr.
	^ result
]

{ #category : 'reflection' }
PharoMcpServer >> unreferencedInstVarsOf: aClassName [
	"Answer a textual list of slot names known to the class but not referenced by any method."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines:
		  (class allUnreferencedInstanceVariables collect: [ :s | s name ])
]

{ #category : 'helpers - slots' }
PharoMcpServer >> updateSlotsInClassNamed: className with: aBlock [
	"Private - Reinstall className with its local slots replaced by (aBlock value: currentSlotNames),
	 preserving methods (ShiftClassBuilder fillFor: + install). Answers the new slot names array,
	 or an 'ERROR: ...' string on failure."
	| class builder |
	class := self classNamed: className.
	class ifNil: [ ^ 'ERROR: class not found: ' , className ].
	builder := ShiftClassBuilder new fillFor: class.
	builder slots: (aBlock value: (class slots collect: [ :s | s name ]) asArray).
	self mutateImageDuring: [ builder install ].
	^ ((self classNamed: className) slots collect: [ :s | s name ]) asArray
]
