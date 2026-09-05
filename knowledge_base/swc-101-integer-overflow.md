# Integer overflow and underflow
Arithmetic outside the representable range wraps in older Solidity versions. A balance can become enormous after subtracting too much, or a counter can wrap to zero. Solidity 0.8 and newer revert by default, but unchecked blocks and legacy code still need explicit bounds checks or safe arithmetic.
