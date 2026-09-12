# Costly loop bodies

External calls, repeated hashing, and storage access inside loops multiply
their gas cost. Move invariant work outside the loop, cache values in memory,
and prefer pull-based processing for large sets.
