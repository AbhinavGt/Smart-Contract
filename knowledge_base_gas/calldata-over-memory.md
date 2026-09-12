# Prefer calldata for read-only arrays

External functions that only read array or byte arguments should use
`calldata` rather than `memory`. This avoids copying arguments into memory.
