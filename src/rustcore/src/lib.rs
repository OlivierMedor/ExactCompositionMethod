use pyo3::prelude::*;
use std::collections::HashMap;

// ---------- Rank helpers ----------
type Count = i32;

#[inline]
fn rank_val(i: usize) -> i32 {
    match i {
        0 => 11,              // Ace
        1..=8 => (i as i32) + 1, // 2..9
        _ => 10,              // Ten bucket
    }
}

#[inline]
fn add_to(total: i32, soft: bool, r: usize) -> (i32, bool) {
    let mut t = total + rank_val(r);
    let mut s = soft || r == 0;
    if t > 21 && s {
        t -= 10;
        s = false;
    }
    (t, s)
}

// ---------- Hole constraints ----------
const HC_NONE: i32 = 0;
const HC_NOT_TEN: i32 = 1;
const HC_NOT_ACE: i32 = 2;

#[inline]
fn hole_allowed(hc: i32, idx: usize) -> bool {
    match hc {
        HC_NOT_TEN => idx != 9,
        HC_NOT_ACE => idx != 0,
        _ => true,
    }
}

// ---------- Dealer runout (exact, memoized) ----------
#[derive(Hash, PartialEq, Eq)]
struct DealerKey {
    counts: [i16; 10],
    total: i16,
    soft: u8,
    h17: u8,
}

fn encode_counts(counts: &[Count; 10]) -> [i16; 10] {
    let mut out = [0i16; 10];
    for (i, c) in counts.iter().enumerate() {
        out[i] = *c as i16;
    }
    out
}

fn dealer_dist_from_total(
    counts: &mut [Count; 10],
    total: i32,
    soft: bool,
    h17: bool,
    memo: &mut HashMap<DealerKey, [f64; 6]>, // bins: 17,18,19,20,21,22(bust)
) -> [f64; 6] {
    if total > 21 {
        let mut v = [0.0; 6];
        v[5] = 1.0;
        return v;
    }
    if total > 17 {
        let mut v = [0.0; 6];
        v[(total - 17) as usize] = 1.0;
        return v;
    }
    if total == 17 {
        if soft && h17 {
            // must hit
        } else {
            let mut v = [0.0; 6];
            v[0] = 1.0;
            return v;
        }
    }

    let key = DealerKey {
        counts: encode_counts(counts),
        total: total as i16,
        soft: soft as u8,
        h17: h17 as u8,
    };
    if let Some(v) = memo.get(&key) {
        return *v;
    }

    let rem: i32 = counts.iter().sum();
    if rem <= 0 {
        let mut v = [0.0; 6];
        let t = total.clamp(17, 22);
        if t <= 21 {
            v[(t - 17) as usize] = 1.0;
        } else {
            v[5] = 1.0;
        }
        memo.insert(key, v);
        return v;
    }

    let mut out = [0.0; 6];
    for r in 0..10 {
        let c = counts[r];
        if c <= 0 {
            continue;
        }
        let p = (c as f64) / (rem as f64);
        counts[r] -= 1;
        let (nt, ns) = add_to(total, soft, r);
        let sub = dealer_dist_from_total(counts, nt, ns, h17, memo);
        for i in 0..6 {
            out[i] += p * sub[i];
        }
        counts[r] += 1;
    }
    memo.insert(key, out);
    out
}

#[inline]
fn dealer_dist_with_two(
    counts: &mut [Count; 10],
    up: usize,
    hole: usize,
    h17: bool,
    memo: &mut HashMap<DealerKey, [f64; 6]>,
) -> [f64; 6] {
    let (t, s) = add_to(rank_val(up), false, hole);
    dealer_dist_from_total(counts, t, s, h17, memo)
}

#[inline]
fn settle_vs_player(pt: i32, dealer_bin: usize) -> f64 {
    if pt > 21 {
        return -1.0;
    }
    if dealer_bin == 5 {
        return 1.0;
    }
    let d = 17 + (dealer_bin as i32);
    if pt > d {
        1.0
    } else if pt < d {
        -1.0
    } else {
        0.0
    }
}

// ---------- PyO3 class ----------
#[pyclass]
pub struct BlackjackSimulator {
    h17: bool,
    dp_depth: usize,
    dp_depth_dbl: usize,
}

#[pymethods]
impl BlackjackSimulator {
    #[new]
    fn new(_shoe_counts: Vec<Count>, h17: bool, dp_depth: Option<usize>, dp_depth_dbl: Option<usize>) -> PyResult<Self> {
        Ok(Self {
            h17,
            dp_depth: dp_depth.unwrap_or(3),
            dp_depth_dbl: dp_depth_dbl.unwrap_or(4),
        })
    }

    /// Stand EV (per-stake), conditional on US peek via hole_constraint.
    fn stand_ev(
        &self,
        pt_total: i32,
        pt_soft: bool,
        up: usize,
        deck: Vec<Count>,
        hole_constraint: i32,
        _depth: Option<usize>,
    ) -> PyResult<f64> {
        let mut arr = [0i32; 10];
        for i in 0..10 {
            arr[i] = *deck.get(i).unwrap_or(&0);
        }
        let rem: i32 = arr.iter().sum();
        if rem <= 0 {
            return Ok(0.0);
        }
        let mut memo = HashMap::new();
        let mut acc = 0.0;
        let mut denom = 0.0;
        for h in 0..10 {
            let c = arr[h];
            if c <= 0 {
                continue;
            }
            if !hole_allowed(hole_constraint, h) {
                continue;
            }
            let p = (c as f64) / (rem as f64);
            arr[h] -= 1;
            let mut cpy = arr;
            let dist = dealer_dist_with_two(&mut cpy, up, h, self.h17, &mut memo);
            let mut ev = 0.0;
            for i in 0..6 {
                ev += settle_vs_player(pt_total, i) * dist[i];
            }
            acc += p * ev;
            denom += p;
            arr[h] += 1;
        }
        Ok(if denom > 0.0 { acc / denom } else { 0.0 })
    }

    /// One-card hit then stand (per-stake), conditional on US peek.
    fn hit_then_stand_ev(
        &self,
        pt_total: i32,
        pt_soft: bool,
        up: usize,
        deck: Vec<Count>,
        hole_constraint: i32,
        _depth: Option<usize>,
    ) -> PyResult<f64> {
        let mut arr = [0i32; 10];
        for i in 0..10 {
            arr[i] = *deck.get(i).unwrap_or(&0);
        }
        let rem0: i32 = arr.iter().sum();
        if rem0 <= 0 {
            return Ok(0.0);
        }
        let mut total_acc = 0.0;
        for r in 0..10 {
            let c = arr[r];
            if c <= 0 {
                continue;
            }
            let p_r = (c as f64) / (rem0 as f64);
            arr[r] -= 1;
            let (t2, s2) = add_to(pt_total, pt_soft, r);

            let rem1: i32 = arr.iter().sum();
            if rem1 <= 0 {
                total_acc += p_r * 0.0;
            } else {
                let mut memo = HashMap::new();
                let mut acc = 0.0;
                let mut denom = 0.0;
                for h in 0..10 {
                    let ch = arr[h];
                    if ch <= 0 {
                        continue;
                    }
                    if !hole_allowed(hole_constraint, h) {
                        continue;
                    }
                    let p_h = (ch as f64) / (rem1 as f64);
                    arr[h] -= 1;
                    let mut cpy = arr;
                    let dist = dealer_dist_with_two(&mut cpy, up, h, self.h17, &mut memo);
                    let mut ev = 0.0;
                    for i in 0..6 {
                        ev += settle_vs_player(t2, i) * dist[i];
                    }
                    acc += p_h * ev;
                    denom += p_h;
                    arr[h] += 1;
                }
                if denom > 0.0 {
                    total_acc += p_r * (acc / denom);
                }
            }
            arr[r] += 1;
        }
        Ok(total_acc)
    }

    /// Double EV (per-stake): draw exactly one card then settle.
    fn double_ev(
        &self,
        pt_total: i32,
        pt_soft: bool,
        up: usize,
        deck: Vec<Count>,
        hole_constraint: i32,
        _depth_dbl: Option<usize>,
    ) -> PyResult<f64> {
        self.hit_then_stand_ev(pt_total, pt_soft, up, deck, hole_constraint, None)
    }

    /// Split EV (per original stake): average of the two child hands’ per-stake EV.
    fn split_ev(
        &self,
        pair_rank: usize,
        up: usize,
        deck: Vec<Count>,
        hole_constraint: i32,
        das: bool,
        split_aces_one: bool,
        _depth_split: Option<usize>,
    ) -> PyResult<f64> {
        let mut arr = [0i32; 10];
        for i in 0..10 {
            arr[i] = *deck.get(i).unwrap_or(&0);
        }
        let rem0: i32 = arr.iter().sum();
        if rem0 <= 0 {
            return Ok(0.0);
        }

        let mut total = 0.0;
        for r in 0..10 {
            let c = arr[r];
            if c <= 0 {
                continue;
            }
            let p = (c as f64) / (rem0 as f64);
            arr[r] -= 1;
            let (t, s) = add_to(rank_val(pair_rank), false, r);

            let ev_child = if split_aces_one && pair_rank == 0 {
                self.stand_ev(t, s, up, arr.to_vec(), hole_constraint, None)?
            } else {
                let es = self.stand_ev(t, s, up, arr.to_vec(), hole_constraint, None)?;
                let eh = self.hit_then_stand_ev(t, s, up, arr.to_vec(), hole_constraint, None)?;
                let ed = if das {
                    self.double_ev(t, s, up, arr.to_vec(), hole_constraint, None)?
                } else {
                    f64::NEG_INFINITY
                };
                es.max(eh.max(ed))
            };

            total += p * ev_child;
            arr[r] += 1;
        }
        Ok(total)
    }
}

#[pymodule]
fn rustcore(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<BlackjackSimulator>()?;
    Ok(())
}
