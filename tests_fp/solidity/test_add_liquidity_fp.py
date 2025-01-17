"""Testing adding & removing liquidity"""

import unittest

import elfpy.agents.agent as agent
import elfpy.markets.hyperdrive.hyperdrive_actions as hyperdrive_actions
import elfpy.markets.hyperdrive.hyperdrive_market as hyperdrive_markets
import elfpy.pricing_models.hyperdrive as hyperdrive_pm
import elfpy.time as time
from elfpy.utils.math import FixedPoint


class TestAddLiquidity(unittest.TestCase):
    """Test adding liquidity to hyperdrive"""

    contribution = FixedPoint("500_000_000.0")
    target_apr = FixedPoint("0.05")
    alice: agent.AgentFP
    bob: agent.AgentFP
    celine: agent.AgentFP
    hyperdrive: hyperdrive_markets.MarketFP
    block_time: time.BlockTimeFP

    def setUp(self):
        self.alice = agent.AgentFP(wallet_address=0, budget=self.contribution)
        self.bob = agent.AgentFP(wallet_address=1, budget=self.contribution)
        self.celine = agent.AgentFP(wallet_address=1, budget=self.contribution)
        self.block_time = time.BlockTimeFP()

        pricing_model = hyperdrive_pm.HyperdrivePricingModelFP()
        market_state = hyperdrive_markets.MarketStateFP()

        self.hyperdrive = hyperdrive_markets.MarketFP(
            pricing_model=pricing_model,
            market_state=market_state,
            block_time=self.block_time,
            position_duration=time.StretchedTimeFP(
                days=FixedPoint("365.0"),
                time_stretch=pricing_model.calc_time_stretch(self.target_apr),
                normalizing_constant=FixedPoint("365.0"),
            ),
        )
        _, wallet_deltas = self.hyperdrive.initialize(self.alice.wallet.address, self.contribution, FixedPoint("0.05"))
        self.alice.wallet.update(wallet_deltas)

    def test_add_liquidity_failure_zero_amount(self):
        """Test adding zero liquidity fails"""
        with self.assertRaises(AssertionError):
            self.hyperdrive.add_liquidity(self.bob.wallet, FixedPoint(0))

    def test_add_liquidity_identical_lp_shares(self):
        """Test adding liquidity equal to the total liquidity of the pool creates the same number of
        shares that are in the pool."""
        lp_supply_before = self.hyperdrive.market_state.lp_total_supply

        # Add liquidity with the same amount as the original contribution.
        market_deltas, wallet_deltas = self.hyperdrive.add_liquidity(self.bob.wallet, self.contribution)

        # Ensure that the contribution was transferred to Hyperdrive.
        self.assertEqual(float(market_deltas.d_base_asset), float(-wallet_deltas.balance.amount))

        # Ensure that the new LP receives the same amount of LP shares as the initializer.
        self.assertAlmostEqual(float(market_deltas.d_lp_total_supply), float(lp_supply_before), places=6)
        self.assertEqual(float(self.hyperdrive.market_state.lp_total_supply), float(lp_supply_before) * 2)

        # Ensure the pool APR is still approximately equal to the target APR.
        pool_apr = self.hyperdrive.pricing_model.calc_apr_from_reserves(
            self.hyperdrive.market_state, self.hyperdrive.position_duration
        )
        self.assertAlmostEqual(float(pool_apr), float(self.target_apr), places=5)

    def test_add_liquidity_with_long_immediately(self):
        """Test adding liquidity when there is a long open.  LP should still get the same number of
        shares as if there weren't any longs open."""
        lp_supply_before = self.hyperdrive.market_state.lp_total_supply

        # Celine opens a long.
        market_deltas, wallet_deltas = hyperdrive_actions.calc_open_long_fp(
            wallet_address=self.celine.wallet.address,
            base_amount=FixedPoint("50_000_000.0"),
            market_state=self.hyperdrive.market_state,
            position_duration=self.hyperdrive.position_duration,
            pricing_model=self.hyperdrive.pricing_model,
            latest_checkpoint_time=self.hyperdrive.latest_checkpoint_time,
            spot_price=self.hyperdrive.spot_price,
        )
        self.hyperdrive.market_state.apply_delta(market_deltas)
        self.celine.wallet.update(wallet_deltas)

        # Add liquidity with the same amount as the original contribution.
        market_deltas, wallet_deltas = self.hyperdrive.add_liquidity(self.bob.wallet, self.contribution)

        # Ensure that the contribution was transferred to Hyperdrive.
        self.assertEqual(float(market_deltas.d_base_asset), float(-wallet_deltas.balance.amount))

        # Ensure that the new LP receives the same amount of LP shares as the initializer.
        self.assertAlmostEqual(float(market_deltas.d_lp_total_supply), float(lp_supply_before), places=6)
        self.assertEqual(float(self.hyperdrive.market_state.lp_total_supply), float(lp_supply_before) * 2)

        # Ensure the pool APR is still approximately equal to the target APR.
        pool_apr = self.hyperdrive.pricing_model.calc_apr_from_reserves(
            self.hyperdrive.market_state, self.hyperdrive.position_duration
        )
        self.assertAlmostEqual(float(pool_apr), float(self.target_apr), places=2)

    def test_add_liquidity_with_short_immediately(self):
        """Test adding liquidity when there is a long short.  LP should still get the same number of
        shares as if there weren't any shorts open."""
        lp_supply_before = self.hyperdrive.market_state.lp_total_supply

        # Celine opens a short.
        market_deltas, wallet_deltas = self.hyperdrive.open_short(
            agent_wallet=self.celine.wallet,
            bond_amount=FixedPoint("50_000_000.0"),
        )

        # Add liquidity with the same amount as the original contribution.
        market_deltas, wallet_deltas = self.hyperdrive.add_liquidity(self.bob.wallet, self.contribution)

        # Ensure that the contribution was transferred to Hyperdrive.
        self.assertEqual(float(market_deltas.d_base_asset), float(-wallet_deltas.balance.amount))

        # Ensure that the new LP receives the same amount of LP shares as the initializer.
        self.assertAlmostEqual(float(market_deltas.d_lp_total_supply), float(lp_supply_before), places=6)
        self.assertEqual(float(self.hyperdrive.market_state.lp_total_supply), float(lp_supply_before) * 2)

        # Ensure the pool APR is still approximately equal to the target APR.
        pool_apr = self.hyperdrive.pricing_model.calc_apr_from_reserves(
            self.hyperdrive.market_state, self.hyperdrive.position_duration
        )
        self.assertAlmostEqual(float(pool_apr), float(self.target_apr), places=2)

    def test_add_liquidity_with_long_at_maturity(self):
        """Test adding liquidity with a long at maturity."""
        # Celine opens a long.
        market_deltas, wallet_deltas = self.hyperdrive.open_long(
            agent_wallet=self.celine.wallet,
            base_amount=FixedPoint("50_000_000.0"),
        )

        # Advance 1 year
        self.block_time.tick(FixedPoint("1.0"))

        # Add liquidity with the same amount as the original contribution.
        market_deltas, wallet_deltas = self.hyperdrive.add_liquidity(self.bob.wallet, self.contribution)

        # Ensure that the contribution was transferred to Hyperdrive.
        self.assertEqual(float(market_deltas.d_base_asset), float(-wallet_deltas.balance.amount))

        # Ensure the pool APR is still approximately equal to the target APR.
        pool_apr = self.hyperdrive.pricing_model.calc_apr_from_reserves(
            self.hyperdrive.market_state, self.hyperdrive.position_duration
        )
        self.assertAlmostEqual(float(pool_apr), float(self.target_apr), places=2)

        # Ensure that if the new LP withdraws, they get their money back.
        market_deltas, wallet_deltas = self.hyperdrive.remove_liquidity(
            agent_wallet=self.bob.wallet,
            lp_shares=self.bob.wallet.lp_tokens,
        )
        self.assertAlmostEqual(float(wallet_deltas.balance.amount), float(self.contribution), places=6)

    def test_add_liquidity_with_short_at_maturity(self):
        """Test adding liquidity with a short at maturity."""
        # Celine opens a short.
        market_deltas, wallet_deltas = self.hyperdrive.open_short(
            agent_wallet=self.celine.wallet,
            bond_amount=FixedPoint("50_000_000.0"),
        )

        # Advance 1 year
        self.block_time.tick(FixedPoint("1.0"))

        # Add liquidity with the same amount as the original contribution.
        market_deltas, wallet_deltas = self.hyperdrive.add_liquidity(
            agent_wallet=self.bob.wallet,
            bond_amount=self.contribution,
        )

        # Ensure that the agent lost money from their wallet
        self.assertAlmostEqual(float(wallet_deltas.balance.amount), float(-self.contribution))

        # Ensure that the contribution was transferred to Hyperdrive.
        self.assertEqual(float(market_deltas.d_base_asset), float(-wallet_deltas.balance.amount))

        # Ensure the pool APR is still approximately equal to the target APR.
        pool_apr = self.hyperdrive.pricing_model.calc_apr_from_reserves(
            self.hyperdrive.market_state, self.hyperdrive.position_duration
        )
        self.assertAlmostEqual(float(pool_apr), float(self.target_apr), places=1)

        # Ensure that if the new LP withdraws, they get their money back.
        market_deltas, wallet_deltas = self.hyperdrive.remove_liquidity(
            agent_wallet=self.bob.wallet,
            lp_shares=self.bob.wallet.lp_tokens,
        )
        # Test that Bob got their money back
        self.assertAlmostEqual(float(wallet_deltas.balance.amount), float(self.contribution), places=6)
