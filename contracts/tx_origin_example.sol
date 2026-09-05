// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
contract TxOriginExample {
    address public owner;
    constructor() { owner = msg.sender; }
    function withdraw() external { require(tx.origin == owner, "not owner"); payable(msg.sender).transfer(address(this).balance); }
}
