"""Testing for the utility methods in the pricing models"""
import unittest
import logging
from typing import Union

import elfpy.pricing_models.hyperdrive as hyperdrive_pm
import elfpy.pricing_models.yieldspace as yieldspace_pm
import elfpy.utils.outputs as output_utils
from elfpy.markets.hyperdrive.hyperdrive_market import MarketState

# TODO: remove this after FixedPoint PRs are finished


class BasePricingModelUtilsTest(unittest.TestCase):
    """Unit tests for price utilities"""

    def run_calc_k_const_test(
        self, pricing_model: Union[yieldspace_pm.YieldspacePricingModel, hyperdrive_pm.HyperdrivePricingModel]
    ):
        """Unit tests for calc_k_const function

        .. todo:: fix test to use new y+s expected value instead of 2y+cz
        """
        output_utils.setup_logging("test_pricing_model_utils")
        test_cases = [
            # test 0: 500k share_reserves; 500k bond_reserves
            #   1 share price; 1 init_share_price; 3mo elapsed
            {
                "market_state": MarketState(
                    share_reserves=500_000,  # z = 500000
                    bond_reserves=500_000,  # y = 500000
                    share_price=1,  # c = 1
                    init_share_price=1,  # u = 1
                ),
                "time_elapsed": 0.25,  # t = 0.25
                # k = c/u * (u*z)**t + (2y+c*z)**t
                #   = 1/1 * (1*500000)**0.25 + (2*500000+1*500000)**0.25
                #   = 61.587834600530776
                "expected_result": 61.587834600530776,
            },
            # test 1: 500k share_reserves; 500k bond_reserves
            #   1 share price; 1 init_share_price; 12mo elapsed
            {
                "market_state": MarketState(
                    share_reserves=500_000,  # z = 500000
                    bond_reserves=500_000,  # y = 500000
                    share_price=1,  # c = 1
                    init_share_price=1,  # u = 1
                ),
                "time_elapsed": 1,  # t = 1
                # k = c/u * (u*z)**t + (2y+c*z)**t
                #     = 1/1 * (1*500000)**1 + (2*500000+1*500000)**1
                #     = 2000000
                "expected_result": 2_000_000,
            },
            # test 2: 5M share_reserves; 5M bond_reserves
            #   2 share price; 1.5 init_share_price; 6mo elapsed
            {
                "market_state": MarketState(
                    share_reserves=5_000_000,  # z = 5000000
                    bond_reserves=5_000_000,  # y = 5000000
                    share_price=2,  # c = 2
                    init_share_price=1.5,  # u = 1.5
                ),
                "time_elapsed": 0.50,  # t = 0.50
                # k = c/u * (u*z)**t + (2y+c*z)**t
                #     = 2/1.5 * (1.5*5000000)**0.50 + (2*5000000+2*5000000)**0.50
                #     = 8123.619671700687
                "expected_result": 8_123.619671700687,
            },
            # test 3: 0M share_reserves; 5M bond_reserves
            #   2 share price; 1.5 init_share_price; 3mo elapsed
            {
                "market_state": MarketState(
                    share_reserves=0,  # z = 0
                    bond_reserves=5_000_000,  # y = 5000000
                    share_price=2,  # c = 2
                    init_share_price=1.5,  # u = 1.5
                ),
                "time_elapsed": 0.25,  # t = 0.25
                # k = c/u * (u*z)**t + (2y+c*z)**t
                #     = 2/1.5 * (1.5*0)**0.25 + (2*5000000+2*0)**0.25
                #     = 56.23413251903491
                "expected_result": 56.23413251903491,
            },
            # test 4: 0 share_reserves; 0 bond_reserves
            #   2 share price; 1.5 init_share_price; 3mo elapsed
            {
                "market_state": MarketState(
                    share_reserves=0,  # z = 0
                    bond_reserves=0,  # y = 0
                    share_price=2,  # c = 2
                    init_share_price=1.5,  # u = 1.5
                ),
                "time_elapsed": 0.25,  # t = 0.25
                # k = c/u * (u*z)**t + (2y+c*z)**t
                #     = 2/1.5 * (1.5*0)**0.25 + (2*0+2*0)**0.25
                #     = 0
                "expected_result": 0,
            },
            # test 5: ERROR CASE; 0 INIT SHARE PRICE
            #   5M share_reserves; 5M bond_reserves
            #   2 share price; 1.5 init_share_price; 6mo elapsed
            {
                "market_state": MarketState(
                    share_reserves=5_000_000,  # z = 5000000
                    bond_reserves=5_000_000,  # y = 5000000
                    share_price=2,  # c = 2
                    init_share_price=0,  # ERROR CASE; u = 0
                ),
                "time_elapsed": 0.50,  # t = 0.50
                # k = c/u * (u*z)**t + (2y+c*z)**t
                #     = 1/1 * (1*5000000)**0.50 + (2*5000000+2*5000000)**0.50
                #     = 6708.203932499369
                "is_error_case": True,  # failure case
                "expected_result": ZeroDivisionError,
            },
        ]
        for test_number, test_case in enumerate(test_cases):
            test_case["market_state"].lp_total_supply = (
                test_case["market_state"].bond_reserves
                + test_case["market_state"].share_price * test_case["market_state"].share_reserves
            )
            logging.info("test_number=%s with\n%s", test_number, test_case)
            # Check if this test case is supposed to fail
            if "is_error_case" in test_case and test_case["is_error_case"]:
                # Check that test case throws the expected error
                with self.assertRaises(test_case["expected_result"]):
                    k = float(
                        pricing_model.calc_yieldspace_const(
                            share_reserves=test_case["market_state"].share_reserves,
                            bond_reserves=test_case["market_state"].bond_reserves,
                            lp_total_supply=test_case["market_state"].lp_total_supply,
                            time_elapsed=test_case["time_elapsed"],
                            share_price=test_case["market_state"].share_price,
                            init_share_price=test_case["market_state"].init_share_price,
                        )
                    )
            # If test was not supposed to fail, continue normal execution
            else:
                k = float(
                    pricing_model.calc_yieldspace_const(
                        share_reserves=test_case["market_state"].share_reserves,
                        bond_reserves=test_case["market_state"].bond_reserves,
                        lp_total_supply=test_case["market_state"].lp_total_supply,
                        time_elapsed=test_case["time_elapsed"],
                        share_price=test_case["market_state"].share_price,
                        init_share_price=test_case["market_state"].init_share_price,
                    )
                )
                self.assertAlmostEqual(k, test_case["expected_result"], places=18, msg="unexpected k")

        output_utils.close_logging()


class TestPricingModelUtils(BasePricingModelUtilsTest):
    """Test calculations for each of the pricing model utility functions"""

    def test_calc_k_const(self):
        """Execute the test"""
        self.run_calc_k_const_test(yieldspace_pm.YieldspacePricingModel())
        self.run_calc_k_const_test(hyperdrive_pm.HyperdrivePricingModel())
