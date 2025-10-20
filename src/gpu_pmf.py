# src/gpu_pmf.py
from typing import Tuple, Dict, List
import torch

def _rank_val(idx: int) -> int:
    # 0..9 => A,2,3,4,5,6,7,8,9,T
    if idx == 0:
        return 11
    elif 1 <= idx <= 8:
        return idx + 1
    else:
        return 10

def _add_rank(total: int, soft: bool, r_idx: int) -> Tuple[int, bool]:
    t = total + _rank_val(r_idx)
    s = soft or (r_idx == 0)
    if t > 21 and s:
        t -= 10
        s = False
    return t, s

def dealer_pmf_single(
    counts_key: Tuple[int, ...],
    up_idx: int,
    hit_s17: bool,
    hole_constraint: int = 0,  # 0=None, 1=NOT_TEN, 2=NOT_ACE
    max_nodes: int = 2_000_000,
    device: torch.device | None = None,
) -> Dict[int, float]:
    """
    Compute dealer PMF given post-deal deck, dealer upcard, and peek constraint.
    Peek mask is applied to the FIRST dealer draw only (hole card).
    Returns a dict: {17..21: p, 22: p_bust}.
    """
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    base_counts = torch.tensor(list(counts_key), dtype=torch.int32, device=device)

    start_total = _rank_val(up_idx)
    start_soft = (up_idx == 0)

    # frontier: (prob, total, soft, counts_tensor, mask_left_bool)
    mask_left = (hole_constraint != 0)
    frontier: List[Tuple[float, int, bool, torch.Tensor, bool]] = [
        (1.0, start_total, start_soft, base_counts, mask_left)
    ]

    pmf: Dict[int, float] = {}

    while frontier:
        prob, total, soft, counts, mask_left = frontier.pop()

        # Standing rules
        if total >= 17:
            if total > 21:
                pmf[22] = pmf.get(22, 0.0) + prob
                continue
            if not (hit_s17 and soft and total == 17):
                pmf[total] = pmf.get(total, 0.0) + prob
                continue

        # View for probabilities (apply peek mask only once, to the hole draw)
        avail = counts.clone()
        if mask_left:
            if hole_constraint == 1:   # NOT_TEN
                avail[9] = 0
            elif hole_constraint == 2: # NOT_ACE
                avail[0] = 0

        total_cards = int(avail.sum().item())
        if total_cards == 0:
            if total > 21:
                pmf[22] = pmf.get(22, 0.0) + prob
            else:
                pmf[total] = pmf.get(total, 0.0) + prob
            continue

        for r in range(10):
            c = int(avail[r].item())
            if c == 0:
                continue
            p = prob * (c / total_cards)

            counts_f = counts.clone()
            counts_f[r] -= 1

            nt, ns = _add_rank(total, soft, r)

            # After the *first* dealer draw, clear the peek mask
            child_mask_left = False if mask_left else False

            if len(frontier) < max_nodes:
                frontier.append((p, nt, ns, counts_f, child_mask_left))
            else:
                # Rare safety valve
                if nt > 21:
                    pmf[22] = pmf.get(22, 0.0) + p
                elif not (hit_s17 and ns and nt == 17) and nt >= 17:
                    pmf[nt] = pmf.get(nt, 0.0) + p
                else:
                    bucket = max(17, min(21, nt))
                    pmf[bucket] = pmf.get(bucket, 0.0) + p

    s = sum(pmf.values())
    if s > 0:
        for k in list(pmf.keys()):
            pmf[k] /= s
    return pmf
