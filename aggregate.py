import csv, collections

p = "/host/run.csv"
by = collections.defaultdict(lambda: {"n":0,"units":0.0,"neg":0,"ins":0.0,"wager":0.0,"runits":0.0})

with open(p, newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        act = row["action"]
        units  = float(row["stake_units"])
        runits = float(row["realized_units"])
        insb   = float(row["ins_bet"])
        wager  = float(row["wager_realized"])
        d = by[act]
        d["n"]     += 1
        d["units"] += units
        d["runits"]+= runits
        d["ins"]   += insb
        d["wager"] += wager
        if runits < 0:
            d["neg"] += 1

print("Action  n   avg_units  neg%   avg_ins_bet  avg_realized_units  avg_wager")
for act, acc in by.items():
    n    = acc["n"]
    au   = acc["units"]/n
    neg  = 100*acc["neg"]/n
    ai   = acc["ins"]/n
    aru  = acc["runits"]/n
    aw   = acc["wager"]/n
    print(f"{act:7s} {n:4d}   {au:7.3f}  {neg:5.1f}%   {ai:10.3f}      {aru:9.3f}        {aw:8.3f}")
