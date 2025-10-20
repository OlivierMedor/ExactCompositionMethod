from src.exact.deck import Deck, HC_NONE, HC_NOT_TEN, HC_NOT_ACE
from src.exact.dealer_pmf import dealer_pmf
from src.exact.ev import stand_ev, hit_then_stand_ev

# one deck fresh
fresh: Deck = (4,4,4,4,4,4,4,4,4,16)

def test_dealer_pmf_basic():
    pmf = dealer_pmf(6, False, fresh, True, HC_NONE)   # start_total=6 soft?=False, H17
    assert abs(sum(pmf.values()) - 1.0) < 1e-12

def test_peek_constraints():
    # A-up, no BJ => hole cannot be Ten
    pmf_a = dealer_pmf(11, True, fresh, True, HC_NOT_TEN)
    # T-up, no BJ => hole cannot be Ace
    pmf_t = dealer_pmf(10, False, fresh, True, HC_NOT_ACE)
    assert abs(sum(pmf_a.values()) - 1.0) < 1e-12
    assert abs(sum(pmf_t.values()) - 1.0) < 1e-12

def test_stand_vs_hit_once():
    # Player 16 vs 10
    ev_stand = stand_ev(16, False, 9, fresh, True, HC_NONE)
    ev_hit0  = hit_then_stand_ev(16, False, 9, fresh, True, HC_NONE)
    assert ev_stand < ev_hit0  # usually better to hit 16v10
