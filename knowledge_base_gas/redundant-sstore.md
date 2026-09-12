# Redundant storage writes

Each SSTORE is costly, especially when a value is written multiple times in a
transaction. Avoid assignments that do not change state and combine updates
so storage is written once.
