"""The base pricing model"""
from __future__ import annotations  # types will be strings by default in 3.11

import logging
from abc import ABC
from decimal import Decimal, getcontext
from typing import TYPE_CHECKING

import elfpy
import elfpy.pricing_models.trades as trades
import elfpy.time as time
import elfpy.types as types
import elfpy.utils.price as price_utils
from elfpy.utils.math import FixedPoint

if TYPE_CHECKING:
    import elfpy.markets.hyperdrive.hyperdrive_market as hyperdrive_market


# Set the Decimal precision to be higher than the default of 28. This ensures
# that the pricing models can safely a lowest possible input of 1e-18 with an
# reserves difference of up to 20 billion.
getcontext().prec = 30


class PricingModel(ABC):
    """Contains functions for calculating AMM variables

    Base class should not be instantiated on its own; it is assumed that a user will instantiate a child class
    """

    def calc_in_given_out(
        self,
        out: types.Quantity,
        market_state: hyperdrive_market.MarketState,
        time_remaining: time.StretchedTime,
    ) -> trades.TradeResult:
        """Calculate fees and asset quantity adjustments"""
        raise NotImplementedError

    def calc_out_given_in(
        self,
        in_: types.Quantity,
        market_state: hyperdrive_market.MarketState,
        time_remaining: time.StretchedTime,
    ) -> trades.TradeResult:
        """Calculate fees and asset quantity adjustments"""
        raise NotImplementedError

    def calc_lp_out_given_tokens_in(
        self,
        d_base: float,
        rate: float,
        market_state: hyperdrive_market.MarketState,
        time_remaining: time.StretchedTime,
    ) -> tuple[float, float, float]:
        """Computes the amount of LP tokens to be minted for a given amount of base asset"""
        raise NotImplementedError

    def calc_tokens_out_given_lp_in(
        self,
        lp_in: float,
        market_state: hyperdrive_market.MarketState,
    ) -> tuple[float, float, float]:
        """Calculate how many tokens should be returned for a given lp addition"""
        raise NotImplementedError

    def model_name(self) -> str:
        """Unique name given to the model, can be based on member variable states"""
        raise NotImplementedError

    def model_type(self) -> str:
        """Unique identifier given to the model, should be lower snake_cased name"""
        raise NotImplementedError

    def calc_initial_bond_reserves(
        self,
        target_apr: float,
        time_remaining: time.StretchedTime,
        market_state: hyperdrive_market.MarketState,
    ) -> float:
        """Returns the assumed bond (i.e. token asset) reserve amounts given
        the share (i.e. base asset) reserves and APR for an initialized market

        Parameters
        ----------
        target_apr : float
            Target fixed APR in decimal units (for example, 5% APR would be 0.05)
        time_remaining : StretchedTime
            Amount of time left until bond maturity
        market_state : MarketState
            MarketState object; the following attributes are used:
                share_reserves : float
                    Base asset reserves in the pool
                init_share_price : float
                    Original share price when the pool started
                share_price : float
                    Current share price

        Returns
        -------
        float
            The expected amount of bonds (token asset) in the pool, given the inputs

        .. todo:: test_market.test_initialize_market uses this, but this should also have a unit test
        """
        # Only want to renormalize time for APR ("annual", so hard coded to 365)
        # Don't want to renormalize stretched time
        annualized_time = time.norm_days(time_remaining.days, 365)
        # y = z/2 * (mu * (1 + rt)**(1/tau) - c)
        return (market_state.share_reserves / 2) * (
            market_state.init_share_price * (1 + target_apr * annualized_time) ** (1 / time_remaining.stretched_time)
            - market_state.share_price
        )

    def calc_bond_reserves(
        self,
        target_apr: float,
        time_remaining: time.StretchedTime,
        market_state: hyperdrive_market.MarketState,
    ) -> float:
        """Returns the assumed bond (i.e. token asset) reserve amounts given
        the share (i.e. base asset) reserves and APR

        Parameters
        ----------
        target_apr : float
            Target fixed APR in decimal units (for example, 5% APR would be 0.05)
        time_remaining : StretchedTime
            Amount of time left until bond maturity
        market_state : MarketState
            MarketState object; the following attributes are used:
                share_reserves : float
                    Base asset reserves in the pool
                init_share_price : float
                    Original share price when the pool started
                share_price : float
                    Current share price

        Returns
        -------
        float
            The expected amount of bonds (token asset) in the pool, given the inputs

        .. todo:: Test this function
        """
        # Only want to renormalize time for APR ("annual", so hard coded to 365)
        annualized_time = time.norm_days(time_remaining.days, 365)
        # (1 + r * t) ** (1 / tau)
        interest_factor = (1 + target_apr * annualized_time) ** (1 / time_remaining.stretched_time)
        # mu * z * (1 + apr * t) ** (1 / tau) - l
        return (
            market_state.init_share_price * market_state.share_reserves * interest_factor - market_state.lp_total_supply
        )

    def calc_spot_price_from_reserves(
        self,
        market_state: hyperdrive_market.MarketState,
        time_remaining: time.StretchedTime,
    ) -> float:
        r"""Calculates the spot price of base in terms of bonds.
        The spot price is defined as:

        .. math::
            \begin{align}
                p &= (\frac{y + s}{\mu z})^{-\tau} \\
                  &= (\frac{\mu z}{y + s})^{\tau}
            \end{align}

        Parameters
        ----------
        market_state: MarketState
            The reserves and prices in the pool.
        time_remaining : StretchedTime
            The time remaining for the asset (uses time stretch).

        Returns
        -------
        float
            The spot price of principal tokens.
        """
        return float(
            self._calc_spot_price_from_reserves_high_precision(market_state=market_state, time_remaining=time_remaining)
        )

    def _calc_spot_price_from_reserves_high_precision(
        self,
        market_state: hyperdrive_market.MarketState,
        time_remaining: time.StretchedTime,
    ) -> Decimal:
        r"""Calculates the current market spot price of base in terms of bonds.
        This variant returns the result in a high precision format.
        The spot price is defined as:

        .. math::
            p = (\frac{\mu z}{y + s})^{\tau}

        Parameters
        ----------
        market_state: MarketState
            The reserves and share prices of the pool.
        time_remaining : StretchedTime
            The time remaining for the asset (incorporates time stretch).

        Returns
        -------
        Decimal
            The spot price of principal tokens.
        """
        init_share_price = Decimal(market_state.init_share_price)  # mu
        share_reserves = Decimal(market_state.share_reserves)  # z
        bond_reserves = Decimal(market_state.bond_reserves)  # y
        lp_total_supply = Decimal(market_state.lp_total_supply)  # s
        tau = Decimal(time_remaining.stretched_time)  # tau = days / duration / time_stretch
        # p = ((mu * z) / (y + s))^(tau)
        return ((init_share_price * share_reserves) / (bond_reserves + lp_total_supply)) ** tau

    def calc_apr_from_reserves(
        self,
        market_state: hyperdrive_market.MarketState,
        time_remaining: time.StretchedTime,
    ) -> float:
        r"""Returns the apr given reserve amounts

        Parameters
        ----------
        market_state : MarketState
            The reserves and share prices of the pool
        time_remaining : StretchedTime
            The expiry time for the asset
        """
        spot_price = self.calc_spot_price_from_reserves(
            market_state,
            time_remaining,
        )
        return price_utils.calc_apr_from_spot_price(spot_price, time_remaining)

    def get_max_long(
        self,
        market_state: hyperdrive_market.MarketState,
        time_remaining: time.StretchedTime,
    ) -> tuple[float, float]:
        r"""
        Calculates the maximum long the market can support

        .. math::
            \Delta z' = \mu^{-1} \cdot (\frac{\mu}{c} \cdot (k-(y+c \cdot z)^{1-\tau(d)}))^{\frac{1}{1-\tau(d)}}
            -c \cdot z

        Parameters
        ----------
        market_state : MarketState
            The reserves and share prices of the pool
        time_remaining : StretchedTime
            The time remaining for the asset (incorporates time stretch)

        Returns
        -------
        float
            The maximum amount of base that can be used to purchase bonds.
        float
            The maximum amount of bonds that can be purchased.
        """
        base = self.calc_in_given_out(
            out=types.Quantity(market_state.bond_reserves - market_state.bond_buffer, unit=types.TokenType.PT),
            market_state=market_state,
            time_remaining=time_remaining,
        ).breakdown.with_fee
        bonds = self.calc_out_given_in(
            in_=types.Quantity(amount=base, unit=types.TokenType.BASE),
            market_state=market_state,
            time_remaining=time_remaining,
        ).breakdown.with_fee
        return base, bonds

    def get_max_short(
        self,
        market_state: hyperdrive_market.MarketState,
        time_remaining: time.StretchedTime,
    ) -> tuple[float, float]:
        r"""
        Calculates the maximum short the market can support using the bisection
        method.

        .. math::
            \Delta y' = \mu^{-1} \cdot (\frac{\mu}{c} \cdot k)^{\frac{1}{1-\tau(d)}}-2y-c \cdot z

        Parameters
        ----------
        market_state : MarketState
            The reserves and share prices of the pool.
        time_remaining : StretchedTime
            The time remaining for the asset (incorporates time stretch).

        Returns
        -------
        float
            The maximum amount of base that can be used to short bonds.
        float
            The maximum amount of bonds that can be shorted.
        """
        bonds = self.calc_in_given_out(
            out=types.Quantity(
                market_state.share_reserves - market_state.base_buffer / market_state.share_price,
                unit=types.TokenType.PT,
            ),
            market_state=market_state,
            time_remaining=time_remaining,
        ).breakdown.with_fee
        base = self.calc_out_given_in(
            in_=types.Quantity(amount=bonds, unit=types.TokenType.PT),
            market_state=market_state,
            time_remaining=time_remaining,
        ).breakdown.with_fee
        return base, bonds

    def calc_time_stretch(self, apr: float) -> float:
        """Returns fixed time-stretch value based on current apr (as a decimal)"""
        apr_percent = apr * 100  # bounded between 0 and 100
        return 3.09396 / (0.02789 * apr_percent)  # bounded between ~1.109 (apr=1) and inf (apr=0)

    def check_input_assertions(
        self,
        quantity: types.Quantity,
        market_state: hyperdrive_market.MarketState,
        time_remaining: time.StretchedTime,
    ):
        """Applies a set of assertions to the input of a trading function."""
        assert quantity.amount >= elfpy.WEI, (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected quantity.amount >= {elfpy.WEI}, not {quantity.amount}!"
        )
        assert market_state.share_reserves >= 0, (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected share_reserves >= 0, not {market_state.share_reserves}!"
        )
        assert market_state.bond_reserves >= 0, (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected bond_reserves >= 0"
            f" bond_reserves == 0, not {market_state.bond_reserves}!"
        )
        if market_state.share_price < market_state.init_share_price:
            logging.warning(
                "WARNING: expected share_price >= %g, not share_price=%g",
                market_state.init_share_price,
                market_state.share_price,
            )
        assert market_state.init_share_price >= 1, (
            f"pricing_models.check_input_assertions: ERROR: "
            f"expected init_share_price >= 1, not share_price={market_state.init_share_price}"
        )
        reserves_difference = abs(market_state.share_reserves * market_state.share_price - market_state.bond_reserves)
        assert reserves_difference < elfpy.MAX_RESERVES_DIFFERENCE, (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected reserves_difference < {elfpy.MAX_RESERVES_DIFFERENCE}, not {reserves_difference}!"
        )
        assert 1 >= market_state.curve_fee_multiple >= 0, (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected 1 >= curve_fee_multiple >= 0, not {market_state.curve_fee_multiple}!"
        )
        assert 1 >= market_state.flat_fee_multiple >= 0, (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected 1 >= flat_fee_multiple >= 0, not {market_state.flat_fee_multiple}!"
        )
        assert 1 + elfpy.PRECISION_THRESHOLD >= time_remaining.stretched_time >= -elfpy.PRECISION_THRESHOLD, (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected {1 + elfpy.PRECISION_THRESHOLD} > time_remaining.stretched_time >= {-elfpy.PRECISION_THRESHOLD}"
            f", not {time_remaining.stretched_time}!"
        )
        assert 1 + elfpy.PRECISION_THRESHOLD >= time_remaining.normalized_time >= -elfpy.PRECISION_THRESHOLD, (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected {1 + elfpy.PRECISION_THRESHOLD} > time_remaining >= {-elfpy.PRECISION_THRESHOLD}"
            f", not {time_remaining.normalized_time}!"
        )

    # TODO: Add checks for TradeResult's other outputs.
    # issue #57
    def check_output_assertions(
        self,
        trade_result: trades.TradeResult,
    ):
        """Applies a set of assertions to a trade result."""
        assert isinstance(trade_result.breakdown.fee, float), (
            "pricing_models.check_output_assertions: ERROR: "
            f"fee should be a float, not {type(trade_result.breakdown.fee)}!"
        )
        assert trade_result.breakdown.fee >= 0, (
            "pricing_models.check_output_assertions: ERROR: "
            f"Fee should not be negative, but is {trade_result.breakdown.fee}!"
        )
        assert isinstance(trade_result.breakdown.without_fee, float), (
            "pricing_models.check_output_assertions: ERROR: "
            f"without_fee should be a float, not {type(trade_result.breakdown.without_fee)}!"
        )
        assert trade_result.breakdown.without_fee >= 0, (
            "pricing_models.check_output_assertions: ERROR: "
            f"without_fee should be non-negative, not {trade_result.breakdown.without_fee}!"
        )


class PricingModelFP(ABC):
    """Contains functions for calculating AMM variables

    Base class should not be instantiated on its own; it is assumed that a user will instantiate a child class

    .. todo:: Make this an interface
    """

    def calc_in_given_out(
        self,
        out: types.QuantityFP,
        market_state: hyperdrive_market.MarketStateFP,
        time_remaining: time.StretchedTimeFP,
    ) -> trades.TradeResultFP:
        """Calculate fees and asset quantity adjustments"""
        raise NotImplementedError

    def calc_out_given_in(
        self,
        in_: types.QuantityFP,
        market_state: hyperdrive_market.MarketStateFP,
        time_remaining: time.StretchedTimeFP,
    ) -> trades.TradeResultFP:
        """Calculate fees and asset quantity adjustments"""
        raise NotImplementedError

    def calc_lp_out_given_tokens_in(
        self,
        d_base: FixedPoint,
        rate: FixedPoint,
        market_state: hyperdrive_market.MarketStateFP,
        time_remaining: time.StretchedTimeFP,
    ) -> tuple[FixedPoint, FixedPoint, FixedPoint]:
        """Computes the amount of LP tokens to be minted for a given amount of base asset"""
        raise NotImplementedError

    def calc_tokens_out_given_lp_in(
        self,
        lp_in: FixedPoint,
        market_state: hyperdrive_market.MarketStateFP,
    ) -> tuple[FixedPoint, FixedPoint, FixedPoint]:
        """Calculate how many tokens should be returned for a given lp addition"""
        raise NotImplementedError

    def model_name(self) -> str:
        """Unique name given to the model, can be based on member variable states"""
        raise NotImplementedError

    def model_type(self) -> str:
        """Unique identifier given to the model, should be lower snake_cased name"""
        raise NotImplementedError

    def calc_initial_bond_reserves(
        self,
        target_apr: FixedPoint,
        time_remaining: time.StretchedTimeFP,
        market_state: hyperdrive_market.MarketStateFP,
    ) -> FixedPoint:
        """Returns the assumed bond (i.e. token asset) reserve amounts given
        the share (i.e. base asset) reserves and APR for an initialized market

        Parameters
        ----------
        target_apr : FixedPoint
            Target fixed APR in decimal units (for example, 5% APR would be 0.05)
        time_remaining : StretchedTime
            Amount of time left until bond maturity
        market_state : MarketState
            MarketState object; the following attributes are used:
                share_reserves : FixedPoint
                    Base asset reserves in the pool
                init_share_price : FixedPoint
                    Original share price when the pool started
                share_price : FixedPoint
                    Current share price

        Returns
        -------
        FixedPoint
            The expected amount of bonds (token asset) in the pool, given the inputs

        .. todo:: test_market.test_initialize_market uses this, but this should also have a unit test
        """
        # Only want to renormalize time for APR ("annual", so hard coded to 365)
        # Don't want to renormalize stretched time
        annualized_time = time_remaining.days / FixedPoint("365.0")
        # y = z/2 * (mu * (1 + rt)**(1/tau) - c)
        return (market_state.share_reserves / FixedPoint("2.0")) * (
            market_state.init_share_price
            * (FixedPoint("1.0") + target_apr * annualized_time) ** (FixedPoint("1.0") / time_remaining.stretched_time)
            - market_state.share_price
        )

    def calc_bond_reserves(
        self,
        target_apr: FixedPoint,
        time_remaining: time.StretchedTimeFP,
        market_state: hyperdrive_market.MarketStateFP,
    ) -> FixedPoint:
        """Returns the assumed bond (i.e. token asset) reserve amounts given
        the share (i.e. base asset) reserves and APR

        Parameters
        ----------
        target_apr : FixedPoint
            Target fixed APR in decimal units (for example, 5% APR would be 0.05)
        time_remaining : StretchedTime
            Amount of time left until bond maturity
        market_state : MarketState
            MarketState object; the following attributes are used:
                share_reserves : FixedPoint
                    Base asset reserves in the pool
                init_share_price : FixedPoint
                    Original share price when the pool started
                share_price : FixedPoint
                    Current share price

        Returns
        -------
        FixedPoint
            The expected amount of bonds (token asset) in the pool, given the inputs

        .. todo:: Test this function
        """
        # Only want to renormalize time for APR ("annual", so hard coded to 365)
        annualized_time = time_remaining.days / FixedPoint("365.0")
        # (1 + r * t) ** (1 / tau)
        interest_factor = (FixedPoint("1.0") + target_apr * annualized_time) ** (
            FixedPoint("1.0") / time_remaining.stretched_time
        )
        # mu * z * (1 + apr * t) ** (1 / tau) - l
        return (
            market_state.init_share_price * market_state.share_reserves * interest_factor - market_state.lp_total_supply
        )

    def calc_spot_price_from_reserves(
        self,
        market_state: hyperdrive_market.MarketStateFP,
        time_remaining: time.StretchedTimeFP,
    ) -> FixedPoint:
        r"""Calculates the spot price of base in terms of bonds.
        The spot price is defined as:

        .. math::
            \begin{align}
                p &= (\frac{y + s}{\mu z})^{-\tau} \\
                  &= (\frac{\mu z}{y + s})^{\tau}
            \end{align}

        Parameters
        ----------
        market_state: MarketState
            The reserves and prices in the pool.
        time_remaining : StretchedTime
            The time remaining for the asset (uses time stretch).

        Returns
        -------
        FixedPoint
            The spot price of principal tokens.
        """
        # avoid div by zero error
        if market_state.bond_reserves + market_state.lp_total_supply == FixedPoint(0):
            return FixedPoint("nan")
        # p = ((mu * z) / (y + s))^(tau)
        return (
            (market_state.init_share_price * market_state.share_reserves)
            / (market_state.bond_reserves + market_state.lp_total_supply)
        ) ** time_remaining.stretched_time

    def calc_apr_from_reserves(
        self,
        market_state: hyperdrive_market.MarketStateFP,
        time_remaining: time.StretchedTimeFP,
    ) -> FixedPoint:
        r"""Returns the apr given reserve amounts

        Parameters
        ----------
        market_state : MarketState
            The reserves and share prices of the pool
        time_remaining : StretchedTime
            The expiry time for the asset
        """
        spot_price = self.calc_spot_price_from_reserves(
            market_state,
            time_remaining,
        )
        return price_utils.calc_apr_from_spot_price_fp(spot_price, time_remaining)

    def get_max_long(
        self,
        market_state: hyperdrive_market.MarketStateFP,
        time_remaining: time.StretchedTimeFP,
    ) -> tuple[FixedPoint, FixedPoint]:
        r"""
        Calculates the maximum long the market can support

        .. math::
            \Delta z' = \mu^{-1} \cdot (\frac{\mu}{c} \cdot (k-(y+c \cdot z)^{1-\tau(d)}))^{\frac{1}{1-\tau(d)}}
            -c \cdot z

        Parameters
        ----------
        market_state : MarketState
            The reserves and share prices of the pool
        time_remaining : StretchedTime
            The time remaining for the asset (incorporates time stretch)

        Returns
        -------
        FixedPoint
            The maximum amount of base that can be used to purchase bonds.
        FixedPoint
            The maximum amount of bonds that can be purchased.
        """
        base = self.calc_in_given_out(
            out=types.QuantityFP(market_state.bond_reserves - market_state.bond_buffer, unit=types.TokenType.PT),
            market_state=market_state,
            time_remaining=time_remaining,
        ).breakdown.with_fee
        bonds = self.calc_out_given_in(
            in_=types.QuantityFP(amount=base, unit=types.TokenType.BASE),
            market_state=market_state,
            time_remaining=time_remaining,
        ).breakdown.with_fee
        return base, bonds

    def get_max_short(
        self,
        market_state: hyperdrive_market.MarketStateFP,
        time_remaining: time.StretchedTimeFP,
    ) -> tuple[FixedPoint, FixedPoint]:
        r"""
        Calculates the maximum short the market can support using the bisection
        method.

        .. math::
            \Delta y' = \mu^{-1} \cdot (\frac{\mu}{c} \cdot k)^{\frac{1}{1-\tau(d)}}-2y-c \cdot z

        Parameters
        ----------
        market_state : MarketState
            The reserves and share prices of the pool.
        time_remaining : StretchedTime
            The time remaining for the asset (incorporates time stretch).

        Returns
        -------
        FixedPoint
            The maximum amount of base that can be used to short bonds.
        FixedPoint
            The maximum amount of bonds that can be shorted.
        """
        bonds = self.calc_in_given_out(
            out=types.QuantityFP(
                market_state.share_reserves - market_state.base_buffer / market_state.share_price,
                unit=types.TokenType.PT,
            ),
            market_state=market_state,
            time_remaining=time_remaining,
        ).breakdown.with_fee
        base = self.calc_out_given_in(
            in_=types.QuantityFP(amount=bonds, unit=types.TokenType.PT),
            market_state=market_state,
            time_remaining=time_remaining,
        ).breakdown.with_fee
        return base, bonds

    def calc_time_stretch(self, apr: FixedPoint) -> FixedPoint:
        """Returns fixed time-stretch value based on current apr (as a FixedPoint)"""
        apr_percent = apr * FixedPoint("100.0")  # bounded between 0 and 100
        return FixedPoint("3.09396") / (
            FixedPoint("0.02789") * apr_percent
        )  # bounded between ~1.109 (apr=1) and inf (apr=0)

    def check_input_assertions(
        self,
        quantity: types.QuantityFP,
        market_state: hyperdrive_market.MarketStateFP,
        time_remaining: time.StretchedTimeFP,
    ):
        """Applies a set of assertions to the input of a trading function."""
        assert quantity.amount >= elfpy.WEI_FP, (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected quantity.amount >= {elfpy.WEI_FP}, not {quantity.amount}!"
        )
        assert market_state.share_reserves >= FixedPoint("0.0"), (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected share_reserves >= 0, not {market_state.share_reserves}!"
        )
        assert market_state.bond_reserves >= FixedPoint("0.0"), (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected bond_reserves >= 0"
            f" bond_reserves == 0, not {market_state.bond_reserves}!"
        )
        if market_state.share_price < market_state.init_share_price:
            logging.warning(
                "WARNING: expected share_price >= %g, not share_price=%g",
                market_state.init_share_price,
                market_state.share_price,
            )
        assert market_state.init_share_price >= FixedPoint("1.0"), (
            f"pricing_models.check_input_assertions: ERROR: "
            f"expected init_share_price >= 1, not share_price={market_state.init_share_price}"
        )
        reserves_difference = abs(market_state.share_reserves * market_state.share_price - market_state.bond_reserves)
        assert reserves_difference < elfpy.MAX_RESERVES_DIFFERENCE_FP, (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected reserves_difference < {elfpy.MAX_RESERVES_DIFFERENCE_FP}, not {reserves_difference}!"
        )
        assert FixedPoint("1.0") >= market_state.curve_fee_multiple >= FixedPoint("0.0"), (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected 1 >= curve_fee_multiple >= 0, not {market_state.curve_fee_multiple}!"
        )
        assert FixedPoint("1.0") >= market_state.flat_fee_multiple >= FixedPoint("0.0"), (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected 1 >= flat_fee_multiple >= 0, not {market_state.flat_fee_multiple}!"
        )
        assert (
            FixedPoint("1.0") + elfpy.PRECISION_THRESHOLD_FP
            >= time_remaining.stretched_time
            >= -elfpy.PRECISION_THRESHOLD_FP
        ), (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected {1 + int(elfpy.PRECISION_THRESHOLD_FP)} > "
            f"time_remaining.stretched_time >= {-int(elfpy.PRECISION_THRESHOLD_FP)}"
            f", not {time_remaining.stretched_time}!"
        )
        assert (
            FixedPoint("1.0") + elfpy.PRECISION_THRESHOLD_FP
            >= time_remaining.normalized_time
            >= -elfpy.PRECISION_THRESHOLD_FP
        ), (
            "pricing_models.check_input_assertions: ERROR: "
            f"expected {1 + int(elfpy.PRECISION_THRESHOLD_FP)} > time_remaining >= {-int(elfpy.PRECISION_THRESHOLD_FP)}"
            f", not {time_remaining.normalized_time}!"
        )

    # TODO: Add checks for TradeResult's other outputs.
    # issue #57
    def check_output_assertions(
        self,
        trade_result: trades.TradeResultFP,
    ):
        """Applies a set of assertions to a trade result."""
        assert isinstance(trade_result.breakdown.fee, FixedPoint), (
            "pricing_models.check_output_assertions: ERROR: "
            f"fee should be a FixedPoint, not {type(trade_result.breakdown.fee)}!"
        )
        assert trade_result.breakdown.fee >= FixedPoint("0.0"), (
            "pricing_models.check_output_assertions: ERROR: "
            f"Fee should not be negative, but is {trade_result.breakdown.fee}!"
        )
        assert isinstance(trade_result.breakdown.without_fee, FixedPoint), (
            "pricing_models.check_output_assertions: ERROR: "
            f"without_fee should be a FixedPoint, not {type(trade_result.breakdown.without_fee)}!"
        )
        assert trade_result.breakdown.without_fee >= FixedPoint("0.0"), (
            "pricing_models.check_output_assertions: ERROR: "
            f"without_fee should be non-negative, not {trade_result.breakdown.without_fee}!"
        )
