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
	#category : 'LLM-Pharo-Agent',
	#package : 'LLM-Pharo-Agent'
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

{ #category : 'private' }
PharoMcpServer >> classNamed: aName [

	^ Smalltalk globals at: aName trimBoth asSymbol ifAbsent: [ nil ]
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

{ #category : 'private' }
PharoMcpServer >> classSourceFor: aClassName [

	| class stream |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	stream := String new writeStream.
	stream
		nextPutAll: class definitionString;
		nextPut: Character lf;
		nextPut: Character lf;
		nextPutAll: '"--- methods ---"';
		nextPut: Character lf.
	(class selectors asSortedCollection: [ :a :b | a < b ]) do: [ :sel |
		stream
			nextPutAll: sel;
			nextPut: Character lf ].
	^ stream contents
]

{ #category : 'private' }
PharoMcpServer >> deferToUi: aBlock [
	"Run the given block on the UI process so that opening a browser
	 works even when called from a background process (HTTP handler)."

	self currentWorld worldState defer: aBlock
]

{ #category : 'private' }
PharoMcpServer >> evaluateSource: aString [
	"Evaluate the given Smalltalk source and return its printString. Errors
	 bubble up to the caller (McpTool catches them and reports them as tool errors)."

	| result |
	result := OpalCompiler new
		          source: aString;
		          evaluate.
	^ result
		  ifNil: [ 'nil' ]
		  ifNotNil: [ result printString ]
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

{ #category : 'private' }
PharoMcpServer >> compileMethodSource: sourceCode forClassNamed: className protocol: protocolName classSide: classSideBoolean [

	| behavior selector |
	behavior := self behaviorNamed: className classSide: classSideBoolean.
	behavior ifNil: [ ^ 'ERROR: class not found: ' , className ].
	selector := self mutateImageDuring: [
		            behavior
			            compile: sourceCode
			            classified: protocolName ].
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

{ #category : 'accessing' }
PharoMcpServer >> initialize [

	super initialize.
	port := self class defaultPort.
	server := nil.
	transport := nil
]

{ #category : 'accessing' }
PharoMcpServer >> isRunning [

	^ transport isNotNil and: [ transport isRunning ]
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

{ #category : 'private' }
PharoMcpServer >> mutateImageDuring: aBlock [

	(Smalltalk globals includesKey: #EpMonitor) ifTrue: [
		^ (Smalltalk globals at: #EpMonitor) disableDuring: aBlock ].
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

{ #category : 'private' }
PharoMcpServer >> toolResultForText: aString [

	(aString beginsWith: 'ERROR:')
		ifTrue: [ ^ McpToolResult errorText: (aString allButFirst: 'ERROR: ' size) ].
	^ McpToolResult successText: aString
]

{ #category : 'accessing' }
PharoMcpServer >> port: aPortNumber [

	port := aPortNumber asNumber
]

{ #category : 'accessing' }
PharoMcpServer >> registerResourcesOn: aServer [

	aServer addResource: (McpResource
			 uri: 'pharo://system/info'
			 name: 'Pharo System Info'
			 description: 'Pharo version and image identity'
			 mimeType: 'text/plain'
			 handler: [ { McpContentItem text: self systemInfoString } ]).

	aServer addResourceTemplate: (McpResourceTemplate
			 uriTemplate: 'pharo://class/{className}'
			 name: 'Class Source'
			 description: 'Definition and method list of a class'
			 mimeType: 'text/plain'
			 handler: [ :params |
				 { McpContentItem text: (self classSourceFor: (params at: 'className')) } ]).

	aServer addResourceTemplate: (McpResourceTemplate
			 uriTemplate: 'pharo://method/{className}/{selector}'
			 name: 'Method Source'
			 description: 'Source code of a single method'
			 mimeType: 'text/plain'
			 handler: [ :params |
				 { McpContentItem text: (self
						    methodSourceFor: (params at: 'className')
						    selector: (params at: 'selector')) } ])
]

{ #category : 'accessing' }
PharoMcpServer >> registerToolsOn: aServer [

	aServer addTool: (McpTool
			 name: 'pharo_eval'
			 description: 'Evaluate a Smalltalk expression in the live Pharo image. Returns the printString of the result.'
			 inputSchema: (McpSchema
					  object: {
							  ('code' -> (McpSchema string: 'Smalltalk source to evaluate')) }
					  required: #( 'code' ))
			 handler: [ :args |
				 McpToolResult successText:
					 (self evaluateSource: (args at: 'code')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_open_class_browser'
			 description: 'Open a System Browser on the given class in the running image.'
			 inputSchema: (McpSchema
					  object: {
							  ('className' -> (McpSchema string: 'Fully-qualified class name, e.g. String')) }
					  required: #( 'className' ))
			 handler: [ :args |
				 | name class |
				 name := (args at: 'className') trimBoth.
				 class := self classNamed: name.
				 class
					 ifNil: [ McpToolResult errorText: 'Class not found: ' , name ]
					 ifNotNil: [
						 self deferToUi: [ Smalltalk tools browser openOnClass: class ].
						 McpToolResult successText: 'Browser requested for class ' , name ] ]).

	aServer addTool: (McpTool
			 name: 'pharo_open_method_browser'
			 description: 'Open a System Browser on the given method. Reference format: ClassName>>selector.'
			 inputSchema: (McpSchema
					  object: {
							  ('reference' -> (McpSchema string: 'Method reference like String>>asUppercase')) }
					  required: #( 'reference' ))
			 handler: [ :args |
				 | ref parts class selector |
				 ref := (args at: 'reference') trimBoth.
				 parts := ref substrings: '>>'.
				 parts size = 2
					 ifFalse: [ McpToolResult errorText:
							 'Method reference must look like ClassName>>selector' ]
					 ifTrue: [
						 class := self classNamed: parts first.
						 class
							 ifNil: [ McpToolResult errorText: 'Class not found: ' , parts first ]
							 ifNotNil: [
								 selector := parts second trimBoth asSymbol.
								 (class includesSelector: selector)
									 ifFalse: [ McpToolResult errorText: 'Selector not found: ' , ref ]
									 ifTrue: [
										 self deferToUi: [ Smalltalk tools browser openOnClass: class selector: selector ].
										 McpToolResult successText: 'Browser requested for method ' , ref ] ] ] ]).

	aServer addTool: (McpTool
			 name: 'pharo_class_source'
			 description: 'Return the class definition and the list of selectors for a class.'
			 inputSchema: (McpSchema
					  object: { ('className' -> McpSchema string) }
					  required: #( 'className' ))
			 handler: [ :args |
				 self toolResultForText:
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
				 self toolResultForText: (self
						  methodSourceFor: (args at: 'className')
						  selector: (args at: 'selector')) ]).

	aServer addTool: (McpTool
			 name: 'pharo_create_class'
			 description: 'Create a class in the running image for terminal-driven coding workflows.'
			 inputSchema: (McpSchema
					  object: {
							  ('className' -> (McpSchema string: 'Name of the class to create')).
							  ('superclassName' -> (McpSchema string: 'Superclass name, for example Object')).
							  ('packageName' -> (McpSchema string: 'Target package name')).
							  ('instanceVariables' -> (McpSchema string: 'Optional instance variable names separated by spaces or commas')).
							  ('classVariables' -> (McpSchema string: 'Optional class variable names separated by spaces or commas')).
							  ('tag' -> (McpSchema string: 'Optional package tag')) }
					  required: #( 'className' 'superclassName' 'packageName' ))
			 handler: [ :args |
				 self toolResultForText: (self
						  createClassNamed: (args at: 'className')
						  superclassName: (args at: 'superclassName')
						  packageName: (args at: 'packageName')
						  tag: (args at: 'tag' ifAbsent: [ nil ])
						  instanceVariables: (args at: 'instanceVariables' ifAbsent: [ nil ])
						  classVariables: (args at: 'classVariables' ifAbsent: [ nil ])) ]).

	aServer addTool: (McpTool
			 name: 'pharo_compile_method'
			 description: 'Compile a method on the instance side or class side of a class in the running image.'
			 inputSchema: (McpSchema
					  object: {
							  ('className' -> (McpSchema string: 'Target class name')).
							  ('sourceCode' -> (McpSchema string: 'Full Smalltalk method source code')).
							  ('protocol' -> (McpSchema string: 'Protocol/category name')).
							  ('classSide' -> (McpSchema string: 'Optional true/false string. true compiles on the class side')) }
					  required: #( 'className' 'sourceCode' 'protocol' ))
			 handler: [ :args |
				 self toolResultForText: (self
						  compileMethodSource: (args at: 'sourceCode')
						  forClassNamed: (args at: 'className')
						  protocol: (args at: 'protocol')
						  classSide: (self
								   booleanFrom: (args at: 'classSide' ifAbsent: [ false ])
								   default: false)) ])
]

{ #category : 'accessing' }
PharoMcpServer >> server [

	^ server
]

{ #category : 'starting' }
PharoMcpServer >> start [

	self isRunning ifTrue: [ ^ self ].

	transport := McpHttpTransport new
		             port: port;
		             yourself.
	server := McpServer
		          name: MCPConstants mcpServerName
		          version: MCPConstants mcpServerVersion.
	server transport: transport.
	self registerToolsOn: server.
	self registerResourcesOn: server.
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

{ #category : 'starting' }
PharoMcpServer >> systemInfoString [

	^ String streamContents: [ :s |
		  s nextPutAll: 'Pharo: '; print: SystemVersion current; lf.
		  s nextPutAll: 'Packages loaded: '; print: PackageOrganizer default packages size; lf.
		  s nextPutAll: 'Image: '; nextPutAll: Smalltalk image imagePath; lf ]
]

{ #category : 'starting' }
PharoMcpServer >> transport [

	^ transport
]
