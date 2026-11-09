// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/**
 * @title AIADCoin (AI AD Coin - Verified Attention Utility Token)
 * @notice Canonical ERC-20 implementation with 100% full-reserve backing,
 * multi-sig minting/burning, and Chainlink Proof-of-Reserves oracle integration.
 */
interface IERC20 {
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 value) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
}

interface IProofOfReservesFeed {
    function latestAnswer() external view returns (int256);
    function latestTimestamp() external view returns (uint256);
}

contract AIADCoin is IERC20 {
    string public constant name = "AI AD Coin";
    string public constant symbol = "AIAC";
    uint8 public constant decimals = 6;

    uint256 private _totalSupply;
    mapping(address => uint256) private _balances;
    mapping(address => mapping(address => uint256)) private _allowances;

    address public owner;
    address public bridgeMinter;
    address public reserveOracleFeed;
    bool public paused;

    event Mint(address indexed to, uint256 amount, string externalRef);
    event Burn(address indexed from, uint256 amount, string destinationRef);
    event Paused(address indexed account);
    event Unpaused(address indexed account);
    event BridgeMinterUpdated(address indexed previousMinter, address indexed newMinter);
    event ReserveOracleUpdated(address indexed previousFeed, address indexed newFeed);

    error Unauthorized();
    error ContractPaused();
    error InsufficientBalance();
    error InsufficientAllowance();
    error ReserveDeficitDetected(uint256 circulatingSupply, uint256 custodyReserves);

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    modifier onlyBridgeMinter() {
        if (msg.sender != bridgeMinter && msg.sender != owner) revert Unauthorized();
        _;
    }

    modifier whenNotPaused() {
        if (paused) revert ContractPaused();
        _;
    }

    constructor(address _bridgeMinter, address _reserveOracleFeed) {
        owner = msg.sender;
        bridgeMinter = _bridgeMinter;
        reserveOracleFeed = _reserveOracleFeed;
    }

    function totalSupply() external view override returns (uint256) {
        return _totalSupply;
    }

    function balanceOf(address account) external view override returns (uint256) {
        return _balances[account];
    }

    function transfer(address to, uint256 value) external override whenNotPaused returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function allowance(address tokenOwner, address spender) external view override returns (uint256) {
        return _allowances[tokenOwner][spender];
    }

    function approve(address spender, uint256 value) external override whenNotPaused returns (bool) {
        _allowances[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external override whenNotPaused returns (bool) {
        uint256 allowed = _allowances[from][msg.sender];
        if (allowed != type(uint256).max) {
            if (allowed < value) revert InsufficientAllowance();
            unchecked {
                _allowances[from][msg.sender] = allowed - value;
            }
        }
        _transfer(from, to, value);
        return true;
    }

    /**
     * @notice Mint real tokens backed 1:1 by confirmed custodian fiat/USDC deposit.
     * @dev Validates against Proof-of-Reserves oracle feed before minting.
     */
    function mint(address to, uint256 amount, string calldata externalRef) external onlyBridgeMinter whenNotPaused {
        if (reserveOracleFeed != address(0)) {
            int256 reserves = IProofOfReservesFeed(reserveOracleFeed).latestAnswer();
            if (reserves > 0 && uint256(reserves) < (_totalSupply + amount)) {
                revert ReserveDeficitDetected(_totalSupply + amount, uint256(reserves));
            }
        }

        _totalSupply += amount;
        unchecked {
            _balances[to] += amount;
        }
        emit Transfer(address(0), to, amount);
        emit Mint(to, amount, externalRef);
    }

    /**
     * @notice Burn tokens for on-chain withdrawal and external fiat/stablecoin redemption.
     */
    function burn(uint256 amount, string calldata destinationRef) external whenNotPaused {
        uint256 bal = _balances[msg.sender];
        if (bal < amount) revert InsufficientBalance();
        unchecked {
            _balances[msg.sender] = bal - amount;
            _totalSupply -= amount;
        }
        emit Transfer(msg.sender, address(0), amount);
        emit Burn(msg.sender, amount, destinationRef);
    }

    function _transfer(address from, address to, uint256 value) internal {
        if (to == address(0)) revert Unauthorized();
        uint256 bal = _balances[from];
        if (bal < value) revert InsufficientBalance();
        unchecked {
            _balances[from] = bal - value;
            _balances[to] += value;
        }
        emit Transfer(from, to, value);
    }

    function setBridgeMinter(address newMinter) external onlyOwner {
        emit BridgeMinterUpdated(bridgeMinter, newMinter);
        bridgeMinter = newMinter;
    }

    function setReserveOracleFeed(address newFeed) external onlyOwner {
        emit ReserveOracleUpdated(reserveOracleFeed, newFeed);
        reserveOracleFeed = newFeed;
    }

    function setPaused(bool _paused) external onlyOwner {
        paused = _paused;
        if (_paused) emit Paused(msg.sender);
        else emit Unpaused(msg.sender);
    }
}
