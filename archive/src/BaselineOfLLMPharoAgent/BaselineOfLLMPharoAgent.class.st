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
			spec baseline: 'PharoLLMIcon' with: [ spec repository: 'github://pharo-llm/pharo-llm-icon:main/src' ].
			spec baseline: 'LLMPharoMCP' with: [ spec repository: 'github://pharo-llm/pharo-mcp:main/src' ].
			spec
				package: 'LLM-Pharo-Agent';
				package: 'LLM-Pharo-Agent-Tests' with: [ spec requires: #( 'LLM-Pharo-Agent' ) ] ]
]
