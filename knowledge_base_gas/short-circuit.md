# Short-circuit expensive checks

Put inexpensive checks before expensive calls in `&&` and `||` expressions.
Solidity short-circuits evaluation, so ordering can avoid unnecessary work.
