Class {
	#name : 'PharoAgent',
	#superclass : 'Object',
	#instVars : [
		'serverSocket',
		'port',
		'running'
	],
	#classInstVars : [
		'defaultInstance'
	],
	#category : 'LLM-Pharo-Agent',
	#package : 'LLM-Pharo-Agent'
}

{ #category : 'accessing' }
PharoAgent class >> default [

	^ defaultInstance ifNil: [ defaultInstance := self new ]
]

{ #category : 'accessing' }
PharoAgent class >> portFromEnvironment [

	| value |
	value := Smalltalk platform environment
		at: 'PHARO_CLI_PORT'
		ifAbsent: [ '4044' ].
	^ value asNumber
]

{ #category : 'accessing' }
PharoAgent class >> resetDefault [

	defaultInstance ifNotNil: [
		[ defaultInstance stop ] on: Exception do: [ :ex | Transcript show: ex printString; cr ]
	].
	defaultInstance := nil
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
PharoAgent class >> startOn: aPortNumber [

	| server |
	server := self default.
	server port: aPortNumber.
	server start.
	^ server

]

{ #category : 'accessing' }
PharoAgent class >> stop [

	defaultInstance ifNotNil: [ defaultInstance stop ]
]

{ #category : 'initialization' }
PharoAgent >> evaluate: aString [

	| result |
	result := OpalCompiler new
		source: aString;
		evaluate.
	^ result printString
]

{ #category : 'initialization' }
PharoAgent >> exceptionStringFor: anException [

	^ String streamContents: [ :stream |
		stream
			nextPutAll: anException class name;
			nextPutAll: ': '.
		anException messageText
			ifNil: [ stream nextPutAll: anException printString ]
			ifNotNil: [ stream nextPutAll: anException messageText ]
	]
]

{ #category : 'initialization' }
PharoAgent >> initialize [

	super initialize.
	port := 4044.
	running := false.
]

{ #category : 'initialization' }
PharoAgent >> isRunning [

	^ running
]

{ #category : 'initialization' }
PharoAgent >> port [

	^ port
]

{ #category : 'initialization' }
PharoAgent >> port: aPortNumber [

	port := aPortNumber asNumber
]

{ #category : 'initialization' }
PharoAgent >> serveClient: clientSocket [

	| request response |
	[
		request := clientSocket receiveData.
		request ifNil: [ request := '' ] ifNotNil: [ request := request asString ].

		response := [ self evaluate: request ]
			on: Exception
			do: [ :ex | self exceptionStringFor: ex ].

		clientSocket sendData: response
	] ensure: [
		[ clientSocket closeAndDestroy ] on: Exception do: [ :ex | Transcript show: ex printString; cr ]
	]
]

{ #category : 'initialization' }
PharoAgent >> start [

	running ifTrue: [ ^ self ].

	serverSocket := Socket newTCP.
	serverSocket listenOn: port backlogSize: 10.
	running := true.

	Transcript
		show: '[PharoCLIServer] listening on '; show: port printString; cr.

	[ running ] whileTrue: [
		| clientSocket |
		[
			clientSocket := serverSocket waitForAcceptFor: 1.
			clientSocket ifNotNil: [
				[ self serveClient: clientSocket ] forkAt: Processor userBackgroundPriority
			]
		] on: Exception do: [ :ex |
			running ifTrue: [
				Transcript
					show: '[PharoCLIServer] accept loop error: ';
					show: ex printString;
					cr
			]
		]
	].

	^ self
]

{ #category : 'initialization' }
PharoAgent >> stop [

	running := false.
	serverSocket ifNotNil: [
		[ serverSocket closeAndDestroy ] on: Exception do: [ :ex | Transcript show: ex printString; cr ].
		serverSocket := nil
	].
	^ self
]
