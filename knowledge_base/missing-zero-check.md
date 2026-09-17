# Missing zero-address check

The Slither `missing-zero-check` detector identifies an address assignment or
use that does not reject the zero address when zero would make the contract
unusable or send funds incorrectly. A suitable fix is usually
`require(addressValue != address(0), "...");` before the assignment or use.
Do not confuse this detector with access control, reentrancy, or signature
replay; the relevant evidence is the address value and its validation.
