Class {
	#name : 'BaselineOfLLMPharoAgent',
	#superclass : 'BaselineOf',
	#category : 'BaselineOfLLMPharoAgent',
	#package : 'BaselineOfLLMPharoAgent'
}

{ #category : 'baselines' }
BaselineOfLLMPharoAgent >> baseline: spec [

	<baseline>
	spec for: #common do: [
		spec
			package: 'LLM-PharoAgent';
			package: 'LLM-PharoAgent-Tests'
			with: [ spec requires: #( 'LLM-PharoAgent' ) ].
			]
]
