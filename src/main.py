# src/main.py
import os
import sys
import time

from rustcore import BlackjackSimulator

def main():
    num_hands = int(os.environ.get("NUM_HANDS", 100000))
    seed = int(os.environ.get("SEED")) if "SEED" in os.environ else None

    rules = {
        "num_decks": float(os.environ.get("NUM_DECKS", 8)),
        "dealer_hits_soft_17": 1.0 if not os.environ.get("DEALER_STANDS_S17") == "1" else 0.0,
        "reshuffle_penetration": float(os.environ.get("PENETRATION", 0.5)),
        "blackjack_payout": 1.5,
        "max_splits": 1.0,
    }
    
    print("==============================================", flush=True)
    print("BLACKJACK SIMULATOR (PYTHON + RUST ENGINE)", flush=True)
    print("==============================================", flush=True)
    print(f"NUM_HANDS: {num_hands:,}", flush=True)
    print(f"RULES    : {rules}", flush=True)

    sim = BlackjackSimulator(rules, seed)
    
    total_pnl = 0.0
    total_wagered = 0.0
    
    start_time = time.time()
    last_progress_time = start_time
    
    for i in range(1, num_hands + 1):
        result = sim.play_hand_py()
        total_pnl += result.get("pnl", 0.0)
        total_wagered += result.get("wagered", 1.0)
        
        if i % (num_hands // 20 or 1) == 0 or time.time() - last_progress_time > 2.0 or i == num_hands:
            elapsed = time.time() - start_time
            hps = i / elapsed if elapsed > 0 else 0
            ev = (total_pnl / total_wagered * 100) if total_wagered > 0 else 0.0
            print(f"  Progress: {i:>8,}/{num_hands:,} | EV: {ev:+.4f}% | {hps:,.0f} h/s", flush=True)
            last_progress_time = time.time()
    
    stats = sim.get_stats()
    actions = {k: v for k, v in stats.items() if k.startswith("action_")}
    total_actions = sum(actions.values())
    
    print("\n--- Simulation Complete ---", flush=True)
    print(f"Total Wagered: ${total_wagered:,.2f}", flush=True)
    print(f"Player P/L:    ${total_pnl:,.2f}", flush=True)
    
    ev_percent = (total_pnl / total_wagered * 100) if total_wagered > 0 else 0.0
    print(f"Player EV:     {ev_percent:+.4f}%", flush=True)
    
    if total_actions > 0:
        print("\nAction Frequencies:")
        for action_key, count in sorted(actions.items()):
            action = action_key.split("_")[1]
            rate = count / total_actions
            print(f"  {action}: {rate:>7.2%} ({int(count):,})")

if __name__ == "__main__":
    main()