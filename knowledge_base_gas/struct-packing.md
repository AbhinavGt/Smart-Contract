# Struct packing

Value types smaller than 32 bytes can share a storage slot when adjacent.
Order compatible fields together, while remembering that packing can increase
read-modify-write work when fields are updated independently.
