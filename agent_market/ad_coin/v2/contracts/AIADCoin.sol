// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/**
 * @title AIADCoin (AI AD Coin - Verified Attention Utility Token)
 * @notice Draft ERC-20 with reserve-checked minting. Not audited; not for mainnet use.
 * @dev Safety rules:
 *  - Minting fails closed: it needs a configured reserve feed with a positive, fresh answer
 *    in the token's decimals that covers the new total supply.
 *  - The owner is expected to be a multisig contract; ownership moves in two steps.
 *  - Changing the bridge minter or the reserve feed waits for CHANGE_DELAY after scheduling.
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

/// Chainlink-style aggregator interface used by Proof of Reserve feeds.
interface IReserveFeed {
    function decimals() external view returns (uint8);
    function latestRoundData()
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound);
}

contract AIADCoin is IERC20 {
    string public constant name = "AI AD Coin";
    string public constant symbol = "AIAC";
    uint8 public constant decimals = 6;

    /// Reserve answers older than this are treated as missing.
    uint256 public constant MAX_RESERVE_AGE = 1 days;
    /// Delay between scheduling and applying a minter or feed change.
    uint256 public constant CHANGE_DELAY = 2 days;
    /// A scheduled change expires if it is not applied within this window after it becomes ready.
    uint256 public constant CHANGE_GRACE = 7 days;

    uint256 private _totalSupply;
    mapping(address => uint256) private _balances;
    mapping(address => mapping(address => uint256)) private _allowances;

    address public owner;
    address public pendingOwner;
    address public bridgeMinter;
    address public reserveFeed;
    bool public paused;

    enum Setting { BridgeMinter, ReserveFeed }

    struct PendingChange {
        address value;
        uint256 readyAt;
    }

    mapping(Setting => PendingChange) public pendingChanges;

    event Mint(address indexed to, uint256 amount, string externalRef);
    event Burn(address indexed from, uint256 amount, string destinationRef);
    event Paused(address indexed account);
    event Unpaused(address indexed account);
    event OwnershipTransferStarted(address indexed previousOwner, address indexed newOwner);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event ChangeScheduled(Setting indexed setting, address indexed value, uint256 readyAt);
    event ChangeCancelled(Setting indexed setting, address indexed value);
    event BridgeMinterUpdated(address indexed previousMinter, address indexed newMinter);
    event ReserveFeedUpdated(address indexed previousFeed, address indexed newFeed);

    error Unauthorized();
    error ContractPaused();
    error ZeroAddress();
    error OwnerMustBeContract();
    error InsufficientBalance();
    error InsufficientAllowance();
    error ReserveFeedMissing();
    error ReserveDecimalsMismatch(uint8 feedDecimals);
    error ReserveAnswerInvalid(int256 answer);
    error ReserveAnswerStale(uint256 updatedAt);
    error ReserveDeficitDetected(uint256 circulatingSupply, uint256 custodyReserves);
    error NoPendingChange();
    error ChangeNotReady(uint256 readyAt);
    error ChangeExpired(uint256 readyAt);

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    modifier onlyBridgeMinter() {
        if (msg.sender != bridgeMinter) revert Unauthorized();
        _;
    }

    modifier whenNotPaused() {
        if (paused) revert ContractPaused();
        _;
    }

    constructor(address initialOwner, address initialMinter, address initialFeed) {
        _requireMultisig(initialOwner);
        if (initialMinter == address(0) || initialFeed == address(0)) revert ZeroAddress();
        owner = initialOwner;
        bridgeMinter = initialMinter;
        reserveFeed = initialFeed;
        emit OwnershipTransferred(address(0), initialOwner);
        emit BridgeMinterUpdated(address(0), initialMinter);
        emit ReserveFeedUpdated(address(0), initialFeed);
    }

    // ---------- ERC-20 ----------

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
        if (spender == address(0)) revert ZeroAddress();
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

    // ---------- supply ----------

    /**
     * @notice Mint tokens backed 1:1 by confirmed custodian deposits.
     * @dev Reverts unless the reserve feed proves the new total supply is covered.
     */
    function mint(address to, uint256 amount, string calldata externalRef) external onlyBridgeMinter whenNotPaused {
        if (to == address(0)) revert ZeroAddress();
        uint256 newSupply = _totalSupply + amount;
        uint256 reserves = currentReserves();
        if (reserves < newSupply) revert ReserveDeficitDetected(newSupply, reserves);

        _totalSupply = newSupply;
        unchecked {
            _balances[to] += amount;
        }
        emit Transfer(address(0), to, amount);
        emit Mint(to, amount, externalRef);
    }

    /// @notice Burn tokens for redemption. Paused together with transfers.
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

    /// @notice The latest verified reserve amount, in token units. Reverts when it cannot be trusted.
    function currentReserves() public view returns (uint256) {
        address feed = reserveFeed;
        if (feed == address(0)) revert ReserveFeedMissing();
        uint8 feedDecimals = IReserveFeed(feed).decimals();
        if (feedDecimals != decimals) revert ReserveDecimalsMismatch(feedDecimals);
        (uint80 roundId, int256 answer, , uint256 updatedAt, uint80 answeredInRound) =
            IReserveFeed(feed).latestRoundData();
        if (answer <= 0) revert ReserveAnswerInvalid(answer);
        if (updatedAt == 0 || updatedAt > block.timestamp || answeredInRound < roundId) {
            revert ReserveAnswerStale(updatedAt);
        }
        if (block.timestamp - updatedAt > MAX_RESERVE_AGE) revert ReserveAnswerStale(updatedAt);
        return uint256(answer);
    }

    function _transfer(address from, address to, uint256 value) internal {
        if (to == address(0)) revert ZeroAddress();
        uint256 bal = _balances[from];
        if (bal < value) revert InsufficientBalance();
        unchecked {
            _balances[from] = bal - value;
            _balances[to] += value;
        }
        emit Transfer(from, to, value);
    }

    // ---------- ownership (two steps, multisig contract) ----------

    function transferOwnership(address newOwner) external onlyOwner {
        _requireMultisig(newOwner);
        pendingOwner = newOwner;
        emit OwnershipTransferStarted(owner, newOwner);
    }

    function acceptOwnership() external {
        if (msg.sender != pendingOwner) revert Unauthorized();
        address previous = owner;
        owner = msg.sender;
        pendingOwner = address(0);
        emit OwnershipTransferred(previous, msg.sender);
    }

    function _requireMultisig(address account) private view {
        if (account == address(0)) revert ZeroAddress();
        if (account.code.length == 0) revert OwnerMustBeContract();
    }

    // ---------- delayed settings ----------

    function scheduleChange(Setting setting, address value) external onlyOwner {
        if (value == address(0)) revert ZeroAddress();
        uint256 readyAt = block.timestamp + CHANGE_DELAY;
        pendingChanges[setting] = PendingChange(value, readyAt);
        emit ChangeScheduled(setting, value, readyAt);
    }

    function cancelChange(Setting setting) external onlyOwner {
        PendingChange memory change = pendingChanges[setting];
        if (change.readyAt == 0) revert NoPendingChange();
        delete pendingChanges[setting];
        emit ChangeCancelled(setting, change.value);
    }

    function applyChange(Setting setting) external onlyOwner {
        PendingChange memory change = pendingChanges[setting];
        if (change.readyAt == 0) revert NoPendingChange();
        if (block.timestamp < change.readyAt) revert ChangeNotReady(change.readyAt);
        if (block.timestamp > change.readyAt + CHANGE_GRACE) revert ChangeExpired(change.readyAt);
        delete pendingChanges[setting];
        if (setting == Setting.BridgeMinter) {
            emit BridgeMinterUpdated(bridgeMinter, change.value);
            bridgeMinter = change.value;
        } else {
            emit ReserveFeedUpdated(reserveFeed, change.value);
            reserveFeed = change.value;
        }
    }

    // ---------- emergency ----------

    /// @notice Pausing is immediate so the multisig can stop transfers, mints and burns in an incident.
    function setPaused(bool _paused) external onlyOwner {
        paused = _paused;
        if (_paused) emit Paused(msg.sender);
        else emit Unpaused(msg.sender);
    }
}
