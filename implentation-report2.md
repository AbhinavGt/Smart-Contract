Version 2 adds an agentic critic loop on top of the existing v1 pipeline.

Main changes

• Generates an initial explanation for each Slither finding.
• Sends that explanation to a critic model for review.
• The critic returns:
•  CONFIDENT , or
•  UNCERTAIN 
• When uncertain, the critic can request:
• More code context from a calling function.
• New vulnerability context from the RAG knowledge base.
• The explanation is regenerated using the additional context.
• The loop is limited by  agent.max_loops  in  config.yaml .
• Findings include:
• Confidence status
• Number of critic loops used
• Final explanation
• Reports now include:
•  ✅ Confident 
•  ⚠️ Needs manual review 
• A review-needed summary at the top
• Solidity files remain read-only; the application does not automatically apply fixes.

Possible Manual Workarounds

The implementation has offline fallbacks, but these external tools may still require manual setup for full functionality:

1. Slither and Solidity compiler

Install Slither:

pip install slither-analyzer

Install and configure a compatible Solidity compiler, commonly using  solc-select :

pip install solc-select
solc-select install 0.8.20
solc-select use 0.8.20

Without Slither, the application exits with a clear installation error.

2. RAG dependencies

For semantic retrieval, install:

pip install chromadb sentence-transformers

If these are unavailable, the app uses the generated JSON token-based index instead. This fallback is functional but less accurate than embeddings.

Build the index with:

python -m src.rag.build_index

3. LLM backend

The default backend is Ollama. Install Ollama, start it, and pull the configured model:

ollama pull deepseek-coder

If Ollama is unavailable, the application generates a deterministic offline explanation. This allows testing, but it is not a real model-generated security assessment.

For Anthropic instead, update  config.yaml :

llm:
  backend: anthropic
  model: claude-sonnet-4-6

Then set the API key:

export ANTHROPIC_API_KEY="your-api-key"

If the key or API is unavailable, the offline fallback is used.

4. Manual review findings

A finding marked:

⚠️ Needs manual review

means the critic did not become confident within the configured loop limit or returned an incomplete response. These findings should be reviewed by a human auditor.

How to Produce Output

From the project directory:

cd /home/a8hi9t/Work/smart-contract

Build or refresh the RAG index:

python -m src.rag.build_index

Run the v2 analysis:

python main.py \
  --file contracts/reentrancy_example.sol \
  --output report.md \
  --json-output report.json

The CLI displays progress:

Running static analysis...
Retrieving context...
Generating explanations...
Wrote report to report.md
Wrote JSON report to report.json

Output files

•  report.md  — human-readable Markdown security report.
•  report.json  — machine-readable findings, explanations, confidence status, and loop counts.

Example report structure:

# Security Report: reentrancy_example.sol

## Needs manual review

- Finding 1: reentrancy-eth (loops: 2)

## Finding 1: reentrancy-eth — Severity: High — ✅ Confident
**Location:** withdraw, lines 8, 9

**Critic loops:** 2

### Assessment
...

To analyze another sample:

python main.py \
  --file contracts/access_control_example.sol \
  --output access-control-report.md \
  --json-output access-control-report.json

You can adjust the critic safety limit in  config.yaml :

agent:
  max_loops: 3
# tell me how is agentic working in this??

The agentic behavior is implemented as a bounded self-review and retry loop for each vulnerability finding.

How it works

1. Initial analysis
• Slither identifies a finding, such as reentrancy.
• The pipeline extracts the relevant Solidity code.
• RAG retrieves related vulnerability information.
• The LLM generates an initial explanation.
2. Critic evaluation
• The same LLM receives the code, finding, and explanation.
• It must respond with:
VERDICT: CONFIDENT or UNCERTAIN
REASON: ...
MISSING_CONTEXT: ...
3. The model chooses the next action
• If it returns:
VERDICT: CONFIDENT
the explanation is accepted.
• If it returns:
VERDICT: UNCERTAIN
MISSING_CONTEXT: calling function
the system reads additional calling-function context from the Solidity file.
• If it returns:
MISSING_CONTEXT: re-retrieve: integer overflow patterns
the system performs another RAG search using that topic.
• The explanation is then regenerated using the new context.
4. Safety limit
• The process cannot run forever.
•  agent.max_loops  controls the maximum number of critic iterations:
agent:
  max_loops: 3
• If the limit is reached without confidence, the finding is marked:
⚠️ Needs manual review

Why this is agentic

The next action is not always fixed. The critic’s response determines whether the system:

• Accepts the explanation.
• Fetches more source-code context.
• Performs a different RAG query.
• Tries the explanation again.
• Stops and requests manual review.

That adaptive decision-making is the agentic part.

Example

For a reentrancy finding:

Initial explanation
        ↓
Critic: UNCERTAIN
Missing context: calling function
        ↓
Fetch caller code
        ↓
Generate improved explanation
        ↓
Critic: CONFIDENT
        ↓
Accept final report

For an uncertain RAG result:

Initial explanation
        ↓
Critic: UNCERTAIN
Missing context: re-retrieve: checks effects interactions
        ↓
Search the knowledge base again
        ↓
Generate improved explanation
        ↓
Critic: CONFIDENT or manual review

It is a single agent with a critic/reasoning loop, not a multi-agent system. The available actions are intentionally limited to read-only code lookup and RAG retrieval. Also, if Ollama or Anthropic is unavailable, the deterministic fallback cannot produce proper critic verdicts, so findings will generally reach the loop limit and be marked for manual review.

# how many agents have been implemented and how is each agent working?
Thought for 3s

Only one logical AI agent has been implemented: the Smart Contract Security Auditor Agent.

It operates through multiple roles in a bounded loop, but these are not separate independent agents.

1. Auditor role

For each Slither finding, the agent:

• Receives the vulnerability type, severity, description, and function.
• Reads the relevant Solidity code.
• Retrieves related vulnerability information from the RAG knowledge base.
• Generates an initial explanation containing:
• Assessment
• Risk
• Exploit example
• Suggested fix

2. Critic role

The same configured LLM then reviews its own explanation.

It checks whether:

• The explanation matches the actual Solidity code.
• The vulnerability is correctly described.
• Important context is missing.
• The suggested fix is appropriate.

It returns a structured verdict:

VERDICT: CONFIDENT or UNCERTAIN
REASON: ...
MISSING_CONTEXT: ...

3. Context-fetching tool

This is not an agent. It is a tool controlled by the critic’s decision.

It supports:

•  calling function 
• Searches the source file for relevant function/call context.
•  re-retrieve: <topic> 
• Runs another RAG query using the requested topic.

The new context is passed back to the auditor role for another explanation.

Execution flow

Slither finding
      ↓
Auditor generates explanation
      ↓
Critic reviews explanation
      ↓
 ┌───────────────┬──────────────────┐
 │ CONFIDENT     │ UNCERTAIN        │
 │ Accept result │ Request context  │
 └───────────────┴────────┬─────────┘
                          ↓
                Fetch code or RAG context
                          ↓
                Generate improved explanation

The loop is limited by:

agent:
  max_loops: 3

If the critic remains uncertain after the limit, the finding is marked:

⚠️ Needs manual review

Components that are not agents

These are supporting components:

• Slither: Static analyzer, not an AI agent.
• RAG retriever: Searches vulnerability documentation, not an agent.
• Ollama/Anthropic client: LLM communication layer.
• Report formatter: Converts findings into Markdown or JSON.
• Context-fetching function: Read-only tool used by the agent.

Therefore, the current version contains one agent with an auditor-and-critic loop, not multiple agents or a multi-agent architecture.

# Is there scope for multi agent is so give example of the use
Thought for 4s

Yes, there is strong scope for a multi-agent architecture, especially for improving accuracy and separating responsibilities. The current v2 uses one LLM with auditor and critic roles; a future version could use several specialized agents.

Example multi-agent design

┌──────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Agent                        │ Responsibility                                                                                      │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Static Analysis Agent        │ Runs Slither and organizes detector findings.                                                       │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Vulnerability Analysis Agent │ Determines whether each finding is a true positive by examining the Solidity code.                  │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ RAG Research Agent           │ Retrieves relevant SWC documentation, exploit examples, and mitigation patterns.                    │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Exploit Simulation Agent     │ Constructs a hypothetical attack path or proof-of-concept reasoning without modifying the contract. │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Remediation Agent            │ Suggests a specific secure coding fix and explains its tradeoffs.                                   │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Review Agent                 │ Compares the outputs of the other agents, resolves disagreements, and assigns final confidence.     │
├──────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Report Agent                 │ Produces the final Markdown and JSON reports.                                                       │
└──────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────┘

Example workflow

Solidity contract
       ↓
Static Analysis Agent
       ↓
 ┌─────────────────────┬─────────────────────┬─────────────────────┐
 │ Vulnerability Agent │ RAG Research Agent  │ Exploit Agent       │
 │ Reviews code        │ Finds context       │ Checks attack path  │
 └─────────────────────┴─────────────────────┴─────────────────────┘
       ↓
Remediation Agent
       ↓
Review Agent
       ↓
Report Agent

For a reentrancy finding:

1. The Static Analysis Agent detects an external call before a balance update.
2. The Vulnerability Analysis Agent checks whether the state transition is actually exploitable.
3. The RAG Research Agent retrieves information about checks-effects-interactions and reentrancy guards.
4. The Exploit Simulation Agent checks whether an attacker-controlled contract can call back into  withdraw .
5. The Remediation Agent recommends moving the balance update before the external call or using a reentrancy guard.
6. The Review Agent compares all conclusions and marks the finding as confident or requiring manual review.
7. The Report Agent creates the final output.

Why multiple agents could help

• Specialization: Each agent focuses on one task.
• Independent verification: Multiple agents can challenge one another.
• Better false-positive handling: Code analysis and exploit reasoning can be compared.
• Parallel execution: Independent research tasks can run simultaneously.
• More detailed reports: Separate agents can provide technical, exploit, and remediation perspectives.

Important limitation

Multi-agent systems also introduce:

• More LLM calls and higher cost
• Longer execution time
• Possible disagreement between agents
• More complex orchestration
• Need for a final authority to resolve conflicts

A practical next version could begin with three agents:

Auditor Agent → Research Agent → Reviewer Agent

The existing v2 critic loop could become the Reviewer Agent, while the current explanation generation becomes the Auditor Agent. This would provide a natural upgrade path without redesigning the entire application.

