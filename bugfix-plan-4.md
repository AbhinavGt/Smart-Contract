# Bugfix Plan — Real LLM Output Quality Issues (Post-Ollama Fix)

## Context
First run with Ollama genuinely reachable (`deepseek-coder`) against `unseen_test_example.sol` surfaced three distinct, real quality problems — separate from the earlier offline-fallback issue. This is expected at this stage: the pipeline plumbing is now working end-to-end, and these are legitimate output-quality bugs the verification gates correctly caught rather than passing through as good.

---

## Bug 1: Code extraction from LLM response includes prose, breaking compilation

### Symptom
Fix verification for `arbitrary-send-eth` failed with `Error: Expected identifier but got 'is'` at the line `Here is the corrected version of the emergencyWithdraw function:` — this sentence, part of the model's natural-language response, was written directly into the temp `.sol` file alongside the actual code.

### Root Cause
The code that extracts the fix from the LLM's raw response text is not correctly isolating just the fenced code block (the content between \`\`\`solidity and \`\`\`). It's likely taking too much of the raw text — either grabbing everything after a keyword, or not using the code fence markers as boundaries at all.

### Fix
In whichever function parses the LLM's fix response (likely in `src/autofix/pipeline.py` near where `fixed_code = llm.generate(build_fix_prompt(...))` is called):

```python
import re

def extract_code_block(llm_response: str) -> str:
    """Extract only the content inside a solidity code fence, discarding any
    surrounding prose the model may have added despite instructions not to."""
    match = re.search(r"```(?:solidity)?\s*\n(.*?)```", llm_response, re.DOTALL)
    if match:
        return match.group(1).strip()
    # No fence found at all — treat as a hard failure rather than guessing
    raise ValueError("No solidity code fence found in LLM fix response")
```

- Call this immediately after receiving the raw LLM response, before passing anything to `apply_fix_to_temp_copy()`.
- If no code fence is found, treat it as a fix generation failure (`status: failed, gate_failed: extraction`) rather than attempting to use the raw text — this is safer than guessing at what part of a malformed response might be code.
- Strengthen the fix prompt (Step 22's `build_fix_prompt()`) to be even more explicit: "Output nothing except a single \`\`\`solidity code fence containing only the corrected function. Do not include any sentence before or after the code fence."

### Verification
- Re-run against `unseen_test_example.sol` and confirm the fix pipeline no longer fails with a syntax error caused by prose contamination.
- Deliberately test with a mocked LLM response that includes a leading sentence (e.g. "Here is the fix:") before the code fence, and confirm `extract_code_block()` correctly strips it.

---

## Bug 2: RAG retrieval / prompt grounding causes the model to hallucinate the wrong vulnerability class

### Symptom
For an `arbitrary-send-eth` finding (missing access control, no reentrancy involved), the model's explanation describes a reentrancy attack narrative that doesn't match the actual code, and proposes a fix (retry-on-failure) that doesn't address the real issue at all. For a `missing-zero-check` finding, the explanation invents unrelated concepts (signature replay, nonce, chain identifier) that appear nowhere in the contract or the finding.

### Root Cause (to confirm)
1. **Knowledge base imbalance:** if `knowledge_base/` has significantly more/better content on reentrancy than on access-control or arbitrary-send patterns, `retrieve()` may be returning the closest-but-wrong match (reentrancy content) when queried with a less-represented finding type, and the model runs with whatever context it's given.
2. **Retrieval query too generic:** if the query passed to `retrieve()` uses a generic string rather than the specific Slither `check` type (e.g. `"arbitrary-send-eth"`), the vector search may not be precise enough to pull the right document even if one exists.
3. **Prompt doesn't constrain the model to the retrieved context:** if the prompt doesn't explicitly instruct the model to only reason about what's actually in the code and retrieved context, general-purpose security jargon in its training data can leak in ungrounded.

### Fix
1. **Expand the knowledge base for currently underrepresented vulnerability classes.** Add dedicated, detailed entries for `arbitrary-send-eth` / missing access control and for `missing-zero-check`, written as specifically as your existing reentrancy entry. Check `knowledge_base/` now — if these are thin or missing, that's very likely the direct cause of the hallucination.
2. **Use the exact Slither `check` string as (part of) the retrieval query**, not a paraphrased or generic description:
   ```python
   retrieved_context = retrieve(query=finding["check"], k=3)
   ```
   rather than a looser natural-language query built separately.
3. **Add an explicit grounding instruction to `build_explanation_prompt()`:**
   ```
   Only describe vulnerabilities that are actually present in the code shown above.
   Do not reference vulnerability types (such as reentrancy, signature replay, or
   nonce/replay issues) unless the specific code pattern for that vulnerability
   type is visible in the function shown. If the retrieved background context
   below does not match the actual code, rely on the code itself over the
   background context.
   ```
4. **Add a lightweight sanity check post-generation (optional but valuable):** if the finding's `check` type is `arbitrary-send-eth` but the explanation text contains the word "reentrancy" (or vice versa for mismatched types), flag it for the critic loop to specifically scrutinize, or log it for manual review during testing.

### Verification
- Re-run against `unseen_test_example.sol`. Confirm the `arbitrary-send-eth` explanation specifically discusses the missing `owner`/access-control check, not reentrancy.
- Confirm the `missing-zero-check` explanation discusses the actual detector meaning (typically: an address parameter isn't checked against the zero address before use) rather than unrelated signature-replay content.
- Spot check 2-3 other findings across different vulnerability types to confirm explanations stay grounded to their actual `check` type.

---

## Bug 3: Model output repeats/loops instead of stopping cleanly

### Symptom
The `missing-zero-check` explanation contains the same "Response / Assessment / Code" block repeated three times verbatim.

### Root Cause
No stop sequence is configured for the Ollama generation call, and/or `max_tokens`/`num_predict` is set high enough that the model continues generating past a natural stopping point, looping back into re-answering the same prompt structure. This is a known behavior pattern for some local models without proper generation constraints.

### Fix
In `src/llm/ollama_client.py`, when making the generation request, add explicit stop sequences and a reasonable token cap:

```python
response = requests.post(
    "http://localhost:11434/api/generate",
    json={
        "model": self.model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": 500,       # cap output length
            "stop": ["### Response", "```\n\n###"],  # tune based on your prompt's structure
            "repeat_penalty": 1.3,     # discourage verbatim repetition
        }
    }
)
```
- The exact `stop` strings should match whatever section headers your prompt template uses (e.g. if your prompt asks for "Assessment / Risk / Exploit example / Suggested fix" as the four sections, set a stop sequence for right after the last expected section, or detect completion by section count rather than relying purely on the model naturally stopping).
- As a defensive backstop independent of the model's own stopping behavior, add post-processing: after receiving the response, check if the expected section markers (e.g. "### Assessment") appear more than once, and if so, truncate everything after the first complete occurrence of all four sections.

### Verification
- Re-run and confirm no explanation contains duplicated section blocks.
- If duplication still occurs occasionally, confirm the post-processing truncation catches it as a backstop.

---

## Summary for the Coding Agent

| File | Change |
|---|---|
| `src/autofix/pipeline.py` (or wherever fix responses are parsed) | Add `extract_code_block()` to isolate only fenced code, reject/fail cleanly if no fence found |
| `src/prompts.py` | Add explicit grounding instruction against hallucinated vulnerability types; use exact `check` string in retrieval queries |
| `knowledge_base/` | Add/expand dedicated entries for `arbitrary-send-eth` and `missing-zero-check` (and any other underrepresented types) |
| `src/llm/ollama_client.py` | Add `stop` sequences, `num_predict` cap, and `repeat_penalty` to the generation request; add post-processing truncation as a backstop against repeated sections |

## Re-test Checklist
1. Re-run against `unseen_test_example.sol` with `--fix --fix-index 0`
2. Confirm the `arbitrary-send-eth` explanation correctly identifies missing access control, not reentrancy
3. Confirm the fix now compiles successfully (no prose contamination) and correctly references the existing `owner` variable
4. Confirm the `missing-zero-check` explanation is coherent, specific, and not duplicated
5. Re-run against 1-2 of your original sample contracts to confirm these changes didn't regress previously-working explanations (especially the reentrancy case, since that's your best-working example so far)
6. Only once these pass consistently should you consider re-running the eval harness (Step 20/29) for real numbers
