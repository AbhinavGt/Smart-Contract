# Bugfix Plan — Boilerplate Explanations & Confidence Labeling Conflict

## Context
Test run against `reentrancy_example.sol` (v4, `--fix` flag) produced a verified, correct fix — but surfaced two bugs in the explanation/reporting layer that need fixing before results can be trusted.

---

## Bug 1: LLM explanations are generic boilerplate, not finding-specific

### Symptom
The "Assessment / Risk / Exploit example / Suggested fix" text is byte-for-byte identical for the `reentrancy-eth` security finding and the unrelated `redundant-storage-read` gas finding. Generic phrases like "loss of funds" and "checks-effects-interactions" appear even on the gas finding, where they make no sense.

### Root Cause (to confirm — check each in order)
1. **Silent exception fallback:** the code calling the LLM likely wraps the call in a try/except that returns a hardcoded default string on any failure (auth error, timeout, malformed response) instead of raising or logging the error.
2. **Prompt not interpolating real values:** check `build_explanation_prompt()` in `src/prompts.py` — confirm the f-string/format call is actually substituting `code_snippet`, `finding.description`, and `retrieved_context`, not a static template string left over from early scaffolding/testing.
3. **RAG retrieval returning empty:** confirm `retrieve()` is returning non-empty, relevant chunks for both a security query and a gas query — if it's returning `[]` silently, the prompt may have a hardcoded fallback context string.

### Fix
1. In whatever function calls the LLM for explanations (likely in `src/pipeline.py` or wherever `llm.generate(build_explanation_prompt(...))` is invoked), **remove any bare `except: return <default string>` pattern.** At minimum, log the actual exception and the raw prompt that was sent.
2. Add a debug log (temporary, can be removed later) that prints the fully-rendered prompt string immediately before the LLM call, for one run. Confirm it contains the actual function code and finding description — not literal `{code_snippet}` placeholder text (a classic bug if using `.format()` incorrectly or a raw string instead of an f-string).
3. Add a similar debug log for the raw LLM response before any parsing/formatting happens. Confirm the response text itself varies between the reentrancy and gas prompts — if the raw response is already identical, the bug is in prompt construction/retrieval, not in downstream formatting; if the raw response differs but the final report shows identical text, the bug is in the formatter overwriting/merging fields.
4. Once the root cause is found: if it's a silent fallback (root cause 1), replace it with actual error surfacing — e.g., include `"explanation": "LLM call failed: <error message>"` in the output rather than fabricated boilerplate, so a failure is visible in the report itself.

### Verification
- Re-run `reentrancy_example.sol` and confirm the security finding's explanation specifically references reentrancy/external-calls/state-update-ordering, and the gas finding's explanation specifically references the redundant storage read — the two should read nothing alike.
- Spot-check against 2 other sample contracts to confirm explanations vary appropriately across different vulnerability types.

---

## Bug 2: Confidence label and fix-verification status contradict each other in the report

### Symptom
The report header shows "⚠️ Needs manual review" (driven by the critic loop's `confident: false`), while the same finding's fix section shows "Status: Verified | Gates passed: compilation, interface_preserved, static_analysis" — two contradictory signals shown without distinction, confusing to read.

### Root Cause
These are two independent signals that answer different questions:
- **`confident` (from v2's critic loop)** — is the *explanation* well-supported, based on the critic's self-assessment?
- **fix `status: verified`** — did the *generated fix* pass the three mechanical v4 gates (compiles, interface preserved, vulnerability resolved per static analysis)?

The current formatter (`src/report/formatter.py`) is displaying both without labeling which is which, so they read as one combined verdict.

### Fix
Update the report template to clearly separate the two indicators with distinct labels, e.g.:

```
### Finding 1: reentrancy-eth — Severity: High
**Explanation confidence:** ⚠️ Uncertain (critic loops used: 1)
**Fix verification:** ✅ Verified — passed compilation, interface preservation, static analysis

[explanation content]

[fix diff]
```

Rather than one shared banner like "Needs manual review" that implies the whole finding (including a fix that actually passed all its gates) is untrustworthy. Make clear in the template that these labels can legitimately disagree — e.g. a fix can be mechanically verified even if the critic wasn't fully confident in its own explanation wording, and vice versa.

### Verification
- Re-run and confirm the report clearly shows both labels separately, worded so a reader understands they're answering different questions.
- Confirm this doesn't break the "Needs manual review" grouping section at the top of the report (Step 13) — that section should now group by **explanation confidence only**, separately from fix verification status.

---

## Bug 3 (dependent on Bug 1): Critic loop confidence may be unreliable until Bug 1 is fixed

### Note
`loops_used: 1, confident: false` on the reentrancy finding may simply reflect the critic evaluating the same broken boilerplate explanation from Bug 1, not a genuine assessment of an ambiguous case. Do not attempt to tune the critic prompt or `max_loops` behavior until Bug 1 is confirmed fixed — re-test the critic loop's behavior fresh afterward, since it may resolve on its own.

### Verification (after Bug 1 fix)
- Re-run `reentrancy_example.sol`. If the explanation is now correct and specific, check whether `confident` becomes `true`. If it's still `false` with a real, well-formed explanation, that's a separate, genuine tuning issue for the critic prompt — worth investigating only at that point.

---

## Summary for the Coding Agent

| File | Change |
|---|---|
| `src/pipeline.py` (or wherever LLM calls happen) | Remove silent exception fallback returning boilerplate; surface real errors |
| `src/prompts.py` | Verify `build_explanation_prompt()` correctly interpolates real finding/code/context values |
| `src/rag/retriever.py` | Verify `retrieve()` returns non-empty, relevant results for both security and gas queries |
| `src/report/formatter.py` | Separate "explanation confidence" and "fix verification status" into two distinct, clearly labeled indicators |

## Re-test Checklist
1. Re-run `reentrancy_example.sol` with `--fix` and confirm the security and gas explanations are distinct and specific to each finding
2. Confirm the report shows explanation confidence and fix verification status as two separate labels
3. Check whether critic confidence changes now that explanations are real
4. Run against the new test contract (`unseen_test_example.sol`, provided separately) to confirm the fixes generalize to a file never used during development
