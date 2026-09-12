// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract CleanStorageExample {
    uint256 private value;

    function setValue(uint256 next) external {
        value = next;
    }

    function getValue() external view returns (uint256) {
        return value;
    }
}
