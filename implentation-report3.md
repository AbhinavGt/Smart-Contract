How the V3 agents work

• Security agent:
• Reuses the V2 logic.
• Runs Slither on the Solidity file.
• Extracts findings.
• Fetches security RAG context.
• Builds security explanation prompts.
• Runs the critic loop to decide whether the explanation is confident or uncertain.
• Returns a list of normalized security findings.
• Gas agent:
• Runs independently from Slither’s security detectors.
• Uses heuristic source-pattern checks for likely gas inefficiencies.
• Examples include:
• costly loops over storage arrays
• repeated storage reads
• repeated storage writes
• large revert strings
• poor struct packing
• Retrieves contextual gas-optimization guidance from  knowledge_base_gas/ 
• Uses the same bounded critic loop style as V2 to decide if the gas explanation is trustworthy.

Orchestration pattern

The orchestrator is implemented in  src/pipeline.py  and follows this pattern:

•  run_security_agent(filepath) :
• executes the security pipeline
• returns only security findings
•  run_gas_agent(filepath) :
• executes the gas pipeline
• returns only gas findings
•  merge_findings(security_findings, gas_findings) :
• packages them into a dictionary:
{
  "security": [...],
  "gas": [...]
}
•  orchestrate(filepath) :
• calls both agents
• combines their output
• optionally runs them concurrently if enabled in config

This is a classic “two specialized agents + shared orchestrator” pattern:

• each agent is responsible for a separate concern
• the orchestrator merges their results
• reporting then split them into separate sections

Why this counts as multi-agent orchestration

It is not one agent doing multiple jobs in sequence; it is:

• one domain-specific security agent
• one domain-specific gas agent
• one controlling orchestrator

The important distinction is that the system does not collapse everything into a single flat list. It keeps security and gas analysis separate, then merges them at the top level. That makes the architecture easier to reason about and more realistic as a portfolio-level multi-agent design.

Execution flow

Contract file
   |
   v
Security agent
   |         \
   |          \
   v           v
Slither     Gas detector
   |          |
   v          v
RAG context  Gas RAG context
   |          |
   v          v
Critic review
   |
   v
Orchestrator merges
   |
   v
Markdown/JSON report

The config option for concurrency is in  config.yaml :

pipeline:
  concurrent: false

When enabled, the two agents can be run in parallel via  ThreadPoolExecutor , though the project keeps the default simple and safe.

V3 changes made

• Added a separate gas-optimization analysis path.
• New file:  src/agents/gas_agent.py 
• Detects heuristic gas issues such as:
• costly loops over storage arrays
• redundant storage reads
• redundant storage writes
• long  require  strings
• poor struct packing
• Added a dedicated gas knowledge base.
• Directory:  knowledge_base_gas/ 
• Separate gas vector collection:  vuln_knowledge_gas 
• Added isolated gas retrieval support.
• Updated retrieval logic to support separate collections.
• Security and gas knowledge are kept in different indexes.
• Added orchestrator logic.
•  run_security_agent() 
•  run_gas_agent() 
•  merge_findings() 
•  orchestrate() 
•  src/pipeline.py  now returns:
{"security": [...], "gas": [...]}
• Updated the report formatter.
• Reports now show separate sections:
•  ## Security Findings 
•  ## Gas Optimization Findings 
• Confidence markers are preserved:
•  ✅ Confident 
•  ⚠️ Needs manual review 
• Kept backward compatibility.
•  analyze_contract()  still works and returns Markdown output for older usage.
• Added evaluation support.
•  eval/labeled_contracts.yaml 
•  eval/run_eval.py 
• Measures precision, recall, and F1 per type and overall
• Updated project configuration.
•  config.yaml  now includes gas settings and orchestration settings.
• Updated documentation.
•  README.md  now includes the V3 architecture and usage.
• Added clean/gas sample contracts.
• Used to support testing and evaluation.

Validation completed

• Python compilation passed
• Gas detector smoke test passed
• Separate gas/security retrieval passed
• Orchestration output passed
• Evaluation script ran successfully
• The only remaining limitation is environmental:
• Full Slither-based security evaluation requires Slither and a compatible Solidity compiler installed in the environment


