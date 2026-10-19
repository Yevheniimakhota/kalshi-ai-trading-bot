from src.utils.stop_loss_calculator import StopLossCalculator as C

def test_owned_no_contract_profit_and_loss():
    levels = C.calculate_stop_loss_levels(0.50, "NO", confidence=0.7)
    assert levels["stop_loss_price"] < 0.50 < levels["take_profit_price"]
    assert C.is_stop_loss_triggered("NO", 0.50, 0.40, levels["stop_loss_price"])
    assert not C.is_stop_loss_triggered("NO", 0.50, 0.60, levels["stop_loss_price"])
    assert C.calculate_pnl_at_stop_loss(0.50, 0.40, 5, "NO") == -0.5

def test_yes_contract_same_direction():
    levels = C.calculate_stop_loss_levels(0.50, "YES", confidence=0.7)
    assert levels["stop_loss_price"] < 0.50 < levels["take_profit_price"]
