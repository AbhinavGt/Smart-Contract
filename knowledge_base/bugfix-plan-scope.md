# Bugfix Plan — Enforce Single-Function Fix Scope (Recurring Duplicate-Declaration Failures)

## Context
The critic-loop confidence parser fix is confirmed working — all recent reports correctly show `✅ Confident` where explanations are genuinely solid. This plan addresses a separate, now-confirmed-recurring issue: fix generation for `access_control_example.sol` (and earlier, `unseen_test_example.sol`) fails because the model rewrites the constructor, `setOwner()`, and other existing contract elements from scratch instead of only modifying the single flagged function (`sweep()` / `emergencyWithdraw()`). This produces duplicate declarations and, in this run, an actual Solidity syntax error (`address(this).transfer(payable(msg.sender))` — `.transfer()` must be called on a payable address, not the reverse).

This is exactly the failure mode the original v4 plan's scope rule was written to prevent ("if the LLM's fix requires touching other parts of the contract, mark it `gate_failed: scope` and skip verification") — but that guard was never actually implemented as a pre-compilation check. Right now, out-of-scope fixes go straight to the compiler and surface a wall of confusing errors instead of failing cleanly with a clear, specific reason.

---

## Fix 1: Strengthen the fix-generation prompt to strictly constrain output to the single flagged function

### Where
`src/prompts.py`, `build_fix_prompt()`.

### What to add
Add this explicit constraint, placed prominently near the top of the prompt (before the code/finding content):

```
CRITICAL SCOPE RESTRICTION: You must output ONLY the corrected version of the
single function shown below — nothing else. Do NOT declare a new constructor,
new modifier, or any new function. Do NOT repeat or redeclare the constructor,
other functions, or state variables even if they already exist in the
contract — assume they already exist exactly as-is elsewhere in the file.

If the fix requires restricting access, add the check as an inline statement
directly inside this function's body (e.g. `require(msg.sender == owner, "...");`
using variables that already exist), rather than defining a new modifier.

If you believe this vulnerability genuinely cannot be fixed without changes
outside this single function, respond with exactly the line:
SCOPE_EXCEEDED: <brief reason>
instead of a code fence, and do not attempt a fix.
```

- The `SCOPE_EXCEEDED:` escape hatch is important — it gives the model an explicit, valid way to say "this needs a bigger change" rather than attempting a fix that violates scope and produces confusing compiler errors.
- This also resolves the `.transfer()` misuse pattern indirectly: by restricting the model to only editing inline within the existing function body (which already correctly uses `to.call{value: amount}("")` or similar patterns from the original code), it's far less likely to introduce new, incorrect low-level call syntax from scratch.

### Verification
Re-run against `access_control_example.sol` and confirm the fix response now contains only the corrected `sweep()` function (with an inline `require(msg.sender == owner, ...)` check), with no constructor, modifier, or `setOwner()` redeclaration.

---

## Fix 2: Add a pre-compilation scope-violation guard (implements the v4 plan's originally-intended check)

### Where
`src/autofix/pipeline.py`, in `generate_verified_fix()`, immediately after `extract_code_block()` runs and before `apply_fix_to_temp_copy()` is called.

### What to add
```python
import re

def check_fix_scope(fixed_code: str, target_function_name: str) -> tuple[bool, str | None]:
    """Return (in_scope, reason). Rejects fixes that declare anything beyond
    the single target function — constructors, modifiers, or additional
    function definitions — since these indicate the model attempted a
    multi-location change that this pipeline cannot safely verify."""

    # Explicit escape hatch from the prompt
    if fixed_code.strip().startswith("SCOPE_EXCEEDED"):
        return False, fixed_code.strip()

    # Count function-like and constructor/modifier declarations in the response.
    # A correctly-scoped fix should contain exactly one function declaration:
    # the target function itself.
    declaration_pattern = re.compile(
        r"\b(function\s+\w+|constructor\s*\(|modifier\s+\w+)"
    )
    matches = declaration_pattern.findall(fixed_code)

    function_declarations = [m for m in matches if m.startswith("function")]
    other_declarations = [m for m in matches if not m.startswith("function")]

    if other_declarations:
        return False, f"Fix declares a new constructor or modifier ({other_declarations[0]}), which exceeds single-function scope."

    if len(function_declarations) > 1:
        return False, f"Fix declares {len(function_declarations)} functions; expected exactly one ({target_function_name})."

    if len(function_declarations) == 1 and target_function_name not in fixed_code:
        return False, f"Fix does not appear to contain the target function '{target_function_name}'."

    return True, None
```

Wire it into the pipeline:
```python
fixed_code = extract_code_block(raw_llm_response)  # existing, from earlier bugfix plan

in_scope, scope_reason = check_fix_scope(fixed_code, finding.function_name)
if not in_scope:
    return {"status": "failed", "gate_failed": "scope", "detail": scope_reason}

# only proceed to apply_fix_to_temp_copy() / compilation if in_scope is True
```

### Verification
- Re-run against `access_control_example.sol` and confirm the fix now fails cleanly at `gate_failed: scope` with a clear one-line reason (if the model still tries to redeclare things despite Fix 1's prompt change) — this should never again produce a wall of raw Solidity compiler errors.
- Confirm a correctly-scoped fix (e.g. the reentrancy fix, which only ever touches `withdraw()`) still passes this check without being incorrectly flagged.
- Test `check_fix_scope()` directly with a mocked multi-declaration response (like the one seen in this run) and confirm it returns `False` with a reason mentioning the constructor/modifier.

---

## Fix 3: Update the report formatter to show scope failures clearly

### Where
`src/report/formatter.py`.

### What to change
When `gate_failed == "scope"`, show a distinct, short message rather than the generic failure format used for compilation/interface/static-analysis failures:
```
**Fix verification:**
⚠️ Not attempted — fix required changes beyond the single flagged function
Detail: <scope_reason>
```
This is meaningfully different from "the fix was attempted and failed" (compilation/interface/static-analysis failures) — it's "the fix was correctly recognized as out of scope for this tool and skipped," which is a more accurate and less alarming framing for a reader.

### Verification
Confirm the updated report clearly distinguishes a scope-skip from an actual failed-but-attempted fix.

---

## Summary for the Coding Agent

| File | Change |
|---|---|
| `src/prompts.py` | Add strict single-function scope restriction to `build_fix_prompt()`, including the `SCOPE_EXCEEDED:` escape hatch |
| `src/autofix/pipeline.py` | Add `check_fix_scope()` and call it immediately after code extraction, before compilation is attempted |
| `src/report/formatter.py` | Distinguish `gate_failed: scope` with its own clear, non-alarming message format |

## Re-test Checklist
1. Re-run `access_control_example.sol` — confirm the `sweep()` fix now either succeeds cleanly (inline owner check, no redeclaration) or fails cleanly at the scope gate with a clear one-line reason, never with a wall of compiler errors
2. Re-run `reentrancy_example.sol` — confirm no regression; this fix should continue to pass all three original gates as before
3. Re-run `unseen_test_example.sol` a few times — confirm the same scope guard now catches the earlier "Identifier already declared" pattern cleanly if it recurs, rather than surfacing raw compiler output
4. Once scope violations are cleanly caught rather than producing confusing errors, this is a good point to finally run the deferred consistency check (2-3 repeated runs on `unseen_test_example.sol`) to get a real fix-success-rate number, now that both the confidence-label bug and the scope-handling gap are fixed
