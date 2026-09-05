# Signature replay
A valid signed message can be reused if it lacks a nonce, chain identifier, expiry, or contract domain. Include a consumed nonce and EIP-712 domain separation, and invalidate signatures after use.
