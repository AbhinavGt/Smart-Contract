# Unsafe delegatecall
Delegatecall executes another contract's code with the caller's storage and balance. An untrusted or upgradeable target can overwrite ownership, balances, or implementation pointers. Restrict targets, validate upgrades, and document storage layouts.
