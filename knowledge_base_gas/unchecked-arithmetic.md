# Safe unchecked arithmetic

When surrounding invariants prove an arithmetic operation cannot overflow,
`unchecked` can avoid redundant checks in tight loops. Only use it with clear
proofs and tests; safety comes before a small gas saving.
