Class {
	#name : 'PharoAgentTest',
	#superclass : 'TestCase',
	#instVars : [
		'agent'
	],
	#category : 'LLM-Pharo-Agent-Tests',
	#package : 'LLM-Pharo-Agent-Tests'
}

{ #category : 'running' }
PharoAgentTest >> setUp [

	super setUp.
	agent := PharoAgent new
]

{ #category : 'running' }
PharoAgentTest >> testEvaluateRequestForEmptyInputReturnsEmptyString [

	self assert: (agent evaluateRequest: '   ') equals: ''
]

{ #category : 'running' }
PharoAgentTest >> testEvaluateRequestRejectsMalformedMethodReference [

	self
		assert: (agent evaluateRequest: 'OPEN_METHOD_BROWSER String')
		equals: 'ERROR: method reference must look like ClassName>>selector'
]

{ #category : 'running' }
PharoAgentTest >> testEvaluateRequestTrimsAndEvaluatesSource [

	self assert: (agent evaluateRequest: ' 3 + 4 ') equals: '7'
]

{ #category : 'running' }
PharoAgentTest >> testEvaluateReturnsNilAsString [

	self assert: (agent evaluate: 'nil') equals: 'nil'
]

{ #category : 'running' }
PharoAgentTest >> testEvaluateReturnsPrintedResult [

	self assert: (agent evaluate: '1 + 2') equals: '3'
]

{ #category : 'running' }
PharoAgentTest >> testExceptionStringForErrorUsesClassAndMessage [

	| exception description |
	exception := [ Error signal: 'boom' ] on: Error do: [ :ex | ex ].
	description := agent exceptionStringFor: exception.

	self assert: description equals: 'Error: boom'
]

{ #category : 'running' }
PharoAgentTest >> testOpenBrowserOnClassNamedUnknownClassReturnsError [

	self
		assert: (agent openBrowserOnClassNamed: 'DefinitelyNotAClass')
		equals: 'ERROR: class not found: DefinitelyNotAClass'
]

{ #category : 'running' }
PharoAgentTest >> testOpenBrowserOnMethodRejectsUnknownClass [

	self
		assert: (agent openBrowserOnMethod: 'DefinitelyNotAClass>>size')
		equals: 'ERROR: class not found: DefinitelyNotAClass'
]

{ #category : 'running' }
PharoAgentTest >> testOpenBrowserOnMethodRejectsUnknownSelector [

	self
		assert: (agent openBrowserOnMethod: 'String>>definitelyMissingSelector')
		equals: 'ERROR: selector not found: String>>definitelyMissingSelector'
]

{ #category : 'running' }
PharoAgentTest >> testPortSetterNormalizesToNumber [

	agent port: '5050'.

	self assert: agent port equals: 5050
]
