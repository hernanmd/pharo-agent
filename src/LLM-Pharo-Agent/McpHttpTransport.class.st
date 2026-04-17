Class {
	#name : 'McpHttpTransport',
	#superclass : 'MCPTransport',
	#instVars : [
		'port',
		'path',
		'server',
		'responseHolders',
		'responseMutex'
	],
	#category : 'LLM-Pharo-Agent',
	#package : 'LLM-Pharo-Agent'
}

{ #category : 'as yet unclassified' }
McpHttpTransport class >> defaultPath [

	^ '/mcp'
]

{ #category : 'as yet unclassified' }
McpHttpTransport class >> defaultPort [

	^ 4046
]

{ #category : 'as yet unclassified' }
McpHttpTransport class >> port: aPort [

	^ self new
		  port: aPort;
		  yourself
]

{ #category : 'as yet unclassified' }
McpHttpTransport class >> port: aPort path: aPath [

	^ self new
		  port: aPort;
		  path: aPath;
		  yourself
]

{ #category : 'private' }
McpHttpTransport >> clearResponseHolder [

	responseMutex critical: [
		responseHolders removeKey: Processor activeProcess ifAbsent: [  ] ]
]

{ #category : 'private' }
McpHttpTransport >> dispatchBody: aBodyString [
	"Run the message handler for one request body and return the raw
	 JSON response string, or nil if the handler produced no response
	 (e.g. the message was a JSON-RPC notification)."

	| holder |
	holder := Array new: 1.
	self registerResponseHolder: holder.
	[
	messageHandler ifNotNil: [ messageHandler value: aBodyString ] ]
		ensure: [ self clearResponseHolder ].
	^ holder first
]

{ #category : 'private' }
McpHttpTransport >> handleRequest: aZnRequest [
	"Handle one Zinc HTTP request and return the ZnResponse to send back."

	| body responseString |
	aZnRequest method = 'POST' ifFalse: [
		^ ZnResponse methodNotAllowed: aZnRequest ].

	aZnRequest uri path = path ifFalse: [
		^ ZnResponse notFound: aZnRequest uri ].

	body := aZnRequest hasEntity
		        ifTrue: [ aZnRequest entity string ]
		        ifFalse: [ '' ].

	responseString := [ self dispatchBody: body ]
		                  on: Error
		                  do: [ :ex | self jsonErrorFor: ex ].

	responseString ifNil: [ ^ self noContentResponse ].

	^ ZnResponse ok: (ZnEntity
			   with: responseString
			   type: ZnMimeType applicationJson)
]

{ #category : 'private' }
McpHttpTransport >> initialize [

	super initialize.
	port := self class defaultPort.
	path := self class defaultPath.
	running := false.
	responseHolders := IdentityDictionary new.
	responseMutex := Mutex new
]

{ #category : 'private' }
McpHttpTransport >> isRunning [

	^ running
]

{ #category : 'private' }
McpHttpTransport >> jsonErrorFor: anException [
	"Build a JSON-RPC parse-error envelope for an exception that escaped
	 the normal dispatch path. With id=null since we don't know the id."

	^ STONJSON toString: (OrderedDictionary new
			   at: 'jsonrpc' put: '2.0';
			   at: 'id' put: nil;
			   at: 'error' put: (OrderedDictionary new
					    at: 'code' put: MCPConstants errorCodeInternalError;
					    at: 'message' put: anException messageText;
					    yourself);
			   yourself)
]

{ #category : 'private' }
McpHttpTransport >> noContentResponse [
	"Return an empty JSON object with HTTP 200. JSON-RPC notifications
	 expect no content, but 200 with {} is the most widely compatible
	 response across MCP HTTP clients."

	^ ZnResponse ok: (ZnEntity
			   with: '{}'
			   type: ZnMimeType applicationJson)
]

{ #category : 'accessing' }
McpHttpTransport >> path [

	^ path
]

{ #category : 'accessing' }
McpHttpTransport >> path: aString [

	path := aString
]

{ #category : 'accessing' }
McpHttpTransport >> port [

	^ port
]

{ #category : 'accessing' }
McpHttpTransport >> port: aPortNumber [

	port := aPortNumber asNumber
]

{ #category : 'private' }
McpHttpTransport >> registerResponseHolder: anArray [

	responseMutex critical: [
		responseHolders at: Processor activeProcess put: anArray ]
]

{ #category : 'operations' }
McpHttpTransport >> sendMessage: aJsonString [
	"Stash the response string in the holder registered for the current
	 request-handling process. The HTTP dispatcher picks it up after the
	 message handler returns."

	| holder |
	holder := responseMutex critical: [
		          responseHolders
			          at: Processor activeProcess
			          ifAbsent: [ nil ] ].
	holder ifNotNil: [ holder at: 1 put: aJsonString ]
]

{ #category : 'operations' }
McpHttpTransport >> server [

	^ server
]

{ #category : 'operations' }
McpHttpTransport >> start [

	running ifTrue: [ ^ self ].
	server := ZnServer on: port.
	server onRequestRespond: [ :request | self handleRequest: request ].
	server start.
	running := true
]

{ #category : 'operations' }
McpHttpTransport >> stop [

	running := false.
	server ifNotNil: [
		[ server stop ]
			on: Error
			do: [ :ex | "swallow stop errors" ].
		server := nil ]
]
