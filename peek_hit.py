import csv
n=0
with open("/host/run.csv", newline="") as f:
    r=csv.DictReader(f)
    for row in r:
        if row["action"]=="hit":
            print(row["hand"], "bet="+row["bet"], "edge="+row["edge"], "stake_units="+row["stake_units"],
                  "p_totals="+row["p_final_totals"], "dealer="+row["dealer_final"],
                  "runits="+row["realized_units"], "pnl="+row["realized_pnl"])
            n+=1
            if n>=25: break
