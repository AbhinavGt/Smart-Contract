// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
contract UncheckedCallExample {
    function notify(address target, bytes calldata data) external { target.call(data); }
}
