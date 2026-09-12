// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract CleanViewExample {
    function isEven(uint256 value) external pure returns (bool) {
        return value % 2 == 0;
    }
}
