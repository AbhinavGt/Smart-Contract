# AI Smart Contract Vulnerability Checker

An AI-assisted CLI tool that analyzes a single Solidity contract, finds
security issues with Slither, retrieves relevant vulnerability knowledge, and
generates a human-readable security report.

The project currently includes:

- **V1:** Static analysis, RAG context retrieval, LLM explanations, and reports.
- **V2:** A bounded agentic critic loop that reviews and improves explanations.

The tool reads contracts only. It does not automatically modify Solidity code.

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
LLM security explanation
     |
     v
V2 critic review and optional retry
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

## Installation

Python 3.10 or newer is recommended.

```bash
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

ChromaDB and SentenceTransformers are used when installed. If they are not
available, the project uses a local JSON token-search fallback.

## Run the application

Generate a Markdown report:

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

The CLI displays progress while it runs:

```text
Running static analysis...
Retrieving context...
Generating explanations...
Wrote report to report.md
Wrote JSON report to report.json
```

## LLM configuration

Ollama is the default backend:

```yaml
llm:
  backend: ollama
  model: deepseek-coder
  base_url: http://localhost:11434
```

Start Ollama and download the configured model before running the application:

```bash
ollama pull deepseek-coder
```

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

If the configured LLM is unavailable, the application uses a deterministic
offline explanation so the pipeline can still be tested. This fallback is not
a substitute for a real security review.

## Project structure

```text
contracts/              Sample Solidity contracts
knowledge_base/         Vulnerability reference documents
src/static_analysis.py  Slither integration
src/rag/                Knowledge indexing and retrieval
src/llm/                Ollama, Anthropic, and offline clients
src/prompts.py          Explanation and critic prompts
src/pipeline.py         V1 pipeline and V2 critic loop
src/report/             Markdown and JSON formatting
main.py                 CLI entrypoint
config.yaml             Runtime configuration
```

## Current limitations

- Only one Solidity file is analyzed at a time.
- Slither and a compatible Solidity compiler are required for real static
  analysis.
- V2 uses one LLM with separate auditor and critic roles; it does not run
  multiple independent agents.
- Findings marked for manual review still require a human auditor.
- The tool does not apply automatic fixes.
- Whole-project analysis, gas optimization, web UI, and automatic PR creation
  are not implemented.
