from desktop.command_builder import (
    Strategy,
    TradingMode,
    build_run_arguments,
)


def test_ai_ensemble_paper():
    assert build_run_arguments(
        Strategy.AI_ENSEMBLE,
        TradingMode.PAPER,
    ) == [
        "run",
    ]


def test_ai_ensemble_live():
    assert build_run_arguments(
        Strategy.AI_ENSEMBLE,
        TradingMode.LIVE,
    ) == [
        "run",
        "--live",
    ]


def test_safe_compounder_paper():
    assert build_run_arguments(
        Strategy.SAFE_COMPOUNDER,
        TradingMode.PAPER,
    ) == [
        "run",
        "--safe-compounder",
    ]


def test_safe_compounder_live():
    assert build_run_arguments(
        Strategy.SAFE_COMPOUNDER,
        TradingMode.LIVE,
    ) == [
        "run",
        "--safe-compounder",
        "--live",
    ]


def test_beast_mode_paper():
    assert build_run_arguments(
        Strategy.BEAST_MODE,
        TradingMode.PAPER,
    ) == [
        "run",
        "--beast",
    ]

def test_beast_mode_live():
    assert build_run_arguments(
        Strategy.BEAST_MODE,
        TradingMode.LIVE,
    ) == [
        "run",
        "--beast",
        "--live",
    ]