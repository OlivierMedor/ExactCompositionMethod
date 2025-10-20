# analyze_doubles.py
import csv, statistics as st, os, sys

fn = "/data/doubles.csv"
if not os.path.exists(fn):
    sys.exit("doubles.csv not found")

rows = []
with open(fn, newline="") as f:
    r = csv.DictReader(f)
    need = {
        "ev_stand","ev_hit","ev_double",
        "realized_units","stand_shadow_units","hit_shadow_units"
    }
    miss = need - set(r.fieldnames or [])
    if miss:
        sys.exit("CSV missing columns: "+", ".join(sorted(miss)))
    for x in r:
        evs = float(x["ev_stand"])
        evh = float(x["ev_hit"])
        evd = float(x["ev_double"])
        lift = evd - max(evs, evh)                 # per-stake lift
        # realized_units is 2× stake for a double; normalize to per-stake
        real_per = float(x["realized_units"]) / 2.0
        shadow_best = max(float(x["stand_shadow_units"]),
                          float(x["hit_shadow_units"]))
        rows.append((lift, real_per - shadow_best))

def bucket(a,b):
    s = [d for d in rows if a<=d[0]<b]
    if s:
        print(f"lift in [{a:.3f},{b:.3f}): n={len(s):5d}  avg(real-best)={st.mean(d[1] for d in s):+.5f}")

for a,b in [(0.00,0.02),(0.02,0.05),(0.05,0.10),(0.10,9.99)]:
    bucket(a,b)

print("ALL doubles avg(real-best):", f"{st.mean(d[1] for d in rows):+.5f}" if rows else "n/a")
