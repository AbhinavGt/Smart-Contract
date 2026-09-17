# Bugfix Plan 6 — Grounding Failure on Lower-Frequency Detectors (Naming Hypothesis Ruled Out)

## Context
Step 1's diagnostic (renaming `VaultManager` to `TestContractAlpha`) is complete. The same type of fabricated content appeared regardless of contract name: invented library references (`OpenZeppelin ERC2756`, `ERC714` — neither is a real standard), a fabricated documentation URL (`https://docs-vault.openzeppelin.com`), and unrelated vulnerability claims (reentrancy, a garbled "signature play-forgotten" claim) — all on the `missing-zero-check` finding specifically.

**Conclusion: the naming-collision hypothesis is ruled out.** The actual pattern is that this model confabulates specific technical details when reasoning about a less commonly-discussed vulnerability type (`missing-zero-check`) compared to a well-known one (`reentrancy`, `arbitrary-send-eth`), which produced clean output in the same diagnostic run. This is a general grounding/factuality weakness for less-represented detector types, not something tied to the test contract's naming.

Apply Steps 1-3 below now (they were written to apply "once Step 1 is reported" — that condition is now satisfied, and applies regardless of which specific cause was confirmed, since all three are general grounding improvements).

---

## Step 1: Strengthen the anti-hallucination prompt instruction (supersedes the earlier draft)

### Where
`src/prompts.py` — both `build_explanation_prompt()` and `build_critique_prompt()`.

### What to add
Replace or extend the earlier anti-hallucination block with this more specific version, since the earlier draft focused on "real protocol names" but the actual fabrication seen was invented library/standard names and URLs:

```
This is a standalone, synthetic test contract used only for security analysis
testing. It is not associated with any real-world protocol, project,
organization, or open-source repository.

Only reference libraries, functions, imports, or standards (such as ERC/EIP
numbers) that are literally present in the Solidity code shown below. Do not
invent or assume the use of any external library, framework, or standard that
is not explicitly imported or referenced in the code. Do not include any
URLs, documentation links, or GitHub references of any kind — none are
relevant to this analysis. If you are uncertain about a specific technical
detail, state your uncertainty explicitly rather than filling the gap with
a plausible-sounding but unverified claim.
```

### Verification
Re-run against `unseen_test_example.sol` (the original, un-renamed file — no need to keep testing the renamed copy going forward) and confirm the `missing-zero-check` explanation no longer mentions any library, standard, or URL not present in the actual contract source.

---

## Step 2: Lower sampling temperature (unchanged from prior plan — apply now)

### Where
`src/llm/ollama_client.py`, inside `generate()`'s request payload.

### What to change
```python
"options": {
    "num_predict": 500,
    "temperature": 0.2,
    "stop": ["### Response", "```\n\n###"],
    "repeat_penalty": 1.3,
},
```

### Verification
Re-run the same finding 2-3 times and confirm output stays grounded to the actual code across repeated runs, not just on one lucky attempt.

---

## Step 3: Expand the contamination filter to catch fabricated standards, not just known protocol names

### Where
`src/llm/contamination_filter.py` (or wherever `looks_contaminated()` was added).

### What to change
The original filter's protocol-name blocklist (`uniswap|compound|aave|opensea`) won't catch this case, since "OpenZeppelin" is a legitimate library that may legitimately appear in real fixes (e.g. `ReentrancyGuard`). The fabrication here is specifically: (a) an invented ERC/EIP number, and (b) a URL — the existing URL pattern already catches (b). Add a check for (a):

```python
import re

# Known real ERC/EIP numbers that commonly appear in Solidity contracts.
# Not exhaustive — extend if legitimate numbers get false-flagged.
_KNOWN_ERC_NUMBERS = {
    "20", "165", "721", "777", "1155", "1967", "2612", "2981", "4626", "4907",
}

_ERC_PATTERN = re.compile(r"\bERC-?(\d+)\b", re.IGNORECASE)

def has_fabricated_standard_reference(text: str) -> bool:
    """Flag ERC/EIP numbers mentioned in the response that don't correspond
    to a widely-recognized standard — a strong signal of invention rather
    than genuine reference, since real fixes almost always cite a small,
    well-known set of standards."""
    for match in _ERC_PATTERN.finditer(text):
        if match.group(1) not in _KNOWN_ERC_NUMBERS:
            return True
    return False
```

Add this as an additional check alongside the existing `looks_contaminated()` call:
```python
if looks_contaminated(result.text) or has_fabricated_standard_reference(result.text):
    finding["confident"] = False
    finding["grounding_warning"] = "Response contained signs of fabricated external references or an unrecognized standard and was flagged automatically."
```

Also add a second, more general backstop that doesn't rely on a hardcoded list: check whether any capitalized "library"-style term the response names (e.g. text matching a pattern like `\b[A-Z][a-zA-Z]+ library\b`) actually appears as a substring anywhere in the original code snippet passed into the prompt. If the response names a library that isn't present in the code at all, flag it the same way. This is more robust than the ERC-number list alone, since it generalizes to fabricated library names beyond just ERC numbers.

### Verification
- Test `has_fabricated_standard_reference()` directly with a string containing "ERC2756" (should return `True`) and one containing "ERC721" (should return `False`).
- Re-run the full test batch and confirm `grounding_warning` now correctly fires on a `missing-zero-check`-style response containing a fake ERC number, while still not firing on clean responses (like the `arbitrary-send-eth` explanation from the earlier diagnostic, which was genuinely clean).

---

## Step 4 (unchanged — still pending): Fix-extraction gate behavior on the renamed-contract test

### Status
Confirmed working as intended: `Fix failed at gate 'extraction': No Solidity code fence found in LLM fix response.` This is exactly the correct, safe behavior from the earlier extraction-gate fix — a malformed fix response was rejected rather than written into a `.sol` file. No further action needed on this specific gate; it's functioning correctly under real conditions.

---

## Summary for the Coding Agent

| Step | File | Change |
|---|---|---|
| 1 | `src/prompts.py` | Replace anti-hallucination instruction with the stronger version above (no inventing libraries/standards/URLs, state uncertainty explicitly instead) |
| 2 | `src/llm/ollama_client.py` | Set `temperature: 0.2` explicitly in generation options |
| 3 | `src/llm/contamination_filter.py` | Add `has_fabricated_standard_reference()` (ERC/EIP number check) and a general library-name-not-in-source check; wire both into the existing contamination check alongside `looks_contaminated()` |
| 4 | None | Extraction gate already confirmed working — no change needed |

## Re-test Checklist
1. Re-run `unseen_test_example.sol` (original name) with all three fixes applied
2. Confirm the `missing-zero-check` explanation contains no fabricated libraries, standards, or URLs
3. Run it 2-3 times to confirm consistency, not a one-off clean result
4. Confirm `grounding_warning` fires correctly on a deliberately-mocked response containing a fake ERC number, and does NOT fire on the known-clean `arbitrary-send-eth` explanation
5. Re-run the full original 5-contract sample batch to confirm no regressions on previously-working explanations
6. Only after this passes consistently should eval harness numbers (Step 20/29) be considered trustworthy for this vulnerability type specifically — flag `missing-zero-check` as a category worth extra scrutiny in your eval results given its history of grounding issues
