# tx.origin authentication
Using tx.origin for authorization lets a malicious intermediary contract trick an owner into making a call. The origin remains the wallet even though msg.sender is the intermediary. Use msg.sender and explicit roles, ideally through a standard access-control design.
