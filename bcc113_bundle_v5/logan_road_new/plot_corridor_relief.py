#!/usr/bin/env python3
"""plot_corridor_relief.py -- corridor density relief graphics, stdlib only.

Reads Aimsun section_timeseries.csv from run result dirs and writes one HTML
file with canvas heatmaps:
  1. per-arm main-approach density (junction x time) -- where the corridor loads
  2. per-TSP-arm DELTA vs same-seed NO_TSP (blue = relieved, red = worsened)
  3. corridor-mean density lines over time per arm
  4. same pair for queued vehicles

Usage:
  python plot_corridor_relief.py <run_dir> [<run_dir> ...] [-o relief.html]

Arm/seed are parsed from the directory name (e.g. ..._CONT_DE_EASE_seed500_...,
NO_TSP_seed300_...). Junction order = projection onto the corridor axis
(centroid of first route junction -> centroid of last).
"""
import csv
import glob
import json
import math
import os
import re
import sys

BIN_S = 60.0


def corridor_axis(centroid_files):
    """(origin, unit) corridor axis from route-group endpoint centroids."""
    pts = {}
    for f in centroid_files:
        try:
            for r in csv.DictReader(open(f, encoding="utf-8-sig")):
                pts[str(r["junction_id"])] = (float(r["x"]), float(r["y"]))
        except Exception:
            pass
    if "17249" in pts and "21895" in pts:
        ax = (pts["21895"][0] - pts["17249"][0],
              pts["21895"][1] - pts["17249"][1])
    else:
        ks = list(pts)
        ax = (pts[ks[-1]][0] - pts[ks[0]][0], pts[ks[-1]][1] - pts[ks[0]][1]) \
            if len(ks) > 1 else (1.0, 0.0)
    n = math.hypot(*ax) or 1.0
    o = pts.get("17249", (0.0, 0.0))
    return o, (ax[0] / n, ax[1] / n), pts


def parse_run(d):
    """(arm, seed, grid) grid[junction] = {tbin: [k_sum, k_n, q_sum, q_n]}."""
    m = re.search(r"_seed(\d+)_", os.path.basename(d))
    seed = m.group(1) if m else "?"
    up = os.path.basename(d).upper()
    if "NO_TSP" in up:
        arm = "NO_TSP"
    else:
        m2 = re.match(r"([A-Z0-9_]+?)_seed\d+_", os.path.basename(d),
                      re.IGNORECASE)
        arm = (m2.group(1).upper() if m2 else os.path.basename(d)[:24])
    grid = {}
    try:
        fp = os.path.join(d, "section_timeseries.csv")
        for r in csv.DictReader(open(fp, encoding="utf-8-sig")):
            if str(r.get("IsMain", "1")) != "1":
                continue
            j = str(r.get("IntersectionID", "?"))
            try:
                b = int(float(r.get("t_start_s", 0)) // BIN_S)
                k = float(r.get("k_vkm_lane", 0) or 0)
                q = float(r.get("queue_veh", 0) or 0)
            except Exception:
                continue
            cell = grid.setdefault(j, {}).setdefault(
                b, [0.0, 0, 0.0, 0])
            cell[0] += k
            cell[1] += 1
            cell[2] += q
            cell[3] += 1
    except Exception as e:
        print(f"  WARN {d}: {e}")
    return arm, seed, grid


def main(argv):
    out = "corridor_relief.html"
    dirs = []
    it = iter(argv)
    for a in it:
        if a == "-o":
            out = next(it)
        else:
            dirs.extend(glob.glob(a) if any(
                c in a for c in "*?") else [a])
    dirs = [d for d in dirs if os.path.isdir(d)]
    seen, uniq = set(), []
    for d in dirs:
        _k = os.path.normcase(os.path.abspath(d))
        if _k not in seen:
            seen.add(_k)
            uniq.append(d)
    dirs = uniq
    if not dirs:
        print(__doc__)
        return 1
    logs = os.path.join(os.path.dirname(os.path.abspath(dirs[0])),
                        "..", "logs")
    o, u, pts = corridor_axis(sorted(glob.glob(os.path.join(
        os.path.dirname(os.path.abspath(dirs[0])), "..", "logs",
        "junction_centroids_*.csv"))))
    runs = []
    for d in sorted(dirs):
        arm, seed, grid = parse_run(d)
        runs.append({"arm": arm, "seed": seed, "dir": d, "grid": grid,
                     "mtime": os.path.getmtime(d)})
        print(f"  {arm} seed {seed}: {sum(len(v) for v in grid.values())} "
              f"junction-bins ({os.path.basename(d)[-11:]})")
    # Re-runs happen: keep the latest dir per (arm, seed).
    latest = {}
    for r in runs:
        k = (r["arm"], r["seed"])
        if k not in latest or r["mtime"] > latest[k]["mtime"]:
            latest[k] = r
    if len(latest) != len(runs):
        print(f"  (kept latest of {len(runs)} dirs -> {len(latest)} runs)")
    runs = sorted(latest.values(),
                  key=lambda r: (r["arm"], r["seed"]))
    jcts = sorted({j for r in runs for j in r["grid"]},
                   key=lambda j: (pts.get(j, (0, 0))[0] - o[0]) * u[0] +
                   (pts.get(j, (0, 0))[1] - o[1]) * u[1])
    nbins = 0
    for r in runs:
        for cells in r["grid"].values():
            if cells:
                nbins = max(nbins, max(cells) + 1)
    nbins = max(nbins, 1)

    def mat(run, idx):
        m = []
        for j in jcts:
            row = []
            cells = run["grid"].get(j, {})
            for b in range(nbins):
                c = cells.get(b)
                if c and c[idx + 1] > 0:
                    row.append(round(c[idx] / c[idx + 1], 3))
                else:
                    row.append(None)
            m.append(row)
        return m

    payload = {"junctions": jcts, "nbins": nbins, "bin_s": BIN_S,
               "arms": []}
    byseed = {}
    for r in runs:
        byseed.setdefault(r["seed"], {})[r["arm"]] = r
    for r in runs:
        payload["arms"].append({
            "arm": r["arm"], "seed": r["seed"],
            "density": mat(r, 0), "queue": mat(r, 2)})
    payload["deltas"] = []
    for seed, arms in byseed.items():
        base = arms.get("NO_TSP")
        if not base:
            continue
        bd, bq = mat(base, 0), mat(base, 2)
        for arm, r in arms.items():
            if arm == "NO_TSP":
                continue
            dd, dq = mat(r, 0), mat(r, 2)
            dm = [[(a - b) if (a is not None and b is not None) else None
                   for a, b in zip(ra, rb)] for ra, rb in zip(dd, bd)]
            qm = [[(a - b) if (a is not None and b is not None) else None
                   for a, b in zip(ra, rb)] for ra, rb in zip(dq, bq)]
            payload["deltas"].append({"arm": arm, "seed": seed,
                                      "density": dm, "queue": qm})
    html = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Corridor relief</title><style>
body{font-family:sans-serif;margin:16px;background:#f7f7f7}
h2{margin-top:28px}canvas{border:1px solid #999;background:#fff;max-width:100%%}
.lbl{font-size:12px;color:#555}</style></head><body>
<h1>Corridor density relief (main approaches, %(bin)ds bins)</h1>
<div id="root"></div>
<script>
const D=%(data)s;
function draw(cv, m, vmin, vmax, div){
  const J=m.length, B=m[0].length, cw=Math.max(2,Math.floor(900/B)), ch=16;
  cv.width=B*cw+120; cv.height=J*ch+8;
  const g=cv.getContext('2d'); g.fillStyle='#fff'; g.fillRect(0,0,cv.width,cv.height);
  for(let j=0;j<J;j++)for(let b=0;b<B;b++){
    const v=m[j][b];
    if(v===null||v===undefined){g.fillStyle='#eee';}
    else{
      let t=Math.max(0,Math.min(1,(v-vmin)/((vmax-vmin)||1)));
      if(div){ // blue-white-red, vmin=-smax,vmax=+smax
        t=(v-vmin)/((vmax-vmin)||1);
        g.fillStyle=t<0.5?`rgb(${Math.round(255*t*2)},${Math.round(255*t*2)},255)`
                         :`rgb(255,${Math.round(255*(1-t)*2)},${Math.round(255*(1-t)*2)})`;
      }else{g.fillStyle=`rgb(255,${Math.round(255*(1-t))},${Math.round(255*(1-t))})`;}
    }
    g.fillRect(120+b*cw,j*ch,cw-0.5,ch-0.5);
  }
  g.fillStyle='#000'; g.font='11px sans-serif';
  for(let j=0;j<J;j++)g.fillText(D.junctions[j],4,(j+1)*ch-4);
}
function line(cv, series){
  const W=900,H=180; cv.width=W+50; cv.height=H+20;
  const g=cv.getContext('2d'); g.fillStyle='#fff'; g.fillRect(0,0,cv.width,cv.height);
  let mx=0.01; series.forEach(s=>s.y.forEach(v=>{if(v>mx)mx=v;}));
  const cols=['#000','#1a7f37','#cf222e','#8250df','#0969da','#bf3989'];
  series.forEach((s,i)=>{
    g.strokeStyle=cols[i%%cols.length]; g.lineWidth=1.5; g.beginPath();
    s.y.forEach((v,b)=>{const x=50+b/(s.y.length-1)*W, y=H-(v/mx)*H;
      b?g.lineTo(x,y):g.moveTo(x,y);});
    g.stroke();
  });
  g.fillStyle='#000'; g.font='11px sans-serif';
  series.forEach((s,i)=>g.fillText(s.l,4,14+i*13));
}
const root=document.getElementById('root');
function sec(t){const h=document.createElement('h2');h.textContent=t;root.appendChild(h);return h;}
function cap(t){const d=document.createElement('div');d.className='lbl';d.textContent=t;root.appendChild(d);}
D.arms.forEach(a=>{
  sec(`${a.arm} seed ${a.seed} -- main density (veh/km/lane)`);
  const c=document.createElement('canvas');root.appendChild(c);draw(c,a.density,0,60,false);
  sec(`${a.arm} seed ${a.seed} -- queue (veh)`);const c2=document.createElement('canvas');root.appendChild(c2);draw(c2,a.queue,0,12,false);
});
D.deltas.forEach(d=>{
  sec(`DELTA ${d.arm} minus NO_TSP seed ${d.seed} -- density (blue=relieved)`);
  const c=document.createElement('canvas');root.appendChild(c);draw(c,d.density,-15,15,true);
  sec(`DELTA ${d.arm} minus NO_TSP seed ${d.seed} -- queue (blue=relieved)`);
  const c2=document.createElement('canvas');root.appendChild(c2);draw(c2,d.queue,-4,4,true);
});
sec('Corridor-mean density over time');
(function(){
  const series=D.arms.map(a=>{
    const y=[];for(let b=0;b<D.nbins;b++){let s=0,n=0;
      for(let j=0;j<D.junctions.length;j++){const v=a.density[j][b];if(v!==null){s+=v;n++;}}
      y.push(n?+(s/n).toFixed(2):0);}
    return {l:`${a.arm} s${a.seed}`,y};});
  const c=document.createElement('canvas');root.appendChild(c);line(c,series);
})();
cap('Bins: %(bin)ds. Junctions ordered along corridor axis (northwest to southeast). White/red = loaded, blue (deltas) = relieved vs NO_TSP same seed.');
</script></body></html>""" % {"data": json.dumps(payload), "bin": int(BIN_S)}
    open(out, "w", encoding="utf-8").write(html)
    print(f"wrote {out} ({os.path.getsize(out)//1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
