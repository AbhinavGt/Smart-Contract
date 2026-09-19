# AI Smart Contract Vulnerability Checker — v1 + v2 + v3 + v4 Implementation Plan

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
agent:
  max_loops: 3              # safety cap for the v2 critic loop
```

---

# v2 — Agentic Critic Loop

## Prerequisite
Do not start v2 until v1's full pipeline (Step 1–9 above) runs end-to-end correctly and has been tested against the sample contract set. v2 adds a loop on top of the existing pipeline — it does not replace any v1 component.

## What Changes Conceptually
v1 is a fixed pipeline: every finding goes through the same steps once, in the same order, regardless of outcome. v2 makes the explanation step **agentic**: after producing an explanation, the system evaluates its own output and decides whether to accept it, gather more information and retry, or flag it as uncertain — instead of always accepting whatever the first LLM call produces.

## New Component: The Critic Loop

### Step 10 — Add a critic prompt (`src/prompts.py`)
- Add `build_critique_prompt(code_snippet, finding, explanation) -> str`, structured like:
  ```
  You are reviewing a security explanation for accuracy before it is shown to a developer.

  Original code:
  {code_snippet}

  Static analysis finding: {finding.check}

  Explanation given:
  {explanation}

  Check the explanation against the actual code. Respond in this exact format:
  VERDICT: CONFIDENT or UNCERTAIN
  REASON: <one or two sentences>
  MISSING_CONTEXT: <what additional information, if any, would help verify this — e.g. "need to see the calling function" or "need retrieval on integer overflow patterns" or "none">
  ```
- Keep the output format strict and parseable (fixed keywords) — you'll parse this string in code, so avoid free-form responses here

### Step 11 — Add a context-fetching tool (`src/pipeline.py`)
- Write `fetch_additional_context(filepath, request: str) -> str`, a small tool the loop can call when the critic's `MISSING_CONTEXT` says it needs more code. Two supported request types are enough for v2:
  - `"calling function"` → search the source file for where the flagged function is called from, return that snippet too
  - `"re-retrieve: <topic>"` → call `retrieve()` again with a new query string built from `<topic>` instead of the original finding text
- This function is what makes the loop "agentic" rather than just "prompted twice" — the *system*, not you, decides what extra input to fetch, based on the critic's own stated reasoning

### Step 12 — Wire the loop into the pipeline (`src/pipeline.py`)
Replace the single explanation call in `analyze_contract()` with a loop per finding:
```python
def explain_finding_with_critic(finding, code_snippet, retrieved_context, max_loops=3):
    explanation = llm.generate(build_explanation_prompt(code_snippet, finding, retrieved_context))

    for i in range(max_loops):
        critique = llm.generate(build_critique_prompt(code_snippet, finding, explanation))
        verdict, reason, missing = parse_critique(critique)  # simple string parsing

        if verdict == "CONFIDENT":
            return explanation, confident=True, loops_used=i

        if missing == "none" or missing is None:
            # uncertain but nothing more to fetch — stop and flag it
            return explanation, confident=False, loops_used=i

        extra_context = fetch_additional_context(finding.filename, missing)
        explanation = llm.generate(
            build_explanation_prompt(code_snippet, finding, retrieved_context + extra_context)
        )

    return explanation, confident=False, loops_used=max_loops  # hit the safety cap
```
- The `max_loops` cap (read from `config.yaml`) is mandatory — never let this loop run unbounded. 3 is a sane default.
- **Acceptance check:** feed a finding where the first explanation is deliberately vague (e.g. don't give it the calling function context) and confirm the loop requests it and improves the explanation on the second pass

### Step 13 — Update the report format (`src/report/formatter.py`)
- Add a confidence indicator per finding: show `✅ Confident` or `⚠️ Needs manual review` based on the loop's final verdict, plus how many critic loops it took
- Findings marked `⚠️ Needs manual review` should be visually distinct in the markdown output (e.g., a separate section at the top) so a developer knows to look at those first
- **Acceptance check:** a report with mixed confident/uncertain findings clearly separates the two

### Step 14 — Test the loop against edge cases
- Run the full sample set again through v2 and compare against your v1 results table
- Specifically check: does the critic ever falsely mark a correct explanation as uncertain (wasted loops)? Does it ever loop the full `max_loops` and still be wrong? Log loop counts per finding — if most findings take 1 loop (never triggering the critic's doubt), your critic prompt may be too lenient; if most take all 3, it may be too strict
- **Acceptance check:** average loops per finding is between 1 and 2 across your sample set — if it's consistently hitting the cap, revise the critic prompt before moving on

## Explicitly Still Out of Scope for v2
- Multi-file / whole-project analysis
- Multiple parallel agents (e.g., a separate "gas optimization agent" running alongside the security agent)
- Auto-fix application (writing the fix back into the file)
- Any tool call that modifies the contract itself — v2's agent only reads and reasons, it does not write code changes automatically

## Why This Counts as "Agentic" (for your portfolio writeup)
The defining feature is that **the next action is chosen by the model's evaluation of its own prior output**, not by a fixed step count you wrote in advance. The number of LLM calls per finding varies (1 to `max_loops`) depending on how confident the critic is, and the specific tool call made (`fetch_additional_context`) depends on what the critic says it's missing — that's a real decision loop, not just "call the LLM twice."

---

# v3 — Multi-Agent Orchestration + Ground-Truth Evaluation

## Prerequisite
v2's critic loop must be working and tested before starting v3. v3 adds a second specialized agent alongside the existing security agent, plus a formal evaluation harness — it does not change how the security agent itself works internally.

## Part A: Multi-Agent Orchestration

### Step 15 — Add a second knowledge base for gas optimization (`knowledge_base_gas/`)
- Write 10–15 short documents covering common gas-inefficiency patterns: unnecessary storage writes, loops over unbounded arrays, redundant SLOAD operations, inefficient use of `require` strings, packing struct variables poorly
- Build a separate Chroma collection for this, e.g. `vuln_knowledge_gas`, kept fully separate from the security knowledge base so retrieval doesn't mix the two domains
- **Acceptance check:** `retrieve("unbounded loop gas cost", collection="vuln_knowledge_gas")` returns relevant gas docs, not security docs

### Step 16 — Add a gas-analysis agent (`src/agents/gas_agent.py`)
- This agent does NOT use Slither's security detectors. Instead, use Slither's own gas-related detectors (it has some, e.g. `costly-loop`) or write simple AST-pattern checks of your own (e.g. flag any `for` loop whose bound is a storage-array `.length` read inside the loop condition)
- Reuse the same `LLMClient` interface and the same critic-loop pattern from v2 — the gas agent should look structurally identical to the security agent, just pointed at a different knowledge base and a different finding source
- Write `analyze_gas(filepath: str) -> list[dict]`, mirroring `analyze_contract()`'s structure but returning gas findings instead of security findings
- **Acceptance check:** running this against a contract with a known unbounded-loop pattern produces at least one flagged finding with an LLM explanation

### Step 17 — Restructure the pipeline as an orchestrator (`src/pipeline.py`)
- Refactor `analyze_contract()` into `orchestrate(filepath: str) -> dict`:
  ```python
  def orchestrate(filepath):
      security_findings = run_security_agent(filepath)   # existing v1+v2 logic
      gas_findings = run_gas_agent(filepath)              # new v3 logic
      return merge_findings(security_findings, gas_findings)
  ```
- Both agents can run independently — if you want a small real speedup, run them concurrently with `asyncio.gather` or `concurrent.futures.ThreadPoolExecutor`, since neither depends on the other's output. This isn't required for v3 to work, but it's a nice showcase of understanding independent parallel agents.
- Write `merge_findings(security_findings, gas_findings) -> dict`, returning a structure like `{"security": [...], "gas": [...]}` — keep them in separate sections rather than interleaving, since they're different concern areas for the developer reading the report
- **Acceptance check:** `orchestrate()` returns both finding types from a single call, and total run time with concurrency is meaningfully less than running both sequentially

### Step 18 — Update the report format for two sections
- Update `formatter.py` to produce a report with two top-level sections: `## Security Findings` and `## Gas Optimization Findings`, each keeping the confidence indicators from v2
- **Acceptance check:** a contract with both a security issue and a gas issue produces a report showing both, clearly separated

## Part B: Ground-Truth Evaluation Harness

### Step 19 — Build a labeled evaluation set (`eval/labeled_contracts.yaml`)
- For every sample contract you're using (SWC Registry examples, Ethernaut challenges, etc.), record the known ground truth:
  ```yaml
  - file: contracts/reentrancy_example.sol
    expected_vulnerabilities:
      - type: reentrancy
        function: withdraw
  - file: contracts/safe_example.sol
    expected_vulnerabilities: []   # contract with no known bugs, to test false-positive rate
  ```
- Include at least 2-3 "clean" contracts with no known vulnerabilities — without these you can only measure recall, not false-positive rate, and a checker that flags everything as vulnerable would score perfectly on recall alone
- Aim for at least 15-20 labeled contracts covering as many different vulnerability classes as you have knowledge base entries for
- **Acceptance check:** the YAML file parses correctly and covers at least 5 distinct vulnerability types plus some clean contracts

### Step 20 — Write the eval script (`eval/run_eval.py`)
- For each labeled contract:
  - Run `orchestrate(filepath)` to get actual findings
  - Compare `actual` vs `expected` per vulnerability type (a finding "counts" as a match if the `type` and `function` both align — decide and document your matching rule)
  - Track: true positives, false positives (flagged but not in ground truth), false negatives (in ground truth but not flagged)
- Compute precision, recall, and F1 score overall, and broken down per vulnerability type (e.g., reentrancy: 90% recall, access-control: 60% recall) — the per-type breakdown is more useful than one aggregate number since it tells you exactly which knowledge base entries or prompts need work
- Output a simple table (console print or CSV) — no need for anything fancy
- **Acceptance check:** running the eval script against your full labeled set produces a table with precision/recall/F1 per vulnerability type and an overall score

### Step 21 — Iterate using the eval results
- Look at whichever vulnerability type has the worst recall or precision, and go back to that specific knowledge base doc or prompt wording to improve it
- Re-run the eval after each change and track whether the score actually improved — this before/after comparison is exactly the kind of evidence worth showing in a portfolio ("iterating on the reentrancy knowledge doc improved recall from 60% to 85%")
- **Acceptance check:** at least one documented iteration cycle showing a measured before/after improvement on some metric

## Explicitly Still Out of Scope for v3
- Auto-fix generation and applying fixes back to files
- Live/scraped exploit data feeds — knowledge bases remain static and manually curated
- Multi-file / cross-contract analysis — each agent still analyzes one file at a time
- A third specialized agent (e.g., a business-logic agent) — two agents (security + gas) is enough to demonstrate the multi-agent pattern without overbuilding

## Why This Matters for a Portfolio
Two things happen in v3 that turn this from "a project that runs" into "a project you can defend under questioning": (1) genuinely independent agents with separate knowledge domains running in parallel and merging outputs, which is real multi-agent orchestration rather than one agent doing two tasks sequentially, and (2) a measured evaluation with actual precision/recall numbers instead of "it seemed to work when I tried it" — this is the difference between a demo and something you can speak to with data in an interview.

---

# v4 — Verified Auto-Fix Generation

## Prerequisite
v3's security agent, critic loop, and eval harness must be working first. v4 adds a new capability (fix generation + verification) on top of the existing security agent — it does not touch the gas agent or the eval harness structure, though the eval harness will be extended to also measure fix quality.

## Scope Decision (read this first)
This version is deliberately capped at three verification gates: **compilation, static-analysis re-check, and interface preservation.** It explicitly does NOT attempt fuzz-testing or formal verification of behavioral correctness — those require building Solidity test infrastructure (Foundry) that's a separate skill investment. Every fix output must be labeled with exactly which gates it passed, so the limitation is visible in the tool's output rather than hidden. Never auto-apply a fix to the user's original file — always output a diff for manual review.

## New Component: The Fix-and-Verify Pipeline

### Step 22 — Add a fix-generation prompt (`src/prompts.py`)
- Add `build_fix_prompt(code_snippet, finding, explanation) -> str`:
  ```
  You are fixing a security vulnerability in a Solidity function.

  Original function:
  {code_snippet}

  Vulnerability: {finding.check}
  Explanation of the issue: {explanation}

  Output ONLY the corrected version of this function. Do not change its name,
  parameters, visibility, or return type unless absolutely required to fix the
  vulnerability — if a signature change is required, state why in a comment
  directly above the function.

  Output format: a single Solidity code block, nothing else.
  ```
- Keep the instruction to preserve the signature explicit and strict — this makes Step 25's interface check meaningful rather than something the LLM ignores
- **Acceptance check:** running this on the reentrancy example produces a function with the state update moved before the external call, same name/params/visibility

### Step 23 — Build the temp-file sandbox (`src/autofix/sandbox.py`)
- Write `apply_fix_to_temp_copy(original_filepath, function_name, fixed_code) -> str` (returns path to a temp file):
  - Copies the original file to a temp location (use Python's `tempfile` module — never write into the original file or its directory)
  - Replaces the flagged function's source text with the LLM's fixed version (locate it using the line numbers from the Slither finding)
  - Returns the temp file path
- **Acceptance check:** the temp file is a valid, complete `.sol` file with only the target function changed, verified by diffing it against the original outside the function body

### Step 24 — Compilation gate (`src/autofix/verify.py`)
- Write `check_compiles(filepath) -> tuple[bool, str]` (bool result, compiler output/error message):
  ```python
  def check_compiles(filepath):
      result = subprocess.run(
          ["solc", "--bin", filepath],
          capture_output=True, text=True
      )
      return result.returncode == 0, result.stderr
  ```
- If this fails, discard the fix immediately — do not proceed to further gates, and do not retry more than once (one retry: feed the compiler error back to the LLM and ask it to correct syntax, then re-check; if it fails a second time, mark the fix as failed)
- **Acceptance check:** an intentionally broken fix (e.g. missing semicolon) is correctly caught and rejected

### Step 25 — Interface preservation gate (`src/autofix/verify.py`)
- Write `check_interface_preserved(original_filepath, fixed_filepath, function_name) -> tuple[bool, str]`:
  - Run `solc --abi` on both the original and the fixed temp file
  - Parse both ABIs as JSON, extract the entry matching `function_name`
  - Compare: name, input types (in order), output types, visibility/state-mutability (`view`, `payable`, etc.)
  - If anything differs, return `False` with a message describing exactly what changed
- **Acceptance check:** a fix that accidentally changes a parameter type or drops `payable` is caught; a fix that only changes internal logic passes

### Step 26 — Re-analysis gate (`src/autofix/verify.py`)
- Write `check_vulnerability_resolved(original_findings, fixed_filepath) -> tuple[bool, list]`:
  - Run Slither on the fixed temp file (reuse `run_slither()` from v1)
  - Confirm the specific finding type that was being fixed no longer appears for that function
  - Also collect any NEW findings that appear in the fixed file that weren't in the original — these should be surfaced as warnings even if the main gate passes, since a fix that resolves one bug but introduces another is a real failure mode worth flagging
- **Acceptance check:** running this on a correctly fixed reentrancy example confirms the reentrancy finding is gone; running it on a fix that introduces a new access-control issue surfaces that as a warning

### Step 27 — Orchestrate the fix pipeline (`src/autofix/pipeline.py`)
- Write `generate_verified_fix(finding, code_snippet, explanation, original_filepath) -> dict`:
  ```python
  def generate_verified_fix(finding, code_snippet, explanation, original_filepath):
      fixed_code = llm.generate(build_fix_prompt(code_snippet, finding, explanation))
      temp_path = apply_fix_to_temp_copy(original_filepath, finding.function_name, fixed_code)

      compiles, compile_error = check_compiles(temp_path)
      if not compiles:
          # one retry with the compiler error fed back
          fixed_code = llm.generate(build_fix_prompt(code_snippet, finding, explanation) + f"\n\nPrevious attempt failed to compile: {compile_error}")
          temp_path = apply_fix_to_temp_copy(original_filepath, finding.function_name, fixed_code)
          compiles, compile_error = check_compiles(temp_path)
          if not compiles:
              return {"status": "failed", "gate_failed": "compilation", "detail": compile_error}

      interface_ok, interface_msg = check_interface_preserved(original_filepath, temp_path, finding.function_name)
      if not interface_ok:
          return {"status": "failed", "gate_failed": "interface", "detail": interface_msg}

      resolved, new_findings = check_vulnerability_resolved([finding], temp_path)
      if not resolved:
          return {"status": "failed", "gate_failed": "static_analysis", "detail": "original vulnerability still present"}

      return {
          "status": "verified",
          "gates_passed": ["compilation", "interface_preserved", "static_analysis"],
          "fixed_code": fixed_code,
          "diff": generate_diff(code_snippet, fixed_code),  # use difflib
          "new_findings_introduced": new_findings,  # surfaced even on success
      }
  ```
- Delete all temp files after each run regardless of outcome
- **Acceptance check:** running end-to-end on the reentrancy example produces `status: verified` with a clean diff; running it on a case where the LLM's fix breaks the interface produces `status: failed, gate_failed: interface`

### Step 28 — Update the report format (`src/report/formatter.py`)
- For each security finding, add a "Suggested Fix" subsection:
  - If `status: verified` — show the diff, and label it clearly: `Verification: ✓ Compiles  ✓ Interface preserved  ✓ Vulnerability resolved (static analysis)`. If `new_findings_introduced` is non-empty, show those as a separate warning even though the main gate passed
  - If `status: failed` — show which gate failed and why, and state plainly that no verified fix could be generated, rather than showing a broken diff
- Add a one-line disclaimer near the top of the report, once: "Verified fixes pass compilation, interface-preservation, and static-analysis checks. They are not proven behaviorally equivalent to the original — review before applying."
- **Acceptance check:** a report shows at least one verified fix with its diff and gate list, and correctly represents at least one failed fix case without showing broken code as if it were good

### Step 29 — Extend the eval harness to measure fix quality
- Add a new field to `eval/labeled_contracts.yaml` per entry: whether a known-good fix exists for reference (optional, for contracts where you know the canonical fix)
- Add to `eval/run_eval.py`: for every true-positive finding, attempt `generate_verified_fix()` and record: did it produce a `verified` fix, and if so did it pass all three gates on the first try or did it need the compile retry
- Report a new metric: **fix success rate** (% of true-positive findings for which a verified fix was generated) alongside your existing precision/recall/F1 from v3
- **Acceptance check:** the eval output now includes fix success rate broken down by vulnerability type, alongside the v3 detection metrics

## Explicitly Still Out of Scope for v4
- Fuzz-testing or property-based invariant checking (Foundry) — noted as future work, not attempted
- Formal/symbolic verification (Mythril, Certora) — noted as future work only
- Auto-applying fixes to the user's real file — always output a diff, never write back automatically
- Fixes spanning multiple functions or requiring new state variables — restrict fix generation to single-function, localized changes only; if the LLM's fix requires touching other parts of the contract, mark it `gate_failed: scope` and skip verification rather than attempting to validate a multi-function change

## Why This Matters for a Portfolio
The honest, labeled verification gates are the point here — not the fix generation itself, which is the easy part. Being able to say "X% of true-positive findings received a fix that passed compilation, preserved the interface, and was confirmed by static analysis to resolve the original issue — and here's the number for how often that held" is a defensible claim. Claiming "auto-fix" without stating what was and wasn't verified is the kind of thing that falls apart under a single follow-up question, so the report format in Step 28 exists specifically to make the limitation visible rather than glossed over.
