"""Close short market trade tests that match those being executed in the solidity repo"""
import unittest
from decimal import Decimal

import numpy as np

import elfpy.agents.agent as agent
import elfpy.markets.hyperdrive.hyperdrive_market as hyperdrive_market
import elfpy.pricing_models.hyperdrive as hyperdrive_pm
import elfpy.pricing_models.yieldspace as yieldspace_pm
import elfpy.time as time
import elfpy.types as types
from elfpy.time.time import StretchedTime

# pylint: disable=too-many-arguments


class TestCloseShort(unittest.TestCase):
    """
    Test opening and closing a short in hyperdrive
    3 failure cases: zero amount, invalid amount, invalid timestamp
    6 success cases:
        - close immediately, with regular, and small amounts
        - redeem at maturity, with zero interest, and with negative interest (skipped)
        - close halfway thru term, with zero, and negative interest (both skipped)
    """

    contribution: float = 500_000_000
    target_apr: float = 0.05
    term_length: int = 365
    alice: agent.Agent
    bob: agent.Agent
    celine: agent.Agent
    hyperdrive: hyperdrive_market.Market

    def setUp(self):
        """Set up agent, pricing model, & market for the subsequent tests.
        This function is run before each test method.
        """
        self.alice = agent.Agent(wallet_address=0, budget=self.contribution)
        self.bob = agent.Agent(wallet_address=1, budget=self.contribution)
        block_time = time.BlockTime()
        pricing_model = hyperdrive_pm.HyperdrivePricingModel()
        market_state = hyperdrive_market.MarketState(
            curve_fee_multiple=0.0,
            flat_fee_multiple=0.0,
        )
        self.hyperdrive = hyperdrive_market.Market(
            pricing_model=pricing_model,
            market_state=market_state,
            position_duration=time.StretchedTime(
                days=self.term_length,
                time_stretch=pricing_model.calc_time_stretch(self.target_apr),
                normalizing_constant=self.term_length,
            ),
            block_time=block_time,
        )
        _, wallet_deltas = self.hyperdrive.initialize(self.alice.wallet.address, self.contribution, 0.05)
        self.alice.wallet.update(wallet_deltas)

    def verify_close_short(
        self,
        example_agent: agent.Agent,
        market_state_before: hyperdrive_market.MarketState,
        agent_base_paid: float,
        agent_base_proceeds: float,
        bond_amount: float,
        maturity_time: float,
    ):
        """Close a short then make sure the market state is correct"""
        # verify that all of Bob's bonds were burned
        self.assertFalse(
            example_agent.wallet.shorts
        )  # In solidity we check that the balance is zero, but here we delete the entry if it is zero
        # verify that the bond reserves were updated according to flat+curve
        # the adjustment should be equal to timeRemaining * bondAmount
        self.assertLess(  # user gets less than what they put in
            agent_base_proceeds,
            agent_base_paid,
            msg="agent gets more than what they put in: agent_base_proceeds > agent_base_paid",
        )
        time_remaining = 0
        if maturity_time > self.hyperdrive.block_time.time:
            time_remaining = maturity_time - self.hyperdrive.block_time.time
        stretch_time = StretchedTime(
            days=time_remaining * 365, time_stretch=self.hyperdrive.time_stretch_constant, normalizing_constant=365
        )
        model = yieldspace_pm.YieldspacePricingModel()
        curve_shares = float(
            model.calc_shares_in_given_bonds_out(
                Decimal(market_state_before.share_reserves),
                Decimal(market_state_before.bond_reserves),
                Decimal(market_state_before.lp_total_supply),
                Decimal(bond_amount * time_remaining),
                Decimal(1 - stretch_time.stretched_time),
                Decimal(market_state_before.share_price),
                Decimal(market_state_before.init_share_price),
            )
        )
        flat_shares = bond_amount * (1 - time_remaining) / market_state_before.share_price
        np.testing.assert_allclose(
            self.hyperdrive.market_state.share_reserves + flat_shares + curve_shares,
            market_state_before.share_reserves,
            rtol=1e-10,
            err_msg="share_reserves is wrong",
        )
        self.assertEqual(  # lp total supply
            self.hyperdrive.market_state.lp_total_supply,
            market_state_before.lp_total_supply,
            msg="lp_total_supply is wrong",
        )
        self.assertEqual(  # longs outstanding
            self.hyperdrive.market_state.longs_outstanding,
            market_state_before.longs_outstanding,
            msg="longs_outstanding is wrong",
        )
        self.assertEqual(  # long average maturity time
            self.hyperdrive.market_state.long_average_maturity_time,
            0,
            msg="long_average_maturity_time is wrong",
        )
        self.assertEqual(  # long base volume
            self.hyperdrive.market_state.long_base_volume,
            0,
            msg="long_base_volume is wrong",
        )
        checkpoint_time = maturity_time - self.term_length
        self.assertEqual(  # checkpoint long base volume
            self.hyperdrive.market_state.checkpoints[checkpoint_time].long_base_volume,
            0,
            msg=(
                f"The long base volume at {checkpoint_time=} should be zero, "
                f"not {self.hyperdrive.market_state.checkpoints[checkpoint_time].long_base_volume=}."
            ),
        )
        self.assertEqual(  # shorts outstanding
            self.hyperdrive.market_state.shorts_outstanding,
            market_state_before.shorts_outstanding - bond_amount,
            msg="shorts_outstanding is wrong",
        )
        self.assertEqual(  # short average maturity time
            self.hyperdrive.market_state.short_average_maturity_time,
            0,
            msg="short_average_maturity_time is wrong",
        )
        self.assertAlmostEqual(  # short base volume
            self.hyperdrive.market_state.short_base_volume,
            0,
            # TODO: see why this isn't zero
            delta=10,
            msg="short_base_volume is wrong",
        )
        self.assertEqual(  # checkpoint short base volume
            self.hyperdrive.market_state.checkpoints[checkpoint_time].short_base_volume,
            0,
            msg="checkpoint short base volume is wrong",
        )

    def test_close_short_failure_zero_amount(self):
        """Attempt to close shorts using zero bond_amount. This should fail."""
        bond_amount = 10
        self.bob.budget = bond_amount
        self.bob.wallet.balance = types.Quantity(amount=bond_amount, unit=types.TokenType.BASE)
        _ = self.hyperdrive.open_short(
            agent_wallet=self.bob.wallet,
            bond_amount=bond_amount,
        )
        with self.assertRaises(AssertionError):
            self.hyperdrive.close_short(
                agent_wallet=self.bob.wallet,
                bond_amount=0,
                mint_time=list(self.bob.wallet.shorts.keys())[0],
                open_share_price=1,
            )

    def test_close_short_failure_invalid_amount(self):
        """Attempt to close too many shorts. This should fail."""
        bond_amount = 10
        self.bob.budget = bond_amount
        self.bob.wallet.balance = types.Quantity(amount=bond_amount, unit=types.TokenType.BASE)
        _ = self.hyperdrive.open_short(
            agent_wallet=self.bob.wallet,
            bond_amount=bond_amount,
        )
        with self.assertRaises(AssertionError):
            self.hyperdrive.close_short(
                agent_wallet=self.bob.wallet,
                bond_amount=list(self.bob.wallet.shorts.values())[0].balance + 1,
                mint_time=list(self.bob.wallet.shorts.keys())[0],
                open_share_price=1,
            )

    def test_close_short_failure_invalid_timestamp(self):
        """Attempt to use a timestamp greater than the maximum range. This should fail."""
        base_amount = 10
        self.bob.budget = base_amount
        self.bob.wallet.balance = types.Quantity(amount=base_amount, unit=types.TokenType.BASE)
        market_deltas, _ = self.hyperdrive.open_short(
            agent_wallet=self.bob.wallet,
            bond_amount=base_amount,
        )
        with self.assertRaises(ValueError):
            _ = self.hyperdrive.close_short(
                agent_wallet=self.bob.wallet,
                bond_amount=market_deltas.d_bond_asset,
                mint_time=list(self.bob.wallet.shorts.keys())[0] + 1,
                open_share_price=1,
            )

    def test_close_short_immediately_with_regular_amount(self):
        """Open a position, close it immediately, with regular amount"""
        trade_amount = 10  # this will be reflected in BASE in the wallet and PTs in the short
        self.bob.budget = trade_amount
        self.bob.wallet.balance = types.Quantity(amount=trade_amount, unit=types.TokenType.BASE)
        _, agent_deltas_open = self.hyperdrive.open_short(
            agent_wallet=self.bob.wallet,
            bond_amount=trade_amount,
        )
        market_state_before_close = self.hyperdrive.market_state.copy()
        self.hyperdrive.block_time.step()
        _, agent_deltas_close = self.hyperdrive.close_short(
            agent_wallet=self.bob.wallet,
            bond_amount=agent_deltas_open.shorts[0].balance,
            mint_time=0,
            open_share_price=1,
        )
        self.verify_close_short(
            example_agent=self.bob,
            market_state_before=market_state_before_close,
            agent_base_paid=trade_amount,
            agent_base_proceeds=agent_deltas_close.balance.amount,
            bond_amount=agent_deltas_open.shorts[0].balance,
            maturity_time=self.hyperdrive.position_duration.days / 365,
        )

    def test_close_short_immediately_with_small_amount(self):
        """Open a small position, close it immediately, with small amount"""
        trade_amount = 0.01  # this will be reflected in BASE in the wallet and PTs in the short
        self.bob.budget = trade_amount
        self.bob.wallet.balance = types.Quantity(amount=trade_amount, unit=types.TokenType.BASE)
        _, agent_deltas_open = self.hyperdrive.open_short(
            agent_wallet=self.bob.wallet,
            bond_amount=trade_amount,
        )
        market_state_before_close = self.hyperdrive.market_state.copy()
        self.hyperdrive.block_time.step()
        _, agent_deltas_close = self.hyperdrive.close_short(
            agent_wallet=self.bob.wallet,
            bond_amount=agent_deltas_open.shorts[0].balance,
            mint_time=0,
            open_share_price=1,
        )
        self.verify_close_short(
            example_agent=self.bob,
            market_state_before=market_state_before_close,
            agent_base_paid=trade_amount,
            agent_base_proceeds=agent_deltas_close.balance.amount,
            bond_amount=agent_deltas_open.shorts[0].balance,
            maturity_time=self.hyperdrive.position_duration.days / 365,
        )

    def test_close_short_redeem_at_maturity_zero_variable_interest(self):
        """Open a position, advance time all the way through the term, close it, receiving zero variable interest"""
        # Bob opens a short
        trade_amount = 10  # this will be reflected in BASE in the wallet and PTs in the short
        self.bob.budget = trade_amount
        self.bob.wallet.balance = types.Quantity(amount=trade_amount, unit=types.TokenType.BASE)
        _ = self.hyperdrive.market_state.copy()
        _, agent_deltas_open = self.hyperdrive.open_short(
            agent_wallet=self.bob.wallet,
            bond_amount=trade_amount,
        )
        # advance time (which also causes the share price to change)
        time_delta = 1
        self.hyperdrive.block_time.set_time(self.hyperdrive.block_time.time + time_delta)
        # get the reserves before closing the short
        market_state_before_close = self.hyperdrive.market_state.copy()
        # Bob closes his short at to maturity
        _, agent_deltas_close = self.hyperdrive.close_short(
            agent_wallet=self.bob.wallet,
            bond_amount=agent_deltas_open.shorts[0].balance,
            mint_time=0,
            open_share_price=1,
        )
        # nothing received from closing at maturity
        self.assertEqual(agent_deltas_close.balance.amount, 0)
        self.verify_close_short(  # verify that the close short updates were correct
            example_agent=self.bob,
            market_state_before=market_state_before_close,
            agent_base_paid=trade_amount,
            agent_base_proceeds=agent_deltas_close.balance.amount,
            bond_amount=agent_deltas_open.shorts[0].balance,
            maturity_time=self.hyperdrive.position_duration.days / 365,
        )

    # TODO: make the below two negative interest tests work, once negative interest is implemented
    @unittest.skip("Negative interest is not implemented yet")
    def test_close_short_redeem_at_maturity_negative_variable_interest(self):
        """Open a position, advance time all the way through the term, close it, receiving negative variable interest"""
        # Bob opens a short
        trade_amount = 10  # this will be reflected in BASE in the wallet and PTs in the short
        self.bob.budget = trade_amount
        self.bob.wallet.balance = types.Quantity(amount=trade_amount, unit=types.TokenType.BASE)
        _, agent_deltas_open = self.hyperdrive.open_short(
            agent_wallet=self.bob.wallet,
            bond_amount=trade_amount,
        )
        # advance time (which also causes the share price to change)
        time_delta = 1.0
        self.hyperdrive.block_time.set_time(self.hyperdrive.block_time.time + time_delta)
        self.hyperdrive.market_state.share_price = self.hyperdrive.market_state.share_price * 0.8
        # get the reserves before closing the short
        market_state_before_close = self.hyperdrive.market_state.copy()
        # Bob closes his short at to maturity
        _, agent_deltas_close = self.hyperdrive.close_short(
            agent_wallet=self.bob.wallet,
            bond_amount=agent_deltas_open.shorts[0].balance,
            mint_time=0,
            open_share_price=1,
        )
        # nothing received from closing at maturity + negative interest
        self.assertEqual(agent_deltas_close.balance.amount, 0)
        self.verify_close_short(  # verify that the close short updates were correct
            example_agent=self.bob,
            market_state_before=market_state_before_close,
            agent_base_paid=trade_amount,
            agent_base_proceeds=agent_deltas_close.balance.amount,
            bond_amount=agent_deltas_open.shorts[0].balance,
            maturity_time=self.hyperdrive.position_duration.days / 365,
        )

    @unittest.skip("Negative interest is not implemented yet")
    def test_close_short_halfway_through_term_negative_variable_interest(self):
        """Open a position, advance time halfway through the term, close it, receiving negative variable interest"""
        # Bob opens a short
        trade_amount = 10  # how much base the agent is using to open a short
        self.bob.budget = trade_amount
        self.bob.wallet.balance = types.Quantity(amount=trade_amount, unit=types.TokenType.BASE)
        _, agent_deltas_open = self.hyperdrive.open_short(
            agent_wallet=self.bob.wallet,
            bond_amount=trade_amount,
        )
        # advance time (which also causes the share price to change)
        time_delta = 0.5
        self.hyperdrive.block_time.set_time(self.hyperdrive.block_time.time + time_delta)
        self.hyperdrive.market_state.share_price = self.hyperdrive.market_state.share_price * 0.8
        # get the reserves before closing the short
        market_state_before_close = self.hyperdrive.market_state.copy()
        # Bob closes his short half way to maturity
        market_deltas_close, agent_deltas_close = self.hyperdrive.close_short(
            agent_wallet=self.bob.wallet,
            bond_amount=agent_deltas_open.shorts[0].balance,
            mint_time=0,
            open_share_price=1,
        )
        self.assertEqual(  # market swaps the whole position at maturity
            market_deltas_close.d_base_asset,
            agent_deltas_open.shorts[0].balance * 0.8,
        )
        # nothing received from closing due to negative interest
        self.assertEqual(agent_deltas_close.balance.amount, 0)
        self.verify_close_short(  # verify that the close short updates were correct
            example_agent=self.bob,
            market_state_before=market_state_before_close,
            agent_base_paid=trade_amount,
            agent_base_proceeds=agent_deltas_close.balance.amount,
            bond_amount=agent_deltas_open.shorts[0].balance,
            maturity_time=self.hyperdrive.position_duration.days / 365,
        )
