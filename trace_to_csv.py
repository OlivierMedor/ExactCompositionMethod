import re, csv, sys
pat = re.compile(r'TRACE.+double.+EVs:\s*STAND=([+-]?\d+\.\d+)\s+HIT=([+-]?\d+\.\d+)\s+DOUBLE=([+-]?\d+\.\d+).+realized=([+-]?\d+\.\d+).+stand_shadow=([+-]?\d+\.\d+)')
rows=[]
with open("doubles.log","r",encoding="utf-8",errors="ignore") as f:
    for ln in f:
        m = pat.search(ln)
        if m:
            rows.append({
                "ev_stand": m.group(1),
                "ev_hit": m.group(2),
                "ev_double": m.group(3),
                "realized_units": m.group(4),
                "stand_shadow_units": m.group(5),
            })
with open("doubles.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["ev_stand","ev_hit","ev_double","realized_units","stand_shadow_units"])
    w.writeheader(); w.writerows(rows)
print("wrote doubles.csv with", len(rows), "rows")
