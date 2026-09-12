# Require revert strings

Long revert strings increase deployed bytecode and can increase execution
cost. Custom errors are usually smaller and cheaper while retaining useful
failure information.
