// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

interface Vm {
    function warp(uint256) external;
    function prank(address) external;
    function expectRevert(bytes calldata) external;
    function expectRevert(bytes4) external;
}

contract MockFeed {
    uint8 public decimals = 6;
    int256 public answer;
    uint256 public updatedAt;
    uint80 public roundId = 1;
    uint80 public answeredInRound = 1;

    function set(int256 a, uint256 t) external {
        answer = a;
        updatedAt = t;
    }

    function setDecimals(uint8 d) external {
        decimals = d;
    }

    function setRounds(uint80 r, uint80 answered) external {
        roundId = r;
        answeredInRound = answered;
    }

    function latestRoundData() external view returns (uint80, int256, uint256, uint256, uint80) {
        return (roundId, answer, updatedAt, updatedAt, answeredInRound);
    }
}

/// Stands in for a multisig wallet: a contract that forwards calls.
contract MockMultisig {
    function exec(address target, bytes calldata data) external returns (bytes memory) {
        (bool ok, bytes memory result) = target.call(data);
        if (!ok) {
            assembly {
                revert(add(result, 32), mload(result))
            }
        }
        return result;
    }
}
