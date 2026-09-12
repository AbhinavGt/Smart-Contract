# Redundant storage reads

An SLOAD is substantially more expensive than a memory read. Reading the same
storage variable repeatedly in one function wastes gas. Cache it in a local
variable and write it back once when the final value is known.
