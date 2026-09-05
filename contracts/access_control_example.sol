// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
contract AccessControlExample {
    address public owner;
    constructor() { owner = msg.sender; }
    function setOwner(address next) external { owner = next; }
    function sweep() external { payable(msg.sender).transfer(address(this).balance); }
}
