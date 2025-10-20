// rustcore/src/lib.rs
use pyo3::prelude::*;
use pyo3::types::PyList;

/// Very small facade that matches the methods Python calls. Replace the internals
/// with your real engine; signatures are the important part.
#[pyclass]
pub struct BlackjackSimulator {
    shoe: Vec<i32>,
    h17: bool,
}

#[pymethods]
impl BlackjackSimulator {
    #[new]
    pub fn new(shoe_counts: Vec<i32>, hit_soft_17: bool) -> Self {
        BlackjackSimulator { shoe: shoe_counts, h17: hit_soft_17 }
    }

    /// EV of standing (per 1 unit) given player total/softness and dealer upcard.
    /// `deck` is A..T bucket counts AFTER removing player's two + dealer up.
    pub fn stand_ev(&self,
                    _p_total: i32,
                    _p_soft: bool,
                    _up_idx: i32,
                    _deck: &PyList,
                    _hole_c: i32) -> f64 {
        // Plug your accurate model here. This placeholder is neutral-ish.
        // It should return expected value (wins=+1, pushes=0, losses=-1) per 1 unit.
        0.0
    }

    /// EV of hit-then-stand policy from this state (per 1 unit).
    pub fn hit_then_stand_ev(&self,
                             _p_total: i32,
                             _p_soft: bool,
                             _up_idx: i32,
                             _deck: &PyList,
                             _hole_c: i32) -> f64 {
        0.0
    }

    /// EV of double-down from this state **in two units**. Python divides by 2
    /// to compare with per-unit EVs (stand/hit).
    pub fn double_ev(&self,
                     _p_total: i32,
                     _p_soft: bool,
                     _up_idx: i32,
                     _deck: &PyList,
                     _hole_c: i32) -> f64 {
        0.0
    }
}

#[pymodule]
fn rustcore(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<BlackjackSimulator>()?;
    Ok(())
}
