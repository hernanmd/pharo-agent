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

{ #category : 'private' }
PharoMcpServer >> callToolNamed: toolName withArguments: args [

	toolName = 'pharo_eval' ifTrue: [
		^ self callToolResultText:
			  (self evaluateSource: (args at: 'code' ifAbsent: [ '' ]))
			  isError: false ].

	toolName = 'pharo_open_class_browser' ifTrue: [
		| name class |
		name := (args at: 'className' ifAbsent: [ '' ]) trimBoth.
		class := self classNamed: name.
		class ifNil: [
			^ self callToolResultText: 'Class not found: ' , name isError: true ].
		self deferToUi: [ Smalltalk tools browser openOnClass: class ].
		^ self callToolResultText: 'Browser requested for class ' , name isError: false ].

	toolName = 'pharo_open_method_browser' ifTrue: [
		| ref parts class selector |
		ref := (args at: 'reference' ifAbsent: [ '' ]) trimBoth.
		parts := ref substrings: '>>'.
		parts size = 2 ifFalse: [
			^ self
				  callToolResultText: 'Method reference must look like ClassName>>selector'
				  isError: true ].
		class := self classNamed: parts first.
		class ifNil: [
			^ self callToolResultText: 'Class not found: ' , parts first isError: true ].
		selector := parts second trimBoth asSymbol.
		(class includesSelector: selector) ifFalse: [
			^ self callToolResultText: 'Selector not found: ' , ref isError: true ].
		self deferToUi: [ Smalltalk tools browser openOnClass: class selector: selector ].
		^ self callToolResultText: 'Browser requested for method ' , ref isError: false ].

	toolName = 'pharo_class_source' ifTrue: [
		^ self
			  callToolResultText:
				  (self classSourceFor: (args at: 'className' ifAbsent: [ '' ]))
			  isError: false ].

	toolName = 'pharo_method_source' ifTrue: [
		^ self
			  callToolResultText:
				  (self
					   methodSourceFor: (args at: 'className' ifAbsent: [ '' ])
					   selector: (args at: 'selector' ifAbsent: [ '' ]))
			  isError: false ].

	toolName = 'pharo_create_class' ifTrue: [
		^ self
			  callToolResultText:
				  (self
					   createClassNamed: (args at: 'className' ifAbsent: [ '' ])
					   superclassName: (args at: 'superclassName' ifAbsent: [ '' ])
					   packageName: (args at: 'packageName' ifAbsent: [ '' ])
					   tag: (args at: 'tag' ifAbsent: [ nil ])
					   instanceVariables: (args at: 'instanceVariables' ifAbsent: [ nil ])
					   classVariables: (args at: 'classVariables' ifAbsent: [ nil ]))
			  isError: false ].

	toolName = 'pharo_compile_method' ifTrue: [
		^ self
			  callToolResultText:
				  (self
					   compileMethodSource: (args at: 'sourceCode' ifAbsent: [ '' ])
					   forClassNamed: (args at: 'className' ifAbsent: [ '' ])
					   protocol: (args at: 'protocol' ifAbsent: [ 'as yet unclassified' ])
					   classSide: (self
							    booleanFrom: (args at: 'classSide' ifAbsent: [ false ])
							    default: false))
			  isError: false ].

	^ self callToolResultText: 'Unknown tool: ' , toolName isError: true
]

{ #category : 'private' }
PharoMcpServer >> callToolResultText: aString isError: aBoolean [

	| result |
	result := OrderedDictionary new
		          at: 'content' put: {
				          (OrderedDictionary new
					           at: 'type' put: 'text';
					           at: 'text' put: aString;
					           yourself) };
		          yourself.
	(aBoolean or: [ aString beginsWith: 'ERROR:' ]) ifTrue: [
		result at: 'isError' put: true ].
	^ result
]

{ #category : 'private' }
PharoMcpServer >> classNamed: aName [

	^ Smalltalk globals at: aName trimBoth asSymbol ifAbsent: [ nil ]
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

{ #category : 'private' }
PharoMcpServer >> evaluateSource: aString [
	"Evaluate the given Smalltalk source and return its printString. Errors
	 bubble up to the caller (McpTool catches them and reports them as tool errors)."

	| result |
	result := OpalCompiler new
		          source: aString;
		          evaluate.
	^ result ifNil: [ 'nil' ] ifNotNil: [ result printString ]
]

{ #category : 'reflection' }
PharoMcpServer >> extensionSelectorsOf: aClassName [
	"Answer a textual list of the extension selectors (methods defined outside the class own package) for the given class."

	| class |
	class := self classNamed: aClassName.
	class ifNil: [ ^ 'ERROR: class not found: ' , aClassName ].
	^ self stringsAsLines: class extensionSelectors
]

{ #category : 'private' }
PharoMcpServer >> handleHttpMcpBody: aBodyString [

	| payload id method params |
	payload := [ STONJSON fromString: aBodyString ]
		           on: Error
		           do: [ :ex |
			           ^ self
				             jsonRpcErrorResponseForId: nil
				             code: -32700
				             message: ex messageText ].
	(payload isDictionary and: [ payload includesKey: 'method' ]) ifFalse: [
		^ self
			  jsonRpcErrorResponseForId: (payload at: 'id' ifAbsent: [ nil ])
			  code: -32600
			  message: 'Invalid JSON-RPC request' ].

	id := payload at: 'id' ifAbsent: [ nil ].
	method := payload at: 'method'.
	params := payload at: 'params' ifAbsent: [ OrderedDictionary new ].
	id ifNil: [
		method = 'notifications/initialized' ifTrue: [ ^ nil ].
		method = 'notifications/cancelled' ifTrue: [ ^ nil ] ].

	method = 'initialize' ifTrue: [
		^ self jsonRpcSuccessResponseForId: id result: (self initializeResultFor: params) ].
	method = 'ping' ifTrue: [
		^ self jsonRpcSuccessResponseForId: id result: OrderedDictionary new ].
	method = 'tools/list' ifTrue: [
		^ self
			  jsonRpcSuccessResponseForId: id
			  result: (OrderedDictionary new
					   at: 'tools' put: self toolDefinitions;
					   yourself) ].
	method = 'tools/call' ifTrue: [
		^ self
			  jsonRpcSuccessResponseForId: id
			  result: (self
					   callToolNamed: (params at: 'name' ifAbsent: [ '' ])
					   withArguments: (params at: 'arguments' ifAbsent: [ OrderedDictionary new ])) ].
	method = 'resources/list' ifTrue: [
		^ self
			  jsonRpcSuccessResponseForId: id
			  result: (OrderedDictionary new
					   at: 'resources' put: self resourceDefinitions;
					   yourself) ].
	method = 'resources/templates/list' ifTrue: [
		^ self
			  jsonRpcSuccessResponseForId: id
			  result: (OrderedDictionary new
					   at: 'resourceTemplates' put: self resourceTemplateDefinitions;
					   yourself) ].
	method = 'resources/read' ifTrue: [
		^ self
			  jsonRpcSuccessResponseForId: id
			  result: (OrderedDictionary new
					   at: 'contents' put: { (self resourceContentForUri: (params at: 'uri' ifAbsent: [ '' ])) };
					   yourself) ].
	method = 'prompts/list' ifTrue: [
		^ self
			  jsonRpcSuccessResponseForId: id
			  result: (OrderedDictionary new
					   at: 'prompts' put: #(  );
					   yourself) ].

	^ self
		  jsonRpcErrorResponseForId: id
		  code: -32601
		  message: 'Method not found: ' , method
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

{ #category : 'initialization' }
PharoMcpServer >> initialize [

	super initialize.
	port := self class defaultPort.
	server := nil.
	transport := nil
]

{ #category : 'private' }
PharoMcpServer >> initializeResultFor: params [

	| protocolVersion capabilities serverInfo result |
	protocolVersion := params
		                   at: 'protocolVersion'
		                   ifAbsent: [ '2025-06-18' ].
	capabilities := OrderedDictionary new
		                at: 'tools' put: OrderedDictionary new;
		                at: 'resources' put: OrderedDictionary new;
		                at: 'prompts' put: OrderedDictionary new;
		                yourself.
	serverInfo := OrderedDictionary new
		              at: 'name' put: 'pharo';
		              at: 'version' put: '0.1.0';
		              yourself.
	result := OrderedDictionary new
		          at: 'protocolVersion' put: protocolVersion;
		          at: 'capabilities' put: capabilities;
		          at: 'serverInfo' put: serverInfo;
		          at: 'instructions'
		          put:
			          'Use the available tools to inspect and edit the connected live Pharo image.';
		          yourself.
	^ result
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

{ #category : 'private' }
PharoMcpServer >> jsonRpcErrorResponseForId: anId code: aCode message: aMessage [

	^ String streamContents: [ :s |
		  (STONWriter new
			   jsonMode: true;
			   referencePolicy: #ignore;
			   on: s) nextPut: (OrderedDictionary new
				   at: 'jsonrpc' put: '2.0';
				   at: 'id' put: anId;
				   at: 'error' put: (OrderedDictionary new
						    at: 'code' put: aCode;
						    at: 'message' put: aMessage;
						    yourself);
				   yourself) ]
]

{ #category : 'private' }
PharoMcpServer >> jsonRpcSuccessResponseForId: anId result: aResultObject [

	^ String streamContents: [ :s |
		  (STONWriter new
			   jsonMode: true;
			   referencePolicy: #ignore;
			   on: s) nextPut: (OrderedDictionary new
				   at: 'jsonrpc' put: '2.0';
				   at: 'id' put: anId;
				   at: 'result' put: aResultObject;
				   yourself) ]
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

{ #category : 'registration' }
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
							  tag: (args at: 'tag')) ])
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

{ #category : 'private' }
PharoMcpServer >> resourceContentForUri: aUriString [

	| text |
	aUriString = 'pharo://system/info' ifTrue: [
		text := self systemInfoString.
		^ OrderedDictionary new
			  at: 'uri' put: aUriString;
			  at: 'mimeType' put: 'text/plain';
			  at: 'text' put: text;
			  yourself ].
	(aUriString beginsWith: 'pharo://class/') ifTrue: [
		| className |
		className := aUriString allButFirst: 'pharo://class/' size.
		text := self classSourceFor: className.
		^ OrderedDictionary new
			  at: 'uri' put: aUriString;
			  at: 'mimeType' put: 'text/plain';
			  at: 'text' put: text;
			  yourself ].
	(aUriString beginsWith: 'pharo://method/') ifTrue: [
		| remainder separatorIndex className selector |
		remainder := aUriString allButFirst: 'pharo://method/' size.
		separatorIndex := remainder indexOf: $/.
		separatorIndex = 0 ifTrue: [
			text := 'ERROR: malformed method resource URI: ' , aUriString ]
		ifFalse: [
			className := remainder copyFrom: 1 to: separatorIndex - 1.
			selector := remainder copyFrom: separatorIndex + 1 to: remainder size.
			text := self methodSourceFor: className selector: selector ].
		^ OrderedDictionary new
			  at: 'uri' put: aUriString;
			  at: 'mimeType' put: 'text/plain';
			  at: 'text' put: text;
			  yourself ].
	^ OrderedDictionary new
		  at: 'uri' put: aUriString;
		  at: 'mimeType' put: 'text/plain';
		  at: 'text' put: 'ERROR: unknown resource URI: ' , aUriString;
		  yourself
]

{ #category : 'private' }
PharoMcpServer >> resourceDefinitions [

	^ {
		  (OrderedDictionary new
			   at: 'uri' put: 'pharo://system/info';
			   at: 'name' put: 'Pharo System Info';
			   at: 'description' put: 'Pharo version and image identity';
			   at: 'mimeType' put: 'text/plain';
			   yourself) }
]

{ #category : 'private' }
PharoMcpServer >> resourceTemplateDefinitions [

	^ {
		  (OrderedDictionary new
			   at: 'uriTemplate' put: 'pharo://class/{className}';
			   at: 'name' put: 'Class Source';
			   at: 'description' put: 'Definition and method list of a class';
			   at: 'mimeType' put: 'text/plain';
			   yourself).
		  (OrderedDictionary new
			   at: 'uriTemplate' put: 'pharo://method/{className}/{selector}';
			   at: 'name' put: 'Method Source';
			   at: 'description' put: 'Source code of a single method';
			   at: 'mimeType' put: 'text/plain';
			   yourself) }
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

{ #category : 'private' }
PharoMcpServer >> stringSchema [

	^ self stringSchema: nil
]

{ #category : 'private' }
PharoMcpServer >> stringSchema: description [

	| schema |
	schema := OrderedDictionary new
		          at: 'type' put: 'string';
		          yourself.
	description ifNotNil: [ schema at: 'description' put: description ].
	^ schema
]

{ #category : 'private - formatting' }
PharoMcpServer >> stringsAsLines: aCollection [
	"Answer a newline-joined list of strings, one per line."

	^ String cr join: aCollection asOrderedCollection
]

{ #category : 'starting' }
PharoMcpServer >> systemInfoString [

	^ String streamContents: [ :s |
			  s
				  nextPutAll: 'Pharo: ';
				  print: SystemVersion current;
				  lf.
			  s
				  nextPutAll: 'Packages loaded: ';
				  print: PackageOrganizer default packages size;
				  lf.
			  s
				  nextPutAll: 'Image: ';
				  nextPutAll: Smalltalk image imagePath;
				  lf ]
]

{ #category : 'private' }
PharoMcpServer >> toolDefinitionNamed: name description: description schema: inputSchema [

	^ OrderedDictionary new
		  at: 'name' put: name;
		  at: 'description' put: description;
		  at: 'inputSchema' put: inputSchema;
		  yourself
]

{ #category : 'private' }
PharoMcpServer >> toolDefinitions [

	^ {
		  (self
			   toolDefinitionNamed: 'pharo_eval'
			   description: 'Evaluate a Smalltalk expression in the live Pharo image. Returns the printString of the result.'
			   schema: (self
					    toolSchemaForProperties:
						    (OrderedDictionary new
							     at: 'code' put: (self stringSchema: 'Smalltalk source to evaluate');
							     yourself)
					    required: #( 'code' ))).
		  (self
			   toolDefinitionNamed: 'pharo_open_class_browser'
			   description: 'Open a System Browser on the given class in the running image.'
			   schema: (self
					    toolSchemaForProperties:
						    (OrderedDictionary new
							     at: 'className' put: (self stringSchema: 'Fully-qualified class name, e.g. String');
							     yourself)
					    required: #( 'className' ))).
		  (self
			   toolDefinitionNamed: 'pharo_open_method_browser'
			   description: 'Open a System Browser on the given method. Reference format: ClassName>>selector.'
			   schema: (self
					    toolSchemaForProperties:
						    (OrderedDictionary new
							     at: 'reference' put: (self stringSchema: 'Method reference like String>>asUppercase');
							     yourself)
					    required: #( 'reference' ))).
		  (self
			   toolDefinitionNamed: 'pharo_class_source'
			   description: 'Return the class definition and the list of selectors for a class.'
			   schema: (self
					    toolSchemaForProperties:
						    (OrderedDictionary new
							     at: 'className' put: self stringSchema;
							     yourself)
					    required: #( 'className' ))).
		  (self
			   toolDefinitionNamed: 'pharo_method_source'
			   description: 'Return the source of a single method.'
			   schema: (self
					    toolSchemaForProperties:
						    (OrderedDictionary new
							     at: 'className' put: self stringSchema;
							     at: 'selector' put: self stringSchema;
							     yourself)
					    required: #( 'className' 'selector' ))).
		  (self
			   toolDefinitionNamed: 'pharo_create_class'
			   description: 'Create a class in the running image for terminal-driven coding workflows.'
			   schema: (self
					    toolSchemaForProperties:
						    (OrderedDictionary new
							     at: 'className' put: (self stringSchema: 'Name of the class to create');
							     at: 'superclassName' put: (self stringSchema: 'Superclass name, for example Object');
							     at: 'packageName' put: (self stringSchema: 'Target package name');
							     at: 'instanceVariables' put: (self stringSchema: 'Optional instance variable names separated by spaces or commas');
							     at: 'classVariables' put: (self stringSchema: 'Optional class variable names separated by spaces or commas');
							     at: 'tag' put: (self stringSchema: 'Optional package tag');
							     yourself)
					    required: #( 'className' 'superclassName' 'packageName' ))).
		  (self
			   toolDefinitionNamed: 'pharo_compile_method'
			   description: 'Compile a method on the instance side or class side of a class in the running image.'
			   schema: (self
					    toolSchemaForProperties:
						    (OrderedDictionary new
							     at: 'className' put: (self stringSchema: 'Target class name');
							     at: 'sourceCode' put: (self stringSchema: 'Full Smalltalk method source code');
							     at: 'protocol' put: (self stringSchema: 'Protocol/category name');
							     at: 'classSide' put: (self stringSchema: 'Optional true/false string. true compiles on the class side');
							     yourself)
					    required: #( 'className' 'sourceCode' 'protocol' ))) }
]

{ #category : 'private' }
PharoMcpServer >> toolResultForText: aString [

	(aString beginsWith: 'ERROR:')
		ifTrue: [ ^ McpToolResult errorText: (aString allButFirst: 'ERROR: ' size) ].
	^ McpToolResult successText: aString
]

{ #category : 'private' }
PharoMcpServer >> toolSchemaForProperties: properties required: requiredKeys [

	^ OrderedDictionary new
		  at: 'type' put: 'object';
		  at: 'properties' put: properties;
		  at: 'required' put: requiredKeys;
		  yourself
]

{ #category : 'starting' }
PharoMcpServer >> transport [

	^ transport
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
