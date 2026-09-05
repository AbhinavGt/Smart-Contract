// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
contract FrontRunningExample {
    uint256 public price;
    function updatePrice(uint256 next) external { price = next; }
}
