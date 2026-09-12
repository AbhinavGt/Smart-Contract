# Batch processing limits

Batch functions should accept a caller-supplied range or maximum item count.
Bounded batches make worst-case gas predictable and let callers continue work
across multiple transactions.
