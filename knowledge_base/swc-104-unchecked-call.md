# Unchecked external call return value
Low-level call, delegatecall, and send return a success flag instead of automatically reverting. Ignoring it can make the caller report success while an operation failed, leaving accounting inconsistent. Check the boolean and revert or compensate on failure; use safe transfer abstractions where appropriate.
