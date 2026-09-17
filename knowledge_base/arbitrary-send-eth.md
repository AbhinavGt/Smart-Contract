# Arbitrary send of ether

The Slither `arbitrary-send-eth` detector identifies a function that sends
contract-held ether to an address controlled by the caller or otherwise lacks
authorization for a privileged transfer. This is an access-control problem,
not automatically a reentrancy problem. The function should restrict callers
with an owner or role check and validate the intended recipient and amount.
Review who controls the destination address and whether the transfer is
reachable by untrusted callers.
