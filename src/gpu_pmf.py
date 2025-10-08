from __future__ import annotations
import os, torch
from typing import Optional, Tuple

def _device():
    use = os.environ.get("USE_GPU", "0") == "1"
    return torch.device("cuda") if (use and torch.cuda.is_available()) else torch.device("cpu")

def _rank_vals(device):
    # idx: 0=A(11), 1..8 -> 2..9, 9..12 -> 10
    return torch.tensor([11,2,3,4,5,6,7,8,9,10,10,10,10], dtype=torch.int32, device=device)

@torch.no_grad()
def dealer_pmf_single(counts_key: Tuple[int,...],
                      up_idx: int,
                      hit_s17: bool,
                      hole_constraint: Optional[str]) -> Tuple[float,float,float,float,float,float]:
    """
    Dealer PMF over (bust,17,18,19,20,21) for a single state on GPU.
    counts_key: tuple of 13 remaining-card counts.
    """
    device = _device()
    vals = _rank_vals(device)
    counts = torch.tensor(counts_key, dtype=torch.int32, device=device)

    # Allowed holes per peek constraint
    allowed = counts.clone().to(torch.float32)
    if hole_constraint == "not_ten":
        allowed[9:13] = 0
    elif hole_constraint == "not_ace":
        allowed[0] = 0

    total_allowed = allowed.sum().item()
    if total_allowed <= 0:
        # Stand on upcard only (degenerate)
        total0 = int(vals[up_idx].item())
        soft0  = (up_idx == 0)
        return _pmf_from_total(counts, total0, soft0, vals, hit_s17)

    pmf_sum = torch.zeros(6, dtype=torch.float64, device=device)
    for r in range(13):
        w = allowed[r].item()
        if w <= 0: 
            continue
        p_hole = w / total_allowed
        # Remove one hole
        counts[r] -= 1
        total0 = int(vals[up_idx].item() + vals[r].item())
        soft0  = (up_idx == 0) or (r == 0)
        pmf = _pmf_from_total(counts, total0, soft0, vals, hit_s17)  # (6,)
        pmf_sum += p_hole * pmf
        counts[r] += 1

    return tuple(float(x) for x in pmf_sum.tolist())

def _pmf_from_total(counts: torch.Tensor,
                    total0: int,
                    soft0: bool,
                    vals: torch.Tensor,
                    hit_s17: bool) -> torch.Tensor:
    """
    Iterative expansion of dealer draw-to-17+; returns tensor (6,) = (bust,17..21).
    """
    counts_f = counts.to(torch.float32)
    pmf = torch.zeros(6, dtype=torch.float32, device=counts.device)
    frontier = [(1.0, total0, soft0)]

    while frontier:
        prob, total, soft = frontier.pop()
        if total > 21:
            pmf[0] += prob; continue
        stand = (total >= 17) and not (hit_s17 and (total == 17 and soft))
        if stand:
            if 17 <= total <= 21:
                pmf[total - 16 - 1] += prob  # 17->idx1 ... 21->idx5
            else:
                pmf[0] += prob
            continue

        total_cards = counts_f.sum().item()
        if total_cards <= 0:
            if 17 <= total <= 21:
                pmf[total - 16 - 1] += prob
            else:
                pmf[0] += prob
            continue

        for r in range(13):
            c = counts_f[r].item()
            if c <= 0: 
                continue
            p = prob * (c / total_cards)
            v = int(vals[r].item())
            new_total = total + v
            new_soft = soft or (r == 0)
            if new_total > 21 and new_soft:
                new_total -= 10
                new_soft = False
            counts_f[r] -= 1.0
            frontier.append((p, new_total, new_soft))
            counts_f[r] += 1.0

    return pmf.to(torch.float64)
