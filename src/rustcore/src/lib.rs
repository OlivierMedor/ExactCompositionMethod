use pyo3::prelude::*;
use std::collections::{HashMap, VecDeque};
use rand::seq::SliceRandom;
use rand::thread_rng;

// Deck state is a simple array of card counts for ranks 1-10.
type Deck = [u8; 10];

// --- Data Structures for Memoization Keys ---
#[derive(Clone, Eq, PartialEq, Hash)]
struct DpKey {
    hand: Vec<u8>,
    up_card: u8,
    deck: Deck,
    can_double: bool,
    depth: u8,
}

#[derive(Clone, Eq, PartialEq, Hash)]
struct DealerKey {
    hand: Vec<u8>,
    deck: Deck,
}

#[pyclass]
struct BlackjackSimulator {
    shoe: Deck,
    initial_shoe: Deck,
    rules: HashMap<String, f64>,
    stats: HashMap<String, f64>,
    // Memoization tables to store results of expensive calculations
    dp_memo: HashMap<DpKey, (char, f64)>,
    dealer_memo: HashMap<DealerKey, HashMap<u8, f64>>,
}

#[pymethods]
impl BlackjackSimulator {
    #[new]
    fn new(rules: HashMap<String, f64>, _seed: Option<u64>) -> Self {
        let num_decks = rules.get("num_decks").cloned().unwrap_or(8.0) as u8;
        let mut initial_shoe = [4 * num_decks; 10];
        initial_shoe[9] = 16 * num_decks;

        BlackjackSimulator {
            shoe: initial_shoe,
            initial_shoe,
            rules,
            stats: HashMap::new(),
            dp_memo: HashMap::new(),
            dealer_memo: HashMap::new(),
        }
    }

    /// Plays one full hand of blackjack and returns the result.
    fn play_hand_py(&mut self) -> PyResult<HashMap<String, f64>> {
        let penetration = self.rules.get("reshuffle_penetration").cloned().unwrap_or(0.5);
        let initial_cards = self.initial_shoe.iter().sum::<u8>() as f64;
        if (self.shoe.iter().sum::<u8>() as f64) < initial_cards * (1.0 - penetration) {
            self.shoe = self.initial_shoe;
            *self.stats.entry("reshuffles".to_string()).or_insert(0.0) += 1.0;
            self.dp_memo.clear();
            self.dealer_memo.clear();
        }

        let player_hand = vec![self.draw_card(), self.draw_card()];
        let up_card = self.draw_card();
        let solver_deck = self.shoe;

        let (player_total, _) = hand_value(&player_hand);
        let player_bj = player_total == 21;

        let mut dealer_bj = false;
        let mut hole_card = 0;
        let mut hole_constraint: Option<u8> = None;

        if up_card == 1 || up_card == 10 {
            hole_card = self.draw_card();
            let peek_rank = if up_card == 1 { 10 } else { 1 };
            if hole_card == peek_rank {
                dealer_bj = true;
            } else {
                hole_constraint = Some(peek_rank);
            }
        }
        
        if player_bj || dealer_bj {
            let mut result = HashMap::new();
            result.insert("wagered".to_string(), 1.0);
            if player_bj && !dealer_bj { result.insert("pnl".to_string(), self.rules.get("blackjack_payout").cloned().unwrap_or(1.5)); }
            else if dealer_bj && !player_bj { result.insert("pnl".to_string(), -1.0); }
            else { result.insert("pnl".to_string(), 0.0); }
            return Ok(result);
        }
        
        let mut hands_to_play = VecDeque::from(vec![(player_hand, 1.0, solver_deck)]);
        let mut final_hands: Vec<(Vec<u8>, f64)> = Vec::new();
        let max_splits = *self.rules.get("max_splits").unwrap_or(&1.0) as usize;

        while let Some((mut hand, mut bet, mut current_solver_deck)) = hands_to_play.pop_front() {
            loop {
                hand.sort(); // Canonicalize for DP
                let (total, _) = hand_value(&hand);
                if total >= 21 { break; }

                let can_split = hand.len() == 2 && hand[0] == hand[1] && (hands_to_play.len() + final_hands.len()) < max_splits;
                
                let action = if can_split && self.should_split(hand[0], up_card) {
                    'P'
                } else {
                    let can_double = hand.len() == 2;
                    let dp_depth = self.rules.get("dp_depth").cloned().unwrap_or(1.0) as u8;
                    self.dp_decision(&hand, up_card, &current_solver_deck, can_double, dp_depth, hole_constraint).0
                };

                *self.stats.entry(format!("action_{}", action)).or_insert(0.0) += 1.0;

                match action {
                    'S' => break,
                    'D' => {
                        bet *= 2.0;
                        let new_card = self.draw_card();
                        hand.push(new_card);
                        break; // Doubling is terminal
                    }
                    'H' => {
                        let new_card = self.draw_card();
                        hand.push(new_card);
                        current_solver_deck[(new_card - 1) as usize] -= 1;
                    }
                    'P' => {
                        let split_card = hand[0];
                        let c1 = self.draw_card();
                        let c2 = self.draw_card();
                        let deck_after_split = tuple_remove(&tuple_remove(&current_solver_deck, c1), c2);

                        hands_to_play.push_back((vec![split_card, c1], 1.0, deck_after_split));
                        hands_to_play.push_back((vec![split_card, c2], 1.0, deck_after_split));
                        
                        hand.clear(); // Mark this hand as resolved
                        break;
                    }
                    _ => break, // Should not happen
                }
            }
            if !hand.is_empty() {
                final_hands.push((hand, bet));
            }
        }
        
        if hole_card == 0 { hole_card = self.draw_card(); }
        let mut dealer_hand = vec![up_card, hole_card];
        let h17 = self.rules.get("dealer_hits_soft_17").cloned().unwrap_or(1.0) == 1.0;
        
        loop {
            let (d_total, d_soft) = hand_value(&dealer_hand);
            if d_total > 21 || d_total > 17 || (d_total == 17 && !d_soft) || (d_total == 17 && d_soft && !h17) { break; }
            dealer_hand.push(self.draw_card());
        }

        let (d_final, _) = hand_value(&dealer_hand);
        let mut total_pnl = 0.0;
        let mut total_wagered = 0.0;

        for (hand, bet) in final_hands {
            total_wagered += bet;
            let (p_final, _) = hand_value(&hand);
            if p_final > 21 { total_pnl -= bet; }
            else if d_final > 21 || p_final > d_final { total_pnl += bet; }
            else if p_final < d_final { total_pnl -= bet; }
        }
        
        let mut result = HashMap::new();
        result.insert("pnl".to_string(), total_pnl);
        result.insert("wagered".to_string(), total_wagered);
        Ok(result)
    }

    fn get_stats(&self) -> PyResult<HashMap<String, f64>> {
        Ok(self.stats.clone())
    }
}

// Internal Rust functions
impl BlackjackSimulator {
    fn draw_card(&mut self) -> u8 {
        let mut choices: Vec<u8> = Vec::with_capacity(self.shoe.iter().sum::<u8>() as usize);
        for (rank_idx, &count) in self.shoe.iter().enumerate() {
            for _ in 0..count { choices.push(rank_idx as u8 + 1); }
        }
        let card = *choices.choose(&mut thread_rng()).unwrap();
        self.shoe[(card - 1) as usize] -= 1;
        card
    }

    fn should_split(&self, rank: u8, up_card: u8) -> bool {
        match rank { // Basic Strategy split decisions
            1 | 8 => true,
            9 => ![7, 10, 1].contains(&up_card),
            7 => up_card <= 7,
            6 => up_card <= 6,
            4 => [5, 6].contains(&up_card),
            2 | 3 => up_card <= 7,
            _ => false,
        }
    }
}

// --- Full DP Solver and Dealer PMF ---
impl BlackjackSimulator {
    fn dp_decision(&mut self, hand: &Vec<u8>, up_card: u8, deck: &Deck, can_double: bool, depth: u8, hole_constraint: Option<u8>) -> (char, f64) {
        let mut sorted_hand = hand.clone();
        sorted_hand.sort();
        let key = DpKey { hand: sorted_hand, up_card, deck: *deck, can_double, depth };
        if let Some(cached) = self.dp_memo.get(&key) {
            return *cached;
        }

        let (p_total, _) = hand_value(hand);
        
        let ev_s = self.calculate_stand_ev(p_total, up_card, deck, hole_constraint);
        let mut best_action = 'S';
        let mut best_ev = ev_s;

        let ev_h = self.calculate_hit_ev(hand, up_card, deck, depth, hole_constraint);
        if ev_h > best_ev {
            best_action = 'H';
            best_ev = ev_h;
        }
        
        if can_double {
            let ev_d = self.calculate_double_ev(hand, up_card, deck, hole_constraint);
            if ev_d > best_ev {
                best_action = 'D';
                best_ev = ev_d;
            }
        }

        self.dp_memo.insert(key, (best_action, best_ev));
        (best_action, best_ev)
    }

    fn calculate_stand_ev(&mut self, p_total: u8, up_card: u8, deck: &Deck, hole_constraint: Option<u8>) -> f64 {
        let dealer_pmf = self.get_dealer_dist(up_card, deck, hole_constraint);
        let mut ev = 0.0;
        for (&score, &prob) in dealer_pmf.iter() {
            if score > 21 { ev += prob; } // Dealer busts
            else if p_total > score { ev += prob; }
            else if p_total < score { ev -= prob; }
        }
        ev
    }

    fn calculate_hit_ev(&mut self, hand: &Vec<u8>, up_card: u8, deck: &Deck, depth: u8, hole_constraint: Option<u8>) -> f64 {
        let mut ev = 0.0;
        let total_cards = deck.iter().sum::<u8>() as f64;
        if total_cards == 0.0 { return -1.0; }

        for r in 1..=10 {
            let count = deck[r - 1];
            if count > 0 {
                let prob = count as f64 / total_cards;
                let mut next_hand = hand.clone();
                next_hand.push(r as u8);
                let next_deck = tuple_remove(deck, r as u8);
                let (next_total, _) = hand_value(&next_hand);

                if next_total > 21 {
                    ev -= prob;
                } else {
                    let next_ev = if depth > 0 {
                        self.dp_decision(&next_hand, up_card, &next_deck, false, depth - 1, hole_constraint).1
                    } else {
                        self.calculate_stand_ev(next_total, up_card, &next_deck, hole_constraint)
                    };
                    ev += prob * next_ev;
                }
            }
        }
        ev
    }
    
    fn calculate_double_ev(&mut self, hand: &Vec<u8>, up_card: u8, deck: &Deck, hole_constraint: Option<u8>) -> f64 {
        let mut ev = 0.0;
        let total_cards = deck.iter().sum::<u8>() as f64;
        if total_cards == 0.0 { return -2.0; }

        for r in 1..=10 {
            let count = deck[r - 1];
            if count > 0 {
                let prob = count as f64 / total_cards;
                let mut next_hand = hand.clone();
                next_hand.push(r as u8);
                let next_deck = tuple_remove(deck, r as u8);
                let (next_total, _) = hand_value(&next_hand);
                if next_total > 21 {
                    ev -= prob;
                } else {
                    ev += prob * self.calculate_stand_ev(next_total, up_card, &next_deck, hole_constraint);
                }
            }
        }
        ev * 2.0
    }

    fn get_dealer_dist(&mut self, up_card: u8, deck: &Deck, hole_constraint: Option<u8>) -> HashMap<u8, f64> {
        let mut avg_dist = HashMap::new();
        let deck_no_up = tuple_remove(deck, up_card);
        let mut total_allowed_cards = 0;

        for r in 1..=10 {
            if hole_constraint == Some(r as u8) { continue; }
            total_allowed_cards += deck_no_up[r - 1];
        }

        if total_allowed_cards == 0 { return HashMap::new(); }

        for r in 1..=10 {
            if hole_constraint == Some(r as u8) { continue; }
            let count = deck_no_up[r - 1];
            if count > 0 {
                let prob = count as f64 / total_allowed_cards as f64;
                let hand = vec![up_card, r as u8];
                let dist = self.get_dealer_final_dist(hand, tuple_remove(&deck_no_up, r as u8));
                for (&score, &sub_prob) in dist.iter() {
                    *avg_dist.entry(score).or_insert(0.0) += prob * sub_prob;
                }
            }
        }
        avg_dist
    }

    fn get_dealer_final_dist(&mut self, hand: Vec<u8>, deck: Deck) -> HashMap<u8, f64> {
        let mut sorted_hand = hand.clone();
        sorted_hand.sort();
        let key = DealerKey { hand: sorted_hand, deck };
        if let Some(cached) = self.dealer_memo.get(&key) {
            return cached.clone();
        }

        let (total, is_soft) = hand_value(&hand);
        let h17 = self.rules.get("dealer_hits_soft_17").cloned().unwrap_or(1.0) == 1.0;

        if total > 21 { return HashMap::from([(22, 1.0)]); } // 22 = Bust
        if total > 17 || (total == 17 && !is_soft) || (total == 17 && is_soft && !h17) {
            return HashMap::from([(total, 1.0)]);
        }

        let total_cards = deck.iter().sum::<u8>() as f64;
        let mut final_dist = HashMap::new();
        if total_cards == 0.0 { return HashMap::from([(total, 1.0)]); }

        for r in 1..=10 {
            if deck[r - 1] > 0 {
                let prob = deck[r - 1] as f64 / total_cards;
                let mut next_hand = hand.clone();
                next_hand.push(r as u8);
                let dist = self.get_dealer_final_dist(next_hand, tuple_remove(&deck, r as u8));
                for (&score, &sub_prob) in dist.iter() {
                    *final_dist.entry(score).or_insert(0.0) += prob * sub_prob;
                }
            }
        }
        self.dealer_memo.insert(key, final_dist.clone());
        final_dist
    }
}

fn hand_value(hand: &Vec<u8>) -> (u8, bool) {
    let mut total = hand.iter().sum::<u8>();
    let mut aces = hand.iter().filter(|&&c| c == 1).count();
    let mut is_soft = false;
    while aces > 0 && total + 10 <= 21 {
        total += 10;
        is_soft = true;
        aces -= 1;
    }
    (total, is_soft)
}

// Helper to convert deck tuple for PyO3
fn tuple_remove(deck: &Deck, rank: u8) -> Deck {
    let mut new_deck = deck.clone();
    if new_deck[(rank - 1) as usize] > 0 {
        new_deck[(rank - 1) as usize] -= 1;
    }
    new_deck
}

#[pymodule]
fn rustcore(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<BlackjackSimulator>()?;
    Ok(())
}