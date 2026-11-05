Class {
	#name : 'PharoMcpServerRunTestsFixture',
	#superclass : 'TestCase',
	#category : 'LLM-Pharo-Agent-Tests',
	#package : 'LLM-Pharo-Agent-Tests'
}

{ #category : 'tests' }
PharoMcpServerRunTestsFixture >> testFailsOnPurpose [

	self
		assert: false
		description: 'intentional failure for runTests fixture'
]

{ #category : 'tests' }
PharoMcpServerRunTestsFixture >> testPasses [

	self assert: 1 + 1 equals: 2
]
