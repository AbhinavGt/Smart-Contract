// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract CleanArrayLoopExample {
    function sum(uint256[] memory values) external pure returns (uint256 total) {
        for (uint256 index = 0; index < values.length; index++) {
            total += values[index];
        }
    }
}
