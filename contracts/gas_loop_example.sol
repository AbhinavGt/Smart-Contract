// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract GasLoopExample {
    address[] public members;

    function addMember(address member) external {
        members.push(member);
    }

    function notifyAll() external {
        for (uint256 index = 0; index < members.length; index++) {
            // Deliberately empty: the loop itself grows with storage state.
            members[index];
        }
    }
}
