# Uninitialized storage
A storage pointer declared without an explicit location can write to an unintended slot in vulnerable compiler versions. Initialize references deliberately and compile with a current Solidity compiler. Review constructors and proxy initialization separately.
