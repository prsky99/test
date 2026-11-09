// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

import {AIADCoin} from "../AIADCoin.sol";
import {MockFeed, MockMultisig, Vm} from "./Mocks.sol";

/// Behaviour tests for the defect list C1-C8 in docs/AD_COIN_TOKEN_CONTRACT.md. Local only.
contract AIADCoinTest {
    Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    AIADCoin token;
    MockFeed feed;
    MockMultisig owner;
    address constant MINTER = address(0xB0B);
    address constant ALICE = address(0xA11CE);
    uint256 constant T0 = 1_800_000_000;

    function setUp() public {
        vm.warp(T0);
        feed = new MockFeed();
        owner = new MockMultisig();
        token = new AIADCoin(address(owner), MINTER, address(feed));
        feed.set(1_000_000_000, T0);
    }

    function _mint(address to, uint256 amount) internal {
        vm.prank(MINTER);
        token.mint(to, amount, "ref");
    }

    function _asOwner(bytes memory data) internal {
        owner.exec(address(token), data);
    }

    function _eq(uint256 a, uint256 b) internal pure {
        require(a == b, "not equal");
    }

    // ---------- C1 / C2: reserve check fails closed ----------

    function test_C1_mints_when_reserves_cover_new_supply() public {
        _mint(ALICE, 1_000_000_000);
        _eq(token.totalSupply(), 1_000_000_000);
        _eq(token.balanceOf(ALICE), 1_000_000_000);
    }

    function test_C1_refuses_mint_above_reserves() public {
        _mint(ALICE, 600_000_000);
        vm.expectRevert(abi.encodeWithSelector(AIADCoin.ReserveDeficitDetected.selector, 1_100_000_000, 1_000_000_000));
        _mint(ALICE, 500_000_000);
    }

    function test_C1_refuses_zero_or_negative_answer() public {
        feed.set(0, T0);
        vm.expectRevert(abi.encodeWithSelector(AIADCoin.ReserveAnswerInvalid.selector, int256(0)));
        _mint(ALICE, 1);
        feed.set(-5, T0);
        vm.expectRevert(abi.encodeWithSelector(AIADCoin.ReserveAnswerInvalid.selector, int256(-5)));
        _mint(ALICE, 1);
    }

    function test_C1_refuses_wrong_decimals() public {
        feed.setDecimals(18);
        vm.expectRevert(abi.encodeWithSelector(AIADCoin.ReserveDecimalsMismatch.selector, uint8(18)));
        _mint(ALICE, 1);
    }

    function test_C1_refuses_incomplete_round() public {
        feed.setRounds(5, 4);
        vm.expectRevert(abi.encodeWithSelector(AIADCoin.ReserveAnswerStale.selector, T0));
        _mint(ALICE, 1);
    }

    function test_C2_refuses_stale_answer() public {
        vm.warp(T0 + 1 days + 1);
        vm.expectRevert(abi.encodeWithSelector(AIADCoin.ReserveAnswerStale.selector, T0));
        _mint(ALICE, 1);
    }

    function test_C2_accepts_answer_exactly_one_day_old() public {
        vm.warp(T0 + 1 days);
        _mint(ALICE, 1);
    }

    function test_C2_refuses_future_or_missing_timestamp() public {
        feed.set(1_000_000_000, T0 + 60);
        vm.expectRevert(abi.encodeWithSelector(AIADCoin.ReserveAnswerStale.selector, T0 + 60));
        _mint(ALICE, 1);
        feed.set(1_000_000_000, 0);
        vm.expectRevert(abi.encodeWithSelector(AIADCoin.ReserveAnswerStale.selector, uint256(0)));
        _mint(ALICE, 1);
    }

    function testFuzz_C1_never_mints_beyond_reserves(uint256 reserves, uint256 amount) public {
        reserves = reserves % 1e30 + 1;
        amount = amount % 1e30;
        feed.set(int256(reserves), T0);
        vm.prank(MINTER);
        try token.mint(ALICE, amount, "ref") {
            require(token.totalSupply() <= reserves, "minted beyond reserves");
        } catch {
            require(amount > reserves, "refused a covered mint");
        }
    }

    // ---------- C3: multisig owner, two-step transfer ----------

    function test_C3_constructor_refuses_eoa_owner() public {
        vm.expectRevert(AIADCoin.OwnerMustBeContract.selector);
        new AIADCoin(ALICE, MINTER, address(feed));
    }

    function test_C3_two_step_ownership_transfer() public {
        MockMultisig next = new MockMultisig();
        _asOwner(abi.encodeCall(AIADCoin.transferOwnership, (address(next))));
        require(token.owner() == address(owner), "moved before acceptance");
        require(token.pendingOwner() == address(next), "pending not set");
        vm.expectRevert(AIADCoin.Unauthorized.selector);
        owner.exec(address(token), abi.encodeCall(AIADCoin.acceptOwnership, ()));
        next.exec(address(token), abi.encodeCall(AIADCoin.acceptOwnership, ()));
        require(token.owner() == address(next) && token.pendingOwner() == address(0), "not transferred");
    }

    function test_C3_transfer_refuses_eoa_and_strangers() public {
        vm.expectRevert(AIADCoin.OwnerMustBeContract.selector);
        _asOwner(abi.encodeCall(AIADCoin.transferOwnership, (ALICE)));
        MockMultisig other = new MockMultisig();
        vm.prank(ALICE);
        vm.expectRevert(AIADCoin.Unauthorized.selector);
        token.transferOwnership(address(other));
    }

    // ---------- C4: delayed minter and feed changes ----------

    function test_C4_change_waits_two_days() public {
        address newMinter = address(0xC0FFEE);
        _asOwner(abi.encodeCall(AIADCoin.scheduleChange, (AIADCoin.Setting.BridgeMinter, newMinter)));
        vm.warp(T0 + 2 days - 1);
        vm.expectRevert(abi.encodeWithSelector(AIADCoin.ChangeNotReady.selector, T0 + 2 days));
        _asOwner(abi.encodeCall(AIADCoin.applyChange, (AIADCoin.Setting.BridgeMinter)));
        vm.warp(T0 + 2 days);
        _asOwner(abi.encodeCall(AIADCoin.applyChange, (AIADCoin.Setting.BridgeMinter)));
        require(token.bridgeMinter() == newMinter, "minter not changed");
    }

    function test_C4_change_expires_after_grace() public {
        MockFeed newFeed = new MockFeed();
        _asOwner(abi.encodeCall(AIADCoin.scheduleChange, (AIADCoin.Setting.ReserveFeed, address(newFeed))));
        vm.warp(T0 + 2 days + 7 days + 1);
        vm.expectRevert(abi.encodeWithSelector(AIADCoin.ChangeExpired.selector, T0 + 2 days));
        _asOwner(abi.encodeCall(AIADCoin.applyChange, (AIADCoin.Setting.ReserveFeed)));
        require(token.reserveFeed() == address(feed), "feed changed after expiry");
    }

    function test_C4_cancel_and_owner_only() public {
        _asOwner(abi.encodeCall(AIADCoin.scheduleChange, (AIADCoin.Setting.BridgeMinter, address(0xC0FFEE))));
        _asOwner(abi.encodeCall(AIADCoin.cancelChange, (AIADCoin.Setting.BridgeMinter)));
        vm.warp(T0 + 3 days);
        vm.expectRevert(AIADCoin.NoPendingChange.selector);
        _asOwner(abi.encodeCall(AIADCoin.applyChange, (AIADCoin.Setting.BridgeMinter)));
        vm.prank(ALICE);
        vm.expectRevert(AIADCoin.Unauthorized.selector);
        token.scheduleChange(AIADCoin.Setting.BridgeMinter, ALICE);
    }

    // ---------- C5: only the bridge minter mints ----------

    function test_C5_owner_cannot_mint() public {
        vm.expectRevert(AIADCoin.Unauthorized.selector);
        _asOwner(abi.encodeCall(AIADCoin.mint, (ALICE, 1, "ref")));
        vm.prank(ALICE);
        vm.expectRevert(AIADCoin.Unauthorized.selector);
        token.mint(ALICE, 1, "ref");
    }

    // ---------- C6: zero addresses refused ----------

    function test_C6_zero_addresses_refused() public {
        vm.expectRevert(AIADCoin.ZeroAddress.selector);
        _mint(address(0), 1);
        vm.expectRevert(AIADCoin.ZeroAddress.selector);
        new AIADCoin(address(owner), address(0), address(feed));
        vm.expectRevert(AIADCoin.ZeroAddress.selector);
        new AIADCoin(address(owner), MINTER, address(0));
        vm.expectRevert(AIADCoin.ZeroAddress.selector);
        _asOwner(abi.encodeCall(AIADCoin.scheduleChange, (AIADCoin.Setting.ReserveFeed, address(0))));
        _mint(ALICE, 10);
        vm.prank(ALICE);
        vm.expectRevert(AIADCoin.ZeroAddress.selector);
        token.transfer(address(0), 1);
        vm.prank(ALICE);
        vm.expectRevert(AIADCoin.ZeroAddress.selector);
        token.approve(address(0), 1);
    }

    // ---------- pause and supply invariant ----------

    function test_pause_stops_transfer_mint_and_burn() public {
        _mint(ALICE, 10);
        _asOwner(abi.encodeCall(AIADCoin.setPaused, (true)));
        vm.prank(ALICE);
        vm.expectRevert(AIADCoin.ContractPaused.selector);
        token.transfer(MINTER, 1);
        vm.expectRevert(AIADCoin.ContractPaused.selector);
        _mint(ALICE, 1);
        vm.prank(ALICE);
        vm.expectRevert(AIADCoin.ContractPaused.selector);
        token.burn(1, "dest");
    }

    function testFuzz_supply_equals_balances(uint64 a, uint64 b, uint64 burnAmount) public {
        feed.set(int256(uint256(type(uint128).max)), T0);
        _mint(ALICE, a);
        _mint(MINTER, b);
        uint256 burnt = uint256(burnAmount) % (uint256(a) + 1);
        vm.prank(ALICE);
        token.burn(burnt, "dest");
        _eq(token.totalSupply(), token.balanceOf(ALICE) + token.balanceOf(MINTER));
    }
}
