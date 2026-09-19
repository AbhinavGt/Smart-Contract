# AI Smart Contract Vulnerability Checker

An AI-assisted CLI tool that analyzes a single Solidity contract, finds
security issues with Slither, retrieves relevant vulnerability knowledge, and
generates a human-readable security report.

The project currently includes:

- **V1:** Static analysis, RAG context retrieval, LLM explanations, and reports.
- **V2:** A bounded agentic critic loop that reviews and improves explanations.
- **V3:** Separate security and gas-optimization agents with grouped reports
  and a labeled precision/recall evaluation harness.
- **V4:** Bounded single-function fix generation with scope checks, temporary
  sandboxing, and compilation, interface, and static-analysis verification.

The tool reads contracts and can generate a verified candidate fix, but it
never automatically modifies the original Solidity source file.

## How it works

```text
Solidity file
     |
     v
Slither static analysis
     |
     v
Finding + relevant source lines
     |
     v
RAG vulnerability knowledge retrieval
     |
     v
Security agent + gas-pattern agent
     |
     v
Separate RAG contexts and LLM explanations
     |
     v
V2 critic review and optional retry
     |
     v
V4 fix generation and verification (optional)
     |
     v
Markdown and JSON reports
```

## V1 implementation

For every Slither finding, V1:

1. Runs Slither on the Solidity file.
2. Normalizes the detector output into a consistent finding format.
3. Extracts the relevant source-code snippet.
4. Retrieves related vulnerability information from `knowledge_base/`.
5. Builds a security-auditing prompt.
6. Sends the prompt to Ollama or Anthropic.
7. Writes a Markdown report and optional JSON report.

The generated explanation contains:

- Assessment of whether the issue appears to be a true positive.
- Plain-language risk explanation.
- Example attack scenario.
- Suggested mitigation.

## V2 implementation

V2 adds one logical security-auditor agent with an auditor/critic loop. It is
not a multi-agent system.

After the initial explanation, the critic checks whether it matches the actual
code and returns a structured verdict:

```text
VERDICT: CONFIDENT or UNCERTAIN
REASON: ...
MISSING_CONTEXT: ...
```

If the critic is uncertain, it can request:

- `calling function` — reads additional calling-function context from the
  Solidity file.
- `re-retrieve: <topic>` — performs another RAG search for the requested topic.

The explanation is regenerated with the additional context. The loop stops
when the critic is confident or when the configured safety limit is reached.

Findings include:

- `✅ Confident` when accepted by the critic.
- `⚠️ Needs manual review` when uncertainty remains.
- The number of critic loops used.

The loop limit is configured in `config.yaml`:

```yaml
agent:
  max_loops: 3
```

## V3 implementation

V3 adds a second specialized analysis path for gas efficiency and turns the
project into a small multi-domain orchestrator.

The security pipeline remains the same as V2, but the system now runs an
additional gas-optimization agent in parallel or sequentially, depending on the
configured pipeline mode.

### Gas-analysis agent

The gas agent is implemented in `src/agents/gas_agent.py` and uses source-level
heuristics rather than a separate security detector pipeline. It detects common
patterns such as:

- costly storage-array loops
- redundant storage reads
- redundant storage writes
- long `require` revert strings
- poor struct packing

Each gas finding is processed through the same bounded critic loop used by the
security agent, with a separate gas knowledge base and a distinct prompt style.

### Gas knowledge base

A dedicated knowledge base lives in `knowledge_base_gas/` and is indexed to its
own collection:

- Security collection: `vuln_knowledge`
- Gas collection: `vuln_knowledge_gas`

This separation keeps gas guidance independent from vulnerability guidance and
prevents cross-domain contamination in retrieval.

### Orchestration design

The orchestrator is implemented in `src/pipeline.py` and exposes:

```python
from src.pipeline import orchestrate

result = orchestrate("contracts/reentrancy_example.sol")
# result == {"security": [...], "gas": [...]}
```

This returns a structured result with two domains instead of a single flat list.
The legacy `analyze_contract()` API still works and renders a combined Markdown
report for backwards compatibility.

### Grouped reporting

The formatter now creates a report with clearly separated sections:

- `## Security Findings`
- `## Gas Optimization Findings`

Each finding retains its confidence status from the v2 critic loop, and findings
that remain uncertain are flagged as `⚠️ Needs manual review`.

### Evaluation harness

V3 also adds a labeled evaluation suite under `eval/`:

- `eval/labeled_contracts.yaml`
- `eval/run_eval.py`

The evaluator compares predicted findings against ground truth and computes:

- precision
- recall
- F1 score
- per-vulnerability-type breakdown

This gives the project a reproducible way to measure improvement over time,
which is the key difference between a demo and a testable security tool.

## V4 implementation

V4 adds an optional fix-and-verify pipeline on top of the V3 security findings.
It generates a candidate replacement for one flagged function, checks that the
candidate stays within that function's scope, and verifies it in an isolated
temporary copy of the contract. V4 is a bounded verification system, not an
unrestricted auto-fix engine and not a proof that the resulting contract is
secure.

### Single-function fix generation

The fix pipeline uses a dedicated prompt in `src/prompts.py`:

```python
build_fix_prompt(code_snippet, finding, explanation)
```

It asks the model to return only a corrected version of the vulnerable
function, preserving the function signature. The prompt forbids constructors,
modifiers, state variables, and additional function declarations. If a fix
cannot be made within the flagged function, the model can return
`SCOPE_EXCEEDED` instead of expanding the change.

The generated response must contain a fenced Solidity code block. Prose-only
responses and malformed code are rejected before verification. The pipeline
also checks the extracted code with `check_fix_scope()` before applying it.

### Temp-file sandbox

The fix is applied to a temp copy of the original Solidity file rather than the
real source file. The sandbox logic is implemented in:

- `src/autofix/sandbox.py`
- `apply_fix_to_temp_copy(original_filepath, function_name, fixed_code)`

This guarantees that the app never writes a fix back into the user's original
contract during verification.

### Verification gates

The generated fix passes through three verification gates before it is marked as
verified:

1. **Compilation gate**
   - `check_compiles(filepath)` runs `solc --bin`.
   - If compilation fails, the fix is rejected.
   - One retry is allowed after feeding the compiler output back to the model.

2. **Interface preservation gate**
   - `check_interface_preserved(original, fixed, function_name)` compares the ABI
     for the target function.
   - It rejects changes to the function name, input types, output types,
     visibility, or state mutability.

3. **Static-analysis re-check**
   - `check_vulnerability_resolved(original_findings, fixed_filepath)` reruns
     Slither on the fixed temp file.
   - The original issue must no longer appear for the same function.
   - Any newly introduced findings are reported as warnings.

Scope validation runs before these gates. A scope violation is reported as
`Not attempted` rather than as a successful or ordinary failed fix.

### LLM provenance and fallback behavior

V4 preserves the source of generated output in Markdown and JSON reports.
Fixes and explanations produced by the deterministic offline fallback are
explicitly labeled and are not treated as real LLM results. Strict CLI mode
requires the configured Ollama or Anthropic backend; use
`--allow-offline-fallback` only for offline testing.

### Orchestration

The fix pipeline is implemented in:

- `src/autofix/pipeline.py`
- `generate_verified_fix(...)`

It returns a structured result like:

```python
{
  "status": "verified",
  "gates_passed": ["compilation", "interface_preserved", "static_analysis"],
  "fixed_code": "...",
  "diff": "...",
  "new_findings_introduced": []
}
```

If a gate fails, the result is marked as failed and includes the gate name and
reason instead of pretending the fix is valid.

### Report integration

The formatter includes a `Suggested Fix` section when fix metadata is attached
to a finding. Verified fixes show their diff and gate list. Failed fixes show
which gate failed and why, while out-of-scope candidates are shown as
`Not attempted`. This is intentionally explicit so the tool does not hide the
limitations of auto-fix generation or confuse mechanical verification with
semantic proof.

### CLI usage

To generate a fix for the first security finding:

```bash
python main.py \
  --file contracts/reentrancy_example.sol \
  --output report.md \
  --fix \
  --fix-index 0
```

This writes the standard report and prints the verified fix diff to the console
when the verification gates pass. To select a different finding, change
`--fix-index`; the index refers to the security findings in the report.

## Installation

Python 3.10 or newer is recommended.

```bash
cd /home/a8hi9t/Work/smart-contract
python -m pip install -r requirements.txt
```

Slither also needs a compatible Solidity compiler. For example:

```bash
pip install solc-select
solc-select install 0.8.20
solc-select use 0.8.20
```

## Build the knowledge index

Run this once after adding or changing documents in `knowledge_base/`:

```bash
python -m src.rag.build_index
```

Build the independent gas knowledge collection when gas guidance changes:

```bash
python -c "from src.rag.build_index import build_gas_index; print(build_gas_index())"
```

ChromaDB and SentenceTransformers are used when installed. If they are not
available, the project uses a local JSON token-search fallback.
Security retrieval uses `vuln_knowledge`; gas retrieval uses
`vuln_knowledge_gas` and never mixes the two collections.

## Run the application

The default command generates a Markdown report:

```bash
python main.py \
  --file contracts/reentrancy_example.sol \
  --output report.md
```

Generate both Markdown and JSON reports:

```bash
python main.py \
  --file contracts/reentrancy_example.sol \
  --output report.md \
  --json-output report.json
```

Generate and verify a candidate fix for the first security finding:

```bash
python main.py \
  --file contracts/reentrancy_example.sol \
  --output v4-report.md \
  --json-output v4-report.json \
  --fix \
  --fix-index 0
```

The fix index selects a security finding from the report. V4 only changes a
temporary copy during verification and prints a unified diff when all gates
pass. It does not write the candidate fix to the input contract.

The CLI displays progress while it runs:

```text
Running static analysis...
Retrieving context...
Generating explanations...
Wrote report to report.md
Wrote JSON report to report.json
```

Reports contain separate **Security Findings** and **Gas Optimization
Findings** sections. Structured callers can use
`src.pipeline.orchestrate(path)`, which returns
`{"security": [...], "gas": [...]}`. `analyze_contract(path)` remains a
backwards-compatible Markdown API.

If Ollama is unavailable and you are intentionally testing the offline path,
enable the deterministic fallback explicitly:

```bash
python main.py \
  --file contracts/reentrancy_example.sol \
  --output offline-report.md \
  --allow-offline-fallback
```

Fallback explanations and fixes are labeled in the reports and must not be
treated as live-model security advice.

Run the labeled evaluation (Slither/compiler availability is required for
real findings):

```bash
python eval/run_eval.py
```

The evaluator uses a one-to-one matching rule: normalized finding type and,
when provided, function name must both match. It prints overall and per-type
precision, recall, and F1.

## LLM configuration

Ollama is the default backend:

```yaml
llm:
  backend: ollama
  model: qwen2.5-coder:7b
  base_url: http://localhost:11434
  timeout_seconds: 60
```

Start Ollama and download the model configured in `config.yaml` before running
the application:

```bash
ollama serve
ollama pull qwen2.5-coder:7b
```

The Ollama client checks the `/api/tags` endpoint before strict-mode analysis.
V4 generation also uses bounded output settings and requires a fenced Solidity
response so prose or malformed model output is rejected.

Anthropic can be selected in `config.yaml`:

```yaml
llm:
  backend: anthropic
  model: claude-sonnet-4-6
```

Then configure the API key:

```bash
export ANTHROPIC_API_KEY="your-api-key"
```

By default, the CLI fails before static analysis when the configured LLM
backend is unavailable. Use `--allow-offline-fallback` only for offline
testing; generated findings, explanations, and fixes are labeled as fallback
output, and the evaluation harness rejects aggregate metrics from such runs.

## Offline RAG retrieval

The CLI uses the local JSON knowledge indexes by default. This avoids trying
to download `all-MiniLM-L6-v2` from Hugging Face during an offline run. The
Chroma/sentence-transformers path is still available when the model is already
cached or network access is available:

```bash
export SMART_CONTRACT_USE_EMBEDDINGS=1
```

## Project structure

```text
contracts/              Sample Solidity contracts
knowledge_base/         Vulnerability reference documents
src/static_analysis.py  Slither integration
src/rag/                Knowledge indexing and retrieval
src/llm/                Ollama, Anthropic, and offline clients
src/prompts.py          Explanation, critic, and V4 fix prompts
src/agents/gas_agent.py Gas pattern detector and gas critic loop
src/autofix/            Fix generation and verification pipeline
src/pipeline.py         V1/V2 logic and V3/V4 orchestrator
src/report/             Markdown and JSON formatting
knowledge_base_gas/     Gas optimization reference documents
eval/                   Ground-truth labels and evaluation script
main.py                 CLI entrypoint
config.yaml             Runtime configuration
V4_IMPLEMENTATION_REPORT.md
                        Detailed V4 architecture and verification report
```

## Current limitations

- Only one Solidity file is analyzed at a time.
- Slither and a compatible Solidity compiler are required for real static
  analysis.
- V2 uses one LLM with separate auditor and critic roles; it does not run
  multiple independent agents.
- Findings marked for manual review still require a human auditor.
- V4 generates and verifies candidate fixes but does not apply them to the
  original Solidity file.
- V4 supports one target function per fix attempt. Changes requiring a
  constructor, modifier, state variable, or multiple functions are rejected as
  out of scope.
- V4 verification is mechanical: compilation, ABI comparison, and Slither
  results do not prove behavioral equivalence or complete security.
- Live Ollama or Anthropic access is required for strict-mode LLM output.
  Offline fallback output is for testing and is not equivalent to an LLM audit.
- Whole-project analysis, automatic application of fixes, web UI, and automatic
  PR creation are not implemented. Gas checks remain heuristic and require
  manual review for context-sensitive optimizations.
- Front-running/MEV-style vulnerabilities are not reliably detected by this
  tool, as they depend on transaction-ordering context that Slither's static
  detectors do not analyze.
