import math, json
pts = {
17249:(504611.644,6958319.649),17308:(507814.992,6953962.623),17383:(506263.511,6955862.632),
17498:(507414.111,6954474.700),17628:(508072.468,6953119.317),17963:(507349.130,6954535.996),
18044:(508061.011,6953531.466),18942:(507081.899,6954926.907),19185:(505081.881,6957285.285),
19196:(507877.735,6952317.144),19363:(504407.060,6958332.455),19474:(504639.458,6957858.732),
19882:(506060.896,6956047.721),20270:(505298.361,6956760.775),20280:(507921.774,6953850.212),
20283:(505209.953,6957114.200),20844:(507897.185,6952118.310),21197:(505607.613,6956461.854),
21553:(505835.343,6956256.028),21847:(507719.849,6954096.453),21895:(505236.754,6956892.823),
22232:(504584.315,6958052.881),22603:(505255.458,6956805.382)}
north=[17249,17308,17383,17498,17628,17963,18044,18942]
south=[19196,19363,19474,19882,21895]
missing=[19185,20270,20280,20283,20844,21197,21553,21847,22232,22603]

def proj_t(p,a,b):
    px,py=p; ax,ay=a; bx,by=b
    vx,vy=bx-ax,by-ay; wx,wy=px-ax,py-ay
    c2=vx*vx+vy*vy
    if c2==0: return 0.0
    return max(0.0,min(1.0,(wx*vx+wy*vy)/c2))

def dist_to_seg(p,a,b):
    t=proj_t(p,a,b)
    ax,ay=a; bx,by=b
    qx=ax+t*(bx-ax); qy=ay+t*(by-ay)
    return math.hypot(p[0]-qx,p[1]-qy),t

assignment={}
for m in missing:
    best=None
    for name,rt in (('north',north),('south',south)):
        for i in range(len(rt)-1):
            d,t=dist_to_seg(pts[m],pts[rt[i]],pts[rt[i+1]])
            if best is None or d<best[0]:
                best=(d,name,i,t)
        # before-first distance as edge -1 with t=0
        d,t=dist_to_seg(pts[m],pts[rt[0]],pts[rt[0]])
        if best is None or d<best[0]:
            best=(d,name,-1,0.0)
        # after-last as edge len-1 with t=1
        d,t=dist_to_seg(pts[m],pts[rt[-1]],pts[rt[-1]])
        if best is None or d<best[0]:
            best=(d,name,len(rt)-1,1.0)
    assignment[m]=best
    print(m, best)

def best_spot(m, route):
    b=assignment[m]
    if b[1]!=('north' if route==north else 'south'):
        return None
    return b[2],b[3]  # edge index, t

ins_by_edge={id(north): {}, id(south): {}}
for m,b in assignment.items():
    rt = north if b[1]=='north' else south
    ins_by_edge[id(rt)].setdefault(b[2],None)
    if ins_by_edge[id(rt)][b[2]] is None:
        ins_by_edge[id(rt)][b[2]]=[]
    ins_by_edge[id(rt)][b[2]].append((b[3],m))

def merge(route, inss):
    out=[]
    for i in range(len(route)-1):
        out.append(route[i])
        if i in inss:
            out.extend(m for _,m in sorted(inss[i]))
    out.append(route[-1])
    # edges == -1 -> before first
    if -1 in inss:
        out = [m for _,m in sorted(inss[-1])] + out
    return out

north_new = merge(north, ins_by_edge[id(north)])
south_new = merge(south, ins_by_edge[id(south)])
print('north_new =', north_new)
print('south_new =', south_new)
