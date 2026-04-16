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
				package: 'LLM-Pharo-Agent';
				package: 'LLM-Pharo-Agent-Tests' with: [ spec requires: #( 'LLM-Pharo-Agent' ) ] ]
]
