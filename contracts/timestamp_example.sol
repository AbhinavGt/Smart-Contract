// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
contract TimestampExample {
    function isLucky() external view returns (bool) { return block.timestamp % 10 == 0; }
}
