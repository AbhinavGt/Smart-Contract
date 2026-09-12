# Unbounded storage-array loops

Looping until a storage array's `.length` makes gas grow with user-controlled
state. A transaction can become too expensive or permanently unusable as the
array grows. Use pagination, bounded batches, or maintain an index.
