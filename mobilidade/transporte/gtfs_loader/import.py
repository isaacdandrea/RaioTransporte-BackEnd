import os
p = r"C:/Users/isaac/Documents/gtfs-emtu/trips.txt"
with open(p, encoding="utf-8-sig", newline="") as f:
    print(repr(f.readline().strip()))