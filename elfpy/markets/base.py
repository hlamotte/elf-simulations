"""Market simulators store state information when interfacing AMM pricing models with users."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Generic, TypeVar

import numpy as np

import elfpy
import elfpy.types as types
from elfpy.utils.math import FixedPoint

if TYPE_CHECKING:
    import elfpy.agents.wallet as wallet
    import elfpy.pricing_models.base as base_pm
    import elfpy.time as time

# all 1subclasses of Market need to pass subclasses of MarketAction, MarketState and MarketDeltas
Action = TypeVar("Action", bound="MarketAction")
Deltas = TypeVar("Deltas", bound="MarketDeltas")
State = TypeVar("State", bound="BaseMarketState")
PricingModel = TypeVar("PricingModel", bound="base_pm.PricingModel")


class MarketActionType(Enum):
    r"""
    The descriptor of an action in a market
    """
    NULL_ACTION = "null action"


@types.freezable(frozen=False, no_new_attribs=True)
@dataclass
class MarketAction(Generic[Action]):
    r"""Market action specification"""

    action_type: Enum  # these two variables are required to be set by the strategy
    wallet: wallet.Wallet  # the agent's wallet


@types.freezable(frozen=True, no_new_attribs=True)
@dataclass
class MarketDeltas:
    r"""Specifies changes to values in the market"""


@types.freezable(frozen=True, no_new_attribs=True)
@dataclass
class MarketActionResult:
    r"""The result to a market of performing a trade"""


@types.freezable(frozen=False, no_new_attribs=False)
@dataclass
class BaseMarketState:
    r"""The state of an AMM

    Implements a class for all that an AMM smart contract would hold or would have access to
    For example, reserve numbers are local state variables of the AMM.
    """

    # TODO: have this be generic enough that any subclass can apply deltas?
    def apply_delta(self, delta: MarketDeltas) -> None:
        r"""Applies a delta to the market state."""
        raise NotImplementedError

    # TODO: have this be generic enough that any subclass can copy?
    def copy(self) -> BaseMarketState:
        """Returns a new copy of self"""
        raise NotImplementedError


class Market(Generic[State, Deltas, PricingModel]):
    r"""Market state simulator

    Holds state variables for market simulation and executes trades.
    The Market class executes trades by updating market variables according to the given pricing model.
    It also has some helper variables for assessing pricing model values given market conditions.
    """

    def __init__(
        self,
        pricing_model: PricingModel,
        market_state: State,
        block_time: time.BlockTime,
    ):
        self.pricing_model = pricing_model
        self.market_state = market_state
        self.block_time = block_time

    @property
    def latest_checkpoint_time(self) -> float:
        """Gets the most recent checkpoint time."""
        raise NotImplementedError

    def perform_action(self, action_details: tuple[int, Enum]) -> tuple[int, wallet.Wallet, Deltas]:
        """Performs an action in the market without updating it."""
        raise NotImplementedError

    def check_market_updates(self, market_deltas: Deltas) -> None:
        """Check market update values to make sure they are valid"""
        for key, value in market_deltas.__dict__.items():
            if value:  # check that it's instantiated and non-empty
                value_to_check: Any = value.amount if isinstance(value, types.Quantity) else value
                assert np.isfinite(value_to_check), f"ERROR: market delta key {key} is not finite."

    def update_market(self, market_deltas: Deltas) -> None:
        """Increments member variables to reflect current market conditions"""
        self.check_market_updates(market_deltas)  # check that market deltas are valid
        self.market_state.apply_delta(market_deltas)
        elfpy.check_non_zero(self.market_state)  # check reserves are non-zero within precision threshold


# all 1subclasses of Market need to pass subclasses of MarketAction, MarketState and MarketDeltas
# TODO: Pylint disables will go away when we finalize FP refactor
ActionFP = TypeVar("ActionFP", bound="MarketActionFP")  # pylint: disable=invalid-name
DeltasFP = TypeVar("DeltasFP", bound="MarketDeltasFP")  # pylint: disable=invalid-name
StateFP = TypeVar("StateFP", bound="BaseMarketStateFP")  # pylint: disable=invalid-name
PricingModelFP = TypeVar("PricingModelFP", bound="base_pm.PricingModelFP")  # pylint: disable=invalid-name


@types.freezable(frozen=False, no_new_attribs=True)
@dataclass
class MarketActionFP(Generic[ActionFP]):
    r"""Market action specification"""

    action_type: Enum  # these two variables are required to be set by the strategy
    wallet: wallet.WalletFP  # the agent's wallet


@types.freezable(frozen=True, no_new_attribs=True)
@dataclass
class MarketDeltasFP:
    r"""Specifies changes to values in the market"""


@types.freezable(frozen=True, no_new_attribs=True)
@dataclass
class MarketActionResultFP:
    r"""The result to a market of performing a trade"""


@types.freezable(frozen=False, no_new_attribs=False)
@dataclass
class BaseMarketStateFP:
    r"""The state of an AMM

    Implements a class for all that that an AMM smart contract would hold or would have access to.
    For example, reserve numbers are local state variables of the AMM.
    """

    # TODO: have this be generic enough that any subclass can apply deltas?
    def apply_delta(self, delta: MarketDeltasFP) -> None:
        r"""Applies a delta to the market state."""
        raise NotImplementedError

    # TODO: have this be generic enough that any subclass can copy?
    def copy(self) -> BaseMarketStateFP:
        """Returns a new copy of self"""
        raise NotImplementedError


class MarketFP(Generic[StateFP, DeltasFP, PricingModelFP]):
    r"""Market state simulator

    Holds state variables for market simulation and executes trades.
    The Market class executes trades by updating market variables according to the given pricing model.
    It also has some helper variables for assessing pricing model values given market conditions.
    """

    def __init__(
        self,
        pricing_model: PricingModelFP,
        market_state: StateFP,
        block_time: time.BlockTimeFP,
    ):
        self.pricing_model = pricing_model
        self.market_state = market_state
        self.block_time = block_time

    @property
    def latest_checkpoint_time(self) -> FixedPoint:
        """Gets the most recent checkpoint time."""
        raise NotImplementedError

    def perform_action(self, action_details: tuple[int, Enum]) -> tuple[int, wallet.WalletFP, DeltasFP]:
        """Performs an action in the market without updating it."""
        raise NotImplementedError

    def update_market(self, market_deltas: DeltasFP) -> None:
        """Increments member variables to reflect current market conditions."""
        self.market_state.apply_delta(market_deltas)
        elfpy.check_non_zero_fp(self.market_state)  # check reserves are non-zero within precision threshold
