# Evaluation iteration log

This is a small, reproducible iteration record for the gas detector (Step 21).
The first prototype flagged every loop whose condition contained `.length`.
On the labeled smoke pair below that produced one true positive
(`gas_loop_example.sol`) and one false positive (`clean_array_loop_example.sol`):
precision **50%**, recall **100%**.

The iteration made the rule storage-aware: it now requires the bound to refer
to a declared storage array. Running:

```bash
python - <<'PY'
from pathlib import Path
from src.agents.gas_agent import detect_gas_patterns
for name in ("gas_loop_example.sol", "clean_array_loop_example.sol"):
    findings = detect_gas_patterns(Path("contracts", name).read_text())
    print(name, [item["type"] for item in findings])
PY
```

now measures one true positive and zero false positives on the same pair:
precision **100%**, recall **100%**. This improves precision without changing
the intended unbounded-storage-loop recall. The rule remains heuristic and
should be reviewed when loops depend on inherited or aliased storage.
