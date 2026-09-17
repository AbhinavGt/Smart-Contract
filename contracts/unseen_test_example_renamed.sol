// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TestContractAlpha {
    address public owner;
    mapping(address => uint256) public vaultBalances;
    bool public paused;

    constructor() {
        owner = msg.sender;
    }

    function deposit() public payable {
        require(!paused, "contract is paused");
        vaultBalances[msg.sender] += msg.value;
    }

    // VULNERABILITY: missing access control.
    // Anyone can call this and pause/unpause the vault, including draining
    // control away from the intended owner. There is no onlyOwner-style
    // check or msg.sender comparison anywhere in this function.
    function setPaused(bool _paused) public {
        paused = _paused;
    }

    // VULNERABILITY: missing access control on a privileged withdrawal path.
    // Any caller can withdraw funds belonging to any other address, not just
    // their own, because there is no check that msg.sender == owner and no
    // check that msg.sender is the intended recipient of these funds.
    function emergencyWithdraw(address payable to, uint256 amount) public {
        require(amount <= address(this).balance, "insufficient contract balance");
        (bool success, ) = to.call{value: amount}("");
        require(success, "withdraw failed");
    }

    function getVaultBalance(address user) public view returns (uint256) {
        return vaultBalances[user];
    }
}
