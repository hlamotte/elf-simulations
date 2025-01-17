"""Example main.py file for illustrating a simulator workflow"""
from __future__ import annotations  # types will be strings by default in 3.11

# stdlib
import argparse
from typing import TYPE_CHECKING, Any

# external
from stochastic.processes import GeometricBrownianMotion

# elfpy core repo
import elfpy
import elfpy.markets.hyperdrive.hyperdrive_actions as hyperdrive_actions
import elfpy.simulators as simulators
import elfpy.utils.outputs as output_utils
import elfpy.utils.sim_utils as sim_utils
import elfpy.agents.agent as agent
import elfpy.types as types

if TYPE_CHECKING:
    import elfpy.markets.hyperdrive.hyperdrive_market as hyperdrive_market


class CustomShorter(agent.Agent):
    """
    Agent that is trying to optimize on a rising vault APR via shorts
    """

    def __init__(self, wallet_address: int, budget: int = 10_000) -> None:
        """Add custom stuff then call basic policy init"""
        self.pt_to_short = 1_000
        super().__init__(wallet_address, budget)

    def action(self, market: hyperdrive_market.Market) -> "list[Any]":
        """Implement a custom user strategy"""
        shorts = list(self.wallet.shorts.values())
        has_opened_short = bool(any((short.balance > 0 for short in shorts)))
        can_open_short = self.get_max_short(market) >= self.pt_to_short
        vault_apr = market.market_state.variable_apr
        action_list = []
        if can_open_short:
            if vault_apr > market.fixed_apr:
                action_list.append(
                    types.Trade(
                        market=types.MarketType.HYPERDRIVE,
                        trade=hyperdrive_actions.MarketAction(
                            action_type=hyperdrive_actions.MarketActionType.OPEN_SHORT,
                            trade_amount=self.pt_to_short,
                            wallet=self.wallet,
                        ),
                    )
                )
            elif vault_apr < market.fixed_apr:
                if has_opened_short:
                    action_list.append(
                        types.Trade(
                            market=types.MarketType.HYPERDRIVE,
                            trade=hyperdrive_actions.MarketAction(
                                action_type=hyperdrive_actions.MarketActionType.CLOSE_SHORT,
                                trade_amount=self.pt_to_short,
                                wallet=self.wallet,
                                mint_time=list(self.wallet.shorts.keys())[0],
                            ),
                        )
                    )
        return action_list


def get_example_agents(new_agents: int, existing_agents: int = 0) -> list[agent.Agent]:
    """Instantiate a set of custom agents"""
    agents = []
    for address in range(existing_agents, existing_agents + new_agents):
        example_agent = CustomShorter(address)
        example_agent.log_status_report()
        agents += [example_agent]
    return agents


def get_argparser() -> argparse.ArgumentParser:
    """Define & parse arguments from stdin"""
    parser = argparse.ArgumentParser(
        prog="ElfMain",
        description="Example execution script for running simulations using Elfpy",
        epilog="See the README on https://github.com/delvtech/elf-simulations/ for more implementation details",
    )
    parser.add_argument(
        "--log_filename", help="Optional output filename for logging", default="../.logging/example_main.log", type=str
    )
    parser.add_argument(
        "--max_bytes",
        help=f"Maximum log file output size, in bytes. Default is {elfpy.DEFAULT_LOG_MAXBYTES} bytes."
        "More than 100 files will cause overwrites.",
        default=elfpy.DEFAULT_LOG_MAXBYTES,
        type=int,
    )
    parser.add_argument(
        "--log_level",
        help='Logging level, should be in ["DEBUG", "INFO", "WARNING"]. Default uses the config.',
        default="DEBUG",
        type=str,
    )
    parser.add_argument(
        "--num_agents", help="Integer specifying how many agents you want to simulate.", default=1, type=int
    )
    parser.add_argument(
        "--pricing_model", help="Pricing model to be used in the simulation", default="Hyperdrive", type=str
    )
    parser.add_argument("--num_trading_days", help="Number of simulated trading days", default=5, type=int)
    parser.add_argument("--num_blocks_per_day", help="Number of simulated trading blocks per day", default=5, type=int)
    parser.add_argument(
        "--vault_apr_type",
        help="Distribution type for the vault apr; must be 'uniform' or 'brownian'.",
        default="uniform",
        type=str,
    )
    return parser


if __name__ == "__main__":
    # Instantiate the config using the command line arguments as overrides.
    args = get_argparser().parse_args()
    config = simulators.Config()
    config.num_trading_days = args.num_trading_days
    config.num_blocks_per_day = args.num_blocks_per_day
    config.pricing_model_name = args.pricing_model
    if args.vault_apr_type == "brownian":
        config.variable_apr = (
            GeometricBrownianMotion(rng=config.rng).sample(n=config.num_trading_days - 1, initial=0.05)  # type: ignore
        ).tolist()
    elif args.vault_apr_type == "uniform":
        config.variable_apr = config.rng.uniform(low=0.001, high=0.9, size=config.num_trading_days).tolist()
    else:
        assert False, f"vault_apr_type argument must be 'uniform' or 'brownian', not {args.vault_apr_type}"
    config.log_level = output_utils.text_to_log_level(args.log_level)
    config.log_filename = args.log_filename
    # NOTE: lint error false positives: This message may report object members that are created dynamically,
    # but exist at the time they are accessed.
    config.freeze()  # type: ignore

    # Define root logging parameters.
    output_utils.setup_logging(log_filename=config.log_filename, max_bytes=args.max_bytes, log_level=config.log_level)

    # Initialize the simulator.
    simulator = sim_utils.get_simulator(config, get_example_agents(new_agents=args.num_agents, existing_agents=1))

    # Run the simulation.
    simulator.run_simulation()
