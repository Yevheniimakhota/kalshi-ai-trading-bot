from enum import Enum


class Strategy(str, Enum):
    AI_DIRECTIONAL = "AI Directional"
    SAFE_COMPOUNDER = "Safe Compounder"
    BEAST_MODE = "Beast Mode"


class TradingMode(str, Enum):
    PAPER = "Paper"
    LIVE = "Live"


def build_run_arguments(strategy: Strategy, mode: TradingMode,) -> list[str]:
    args = ["run"]

    if strategy == Strategy.SAFE_COMPOUNDER:
        args.append("--safe-compounder")

    elif strategy == Strategy.BEAST_MODE:
        args.append("--beast")

    if mode == TradingMode.LIVE:
        args.append("--live")

    return args


def format_command(arguments: list[str]) -> str:
    """Human-readable representation for GUI logs."""

    return "python cli.py " + " ".join(arguments)



if __name__ == "__main__":
    combinations = [
        (Strategy.AI_ENSEMBLE, TradingMode.PAPER),
        (Strategy.AI_ENSEMBLE, TradingMode.LIVE),
        (Strategy.SAFE_COMPOUNDER, TradingMode.PAPER),
        (Strategy.SAFE_COMPOUNDER, TradingMode.LIVE),
        (Strategy.BEAST_MODE, TradingMode.PAPER),
    ]

    for strategy, mode in combinations:
        args = build_run_arguments(strategy, mode)

        print(
            strategy.value,
            "/",
            mode.value,
            "->",
            format_command(args),
        )