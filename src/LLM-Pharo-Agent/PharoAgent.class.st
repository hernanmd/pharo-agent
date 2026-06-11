"
CLI Client

```
PharoAgent stop.

PharoAgent resetDefault.

PharoAgent startOn: 5055
```
"
Class {
	#name : 'PharoAgent',
	#superclass : 'Object',
	#instVars : [
		'serverSocket',
		'port',
		'running',
		'serverProcess'
	],
	#classVars : [
		'DefaultInstance'
	],
	#category : 'LLM-Pharo-Agent-Core',
	#package : 'LLM-Pharo-Agent',
	#tag : 'Core'
}

{ #category : 'accessing' }
PharoAgent class >> default [

	^ DefaultInstance ifNil: [ DefaultInstance := self new ]
]

{ #category : 'accessing' }
PharoAgent class >> openBrowserOnClassNamed: aString [

	^ self default openBrowserOnClassNamed: aString
]

{ #category : 'accessing' }
PharoAgent class >> openBrowserOnMethod: aMethodReferenceString [

	^ self default openBrowserOnMethod: aMethodReferenceString
]

{ #category : 'accessing' }
PharoAgent class >> portFromEnvironment [

	| value |
	value := OSPlatform current environment
		         at: 'PHARO_CLI_PORT'
		         ifAbsent: [ '4044' ].
	^ value asNumber
]

{ #category : 'accessing' }
PharoAgent class >> resetDefault [

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
PharoAgent class >> start [

	^ self startOn: self portFromEnvironment
]

{ #category : 'accessing' }
PharoAgent class >> startFromEnvironment [

	^ self start
]

{ #category : 'accessing' }
PharoAgent class >> startMcp [
	"Start the MCP server on the port declared by PHARO_MCP_PORT (defaults to 4046).
	 Exposes Pharo tools and resources over HTTP so CLI agents like Claude Code,
	 Codex or Qwen can talk directly to this live image."

	^ PharoMcpServer start
]

{ #category : 'accessing' }
PharoAgent class >> startMcpOn: aPortNumber [
	"Start the MCP server on aPortNumber. See #startMcp."

	^ PharoMcpServer startOn: aPortNumber
]

{ #category : 'accessing' }
PharoAgent class >> startOn: aPortNumber [

	| agent |
	agent := self default.
	agent port: aPortNumber.
	agent start.
	^ agent
]

{ #category : 'accessing' }
PharoAgent class >> stop [

	DefaultInstance ifNotNil: [ DefaultInstance stop ]
]

{ #category : 'accessing' }
PharoAgent class >> stopMcp [

	PharoMcpServer stop
]

{ #category : 'accessing' }
PharoAgent >> evaluate: aString [

	| result |
	result := OpalCompiler new
		          source: aString;
		          evaluate.
	^ result ifNil: [ 'nil' ] ifNotNil: [ result printString ]
]

{ #category : 'accessing' }
PharoAgent >> evaluateRequest: aString [

	| source |
	source := aString trimBoth.

	source isEmpty ifTrue: [ ^ '' ]. "UI commands must be deferred onto the UI/world process."
	(source beginsWith: 'OPEN_CLASS_BROWSER ') ifTrue: [
			^ self openBrowserOnClassNamed:
				  (source allButFirst: 'OPEN_CLASS_BROWSER ' size) ].

	(source beginsWith: 'OPEN_METHOD_BROWSER ') ifTrue: [
			^ self openBrowserOnMethod:
				  (source allButFirst: 'OPEN_METHOD_BROWSER ' size) ].

	^ self evaluate: source
]

{ #category : 'accessing' }
PharoAgent >> exceptionStringFor: anException [

	^ String streamContents: [ :stream |
			  stream
				  nextPutAll: anException class name;
				  nextPutAll: ': '.
			  anException messageText
				  ifNil: [ stream nextPutAll: anException printString ]
				  ifNotNil: [ stream nextPutAll: anException messageText ] ]
]

{ #category : 'initialization' }
PharoAgent >> initialize [

	super initialize.
	port := 4044.
	running := false.
]

{ #category : 'accessing' }
PharoAgent >> isRunning [

	^ running
]

{ #category : 'accessing' }
PharoAgent >> openBrowserOnClassNamed: aString [

	| className class |
	className := aString trimBoth.
	class := Smalltalk
		         at: className asSymbol
		         ifAbsent: [ ^ 'ERROR: class not found: ' , className ].

	self currentWorld worldState defer: [
		Smalltalk tools browser openOnClass: class ].

	^ 'OK: browser requested for class ' , className
]

{ #category : 'accessing' }
PharoAgent >> openBrowserOnMethod: aMethodReferenceString [

	| input parts class selector |
	input := aMethodReferenceString trimBoth.
	(parts := input substrings: '>>') size = 2 ifFalse: [
		^ 'ERROR: method reference must look like ClassName>>selector' ].

	class := Smalltalk
		         at: parts first asSymbol
		         ifAbsent: [ ^ 'ERROR: class not found: ' , parts first ].

	selector := parts second trimBoth asSymbol.

	(class includesSelector: selector) ifFalse: [
		^ 'ERROR: selector not found: ' , input ].

	self currentWorld worldState defer: [
		Smalltalk tools browser openOnClass: class selector: selector ].

	^ 'OK: browser requested for method ' , input
]

{ #category : 'accessing' }
PharoAgent >> port [

	^ port
]

{ #category : 'accessing' }
PharoAgent >> port: aPortNumber [

	port := aPortNumber asNumber
]

{ #category : 'accessing' }
PharoAgent >> portFromEnvironment [

	| value |
	value := OSPlatform current environment
		         at: 'PHARO_AGENT_PORT'
		         ifAbsent: [ '4044' ].
	^ value asNumber
]

{ #category : 'accessing' }
PharoAgent >> serveClient: clientSocket [

	| request response |
	[
		request := clientSocket receiveData.
		request := request ifNil: [ '' ] ifNotNil: [ request asString ].

		response := [ self evaluateRequest: request ]
			            on: Exception
			            do: [ :ex | self exceptionStringFor: ex ].

		clientSocket sendData: response asString ] ensure: [
			[ clientSocket close ]
				on: Exception
				do: [ :ex |
						Transcript
							show: ex printString;
							cr ] ]
]

{ #category : 'accessing' }
PharoAgent >> serverLoop [

	[ running ] whileTrue: [
			| clientSocket |
			clientSocket := nil.
			[
				serverSocket waitForConnectionFor: 1.
				running ifFalse: [ ^ self ].

				clientSocket := serverSocket accept.
				clientSocket ifNotNil: [
						[ self serveClient: clientSocket ] forkAt:
							Processor userBackgroundPriority ] ]
				on: Exception
				do: [ :ex |
						running ifTrue: [
								Transcript
									show: '[PharoAgent] accept loop error: ';
									show: ex printString;
									cr ].
						clientSocket ifNotNil: [
								[ clientSocket close ]
									on: Exception
									do: [ :ignored |  ] ] ] ]
]

{ #category : 'accessing' }
PharoAgent >> start [

	running ifTrue: [ ^ self ].

	serverSocket := Socket newTCP.
	serverSocket listenOn: port backlogSize: 10.
	running := true.

	serverProcess := [ self serverLoop ]
		                 forkAt: Processor userBackgroundPriority
		                 named: 'PharoAgent TCP Server'.

	Transcript
		show: '[PharoAgent] listening on ';
		show: port printString;
		cr.

	^ self
]

{ #category : 'accessing' }
PharoAgent >> stop [

	running := false.

	serverSocket ifNotNil: [
			[ serverSocket close ]
				on: Exception
				do: [ :ex |
						Transcript
							show: ex printString;
							cr ].
			serverSocket := nil ].

	serverProcess ifNotNil: [
			[ serverProcess terminate ]
				on: Exception
				do: [ :ex |
						Transcript
							show: ex printString;
							cr ].
			serverProcess := nil ].

	^ self
]
