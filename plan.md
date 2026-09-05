# AI Smart Contract Vulnerability Checker — v1 Implementation Plan

## Project Goal
Build a prototype that takes a single Solidity (`.sol`) file, runs static analysis on it, retrieves relevant vulnerability context via RAG, and produces an LLM-generated, human-readable security report with severity, explanation, and suggested fix.

Scope is intentionally narrow for v1: single-file contracts only, no auto-fix, no web frontend (CLI or Streamlit is enough).

---

## Tech Stack

- **Language:** Python 3.10+
- **Static analysis:** Slither (`pip install slither-analyzer`)
- **Solidity compiler:** `solc` (install via `solc-select` to manage versions)
- **Embeddings:** `sentence-transformers` — model `all-MiniLM-L6-v2` (local, free, no API key needed)
- **Vector store:** ChromaDB (local, file-based, no server needed)
- **LLM for reasoning:** abstracted behind a single interface — start with Ollama (local, free) for development, support swapping to Anthropic/Gemini API later via config
- **Interface:** CLI first; optional Streamlit UI as a stretch goal
- **Output format:** Markdown report + raw JSON

---

## Project Structure

```
sc-checker/
├── contracts/                  # sample .sol files for testing
│   ├── reentrancy_example.sol
│   ├── access_control_example.sol
│   └── ...
├── knowledge_base/              # RAG source documents (plain text/markdown)
│   ├── swc-101-integer-overflow.md
│   ├── swc-107-reentrancy.md
│   ├── swc-115-tx-origin.md
│   └── dao-hack-writeup.md
├── src/
│   ├── __init__.py
│   ├── static_analysis.py       # Slither wrapper
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── build_index.py       # embeds knowledge_base/ into Chroma
│   │   └── retriever.py         # retrieve(query, k) function
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── llm_client.py        # abstract interface: LLMClient.generate(prompt)
│   │   ├── ollama_client.py
│   │   └── anthropic_client.py
│   ├── report/
│   │   ├── __init__.py
│   │   └── formatter.py         # builds markdown/JSON report from findings
│   ├── pipeline.py              # orchestrates the full flow end to end
│   └── prompts.py               # prompt templates as constants/functions
├── main.py                      # CLI entrypoint
├── requirements.txt
├── config.yaml                  # which LLM backend, model names, k value, etc.
└── README.md
```

---

## Step-by-Step Build Order

### Step 1 — Environment setup
- Install `solc-select`, install a recent Solidity version (e.g. 0.8.20), and `slither-analyzer`
- Verify Slither runs standalone on a test contract: `slither contracts/reentrancy_example.sol`
- Collect 5–10 sample vulnerable contracts labeled by vulnerability type. Good sources: SWC Registry examples (swcregistry.io), Ethernaut challenge contracts, DamnVulnerableDeFi
- **Acceptance check:** Slither runs successfully on at least 3 sample contracts and produces JSON output

### Step 2 — Static analysis wrapper (`src/static_analysis.py`)
- Write `run_slither(filepath: str) -> list[dict]` that:
  - Shells out to `slither <filepath> --json -` (or writes to a temp file)
  - Parses the JSON output into a clean list of findings, each with: `check` (vuln type), `impact` (severity), `description`, `function_name`, `filename`, `lines`
- Handle the case where Slither finds nothing (empty list) and where Slither itself errors (bad Solidity syntax, wrong compiler version)
- **Acceptance check:** running this on `reentrancy_example.sol` returns at least one finding with `check` containing "reentrancy"

### Step 3 — Build the RAG knowledge base
- Write 15–25 short documents in `knowledge_base/`, one per known vulnerability class (SWC Registry entries are ideal source material — summarize each in your own words, don't copy verbatim)
- Include at least: reentrancy, integer overflow/underflow, unchecked external calls, tx.origin auth, access control, front-running, timestamp dependence
- Write `src/rag/build_index.py`:
  - Loads all files in `knowledge_base/`
  - Chunks each into ~200-400 token pieces
  - Embeds with `sentence-transformers`
  - Stores in a local ChromaDB collection called `vuln_knowledge`
  - Run this once as a setup script, not per-request
- Write `src/rag/retriever.py`:
  - `retrieve(query: str, k: int = 3) -> list[str]` — embeds the query, returns top-k matching chunks from Chroma
- **Acceptance check:** `retrieve("reentrancy vulnerability external call before state update")` returns your reentrancy knowledge doc in the top result

### Step 4 — LLM client abstraction (`src/llm/`)
- Define an abstract interface in `llm_client.py`:
  ```python
  class LLMClient:
      def generate(self, prompt: str) -> str:
          raise NotImplementedError
  ```
- Implement `OllamaClient` (calls local Ollama server, e.g. `deepseek-coder` or `codellama` model) as the default for development
- Implement `AnthropicClient` as a swappable alternative (reads API key from env var, only used when configured)
- Read which backend to use from `config.yaml` so switching is a one-line config change, not a code change
- **Acceptance check:** both clients return a non-empty string response to a simple test prompt

### Step 5 — Prompt templates (`src/prompts.py`)
- Write a function `build_explanation_prompt(code_snippet, finding, retrieved_context) -> str` that constructs a prompt roughly like:
  ```
  You are a smart contract security auditor. A static analysis tool flagged the following issue.

  Vulnerability type: {finding.check}
  Function: {finding.function_name}
  Code:
  {code_snippet}

  Relevant background on this vulnerability class:
  {retrieved_context}

  Tasks:
  1. State whether this appears to be a true positive or likely false positive, and why.
  2. Explain the risk in plain language, specific to this function.
  3. Give a concrete example of how this could be exploited.
  4. Suggest a specific code fix.

  Respond in structured markdown with these four sections.
  ```
- Keep this in one place so you can iterate on prompt wording without touching pipeline logic
- **Acceptance check:** manually run one finding through this prompt against your LLM client and confirm the output has all 4 sections and makes sense

### Step 6 — Report formatting (`src/report/formatter.py`)
- Write `format_report(contract_name, findings_with_explanations) -> str` that produces a markdown document:
  ```
  # Security Report: {contract_name}

  ## Finding 1: {check} — Severity: {impact}
  **Location:** {function_name}, lines {lines}

  {llm_explanation}

  ---
  ```
- Also support dumping the same data as JSON for programmatic use later
- **Acceptance check:** running this on 2+ findings produces a readable markdown file

### Step 7 — Pipeline orchestration (`src/pipeline.py`)
- Write `analyze_contract(filepath: str) -> str` (returns final report) that:
  1. Calls `run_slither(filepath)`
  2. For each finding: extracts the relevant code snippet from the source file using the line numbers
  3. Calls `retrieve()` using the finding's `check` type + description as the query
  4. Builds the prompt and calls the LLM client
  5. Collects all explained findings
  6. Calls `format_report()` and returns the final markdown
- Handle the "no findings" case gracefully (report should say "no issues detected by static analysis" rather than erroring)
- **Acceptance check:** full pipeline runs end-to-end on `reentrancy_example.sol` without crashing and produces a complete report

### Step 8 — CLI entrypoint (`main.py`)
- Simple CLI: `python main.py --file contracts/reentrancy_example.sol --output report.md`
- Use `argparse`. Print progress to console ("Running static analysis...", "Retrieving context...", "Generating explanations...") so it doesn't look frozen during LLM calls
- **Acceptance check:** running the command produces `report.md` in the working directory

### Step 9 — Test against your full sample set
- Run all 5-10 sample contracts through the CLI
- For each, manually verify: did it catch the known bug? Is the severity reasonable? Does the explanation make sense to someone who didn't write the code?
- Keep a simple table (contract name, expected vuln, detected Y/N, explanation quality 1-5) — this becomes your informal eval and is useful to show in a portfolio writeup
- **Acceptance check:** at least 80% of known vulnerabilities in your sample set are detected and explained correctly

---

## Explicitly Out of Scope for v1
Defer these — do not build them now:
- Multi-agent critic/verification loop (second LLM pass to catch false positives)
- Multi-file / whole-project contract analysis
- Gas optimization checks
- Auto-fix / automatic PR generation
- Fine-tuning or training a custom detection model
- Web frontend with file upload (Streamlit can come after CLI works)

---

## Suggested Order of Operations for the Coding Assistant
1. Scaffold the project structure above
2. Implement Step 1–2 first and get real Slither output before touching any AI/RAG code
3. Implement Step 3 (RAG) and test retrieval in isolation
4. Implement Step 4–5 (LLM + prompts) and test explanation generation on one hardcoded finding
5. Wire everything together in Step 7 (pipeline)
6. Build the CLI last
7. Test against the full sample set and iterate on prompt wording based on real output quality

## Config File Example (`config.yaml`)
```yaml
llm:
  backend: ollama          # or "anthropic"
  model: deepseek-coder    # or "claude-sonnet-4-6" if backend is anthropic
rag:
  top_k: 3
  embedding_model: all-MiniLM-L6-v2
solidity:
  compiler_version: "0.8.20"
```
