import ast, os

def load_arms(path, env=None):
    src = open(path, errors='replace').read()
    tree = ast.parse(src)
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                consts[node.targets[0].id] = ast.literal_eval(node.value)
            except Exception:
                pass
    if env:
        os.environ.update(env)
    # resolve referenced names from consts
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in consts and not isinstance(node.ctx, ast.Store):
            pass
    arms = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ARMS' for t in node.targets):
            arms = node.value
    out = {}
    for elt in arms.elts:
        d = {}
        for k, v in zip(elt.keys, elt.values):
            key = k.value if isinstance(k, ast.Constant) else ast.dump(k)
            try:
                d[key] = ast.literal_eval(v)
            except Exception:
                # try resolving names / _merge / conditionals
                try:
                    d[key] = eval(compile(ast.Expression(v), '<v>', 'eval'),
                                  dict(consts, _IS_LOGAN=(env or {}).get('CORRIDOR', 'kg') == 'logan_road_new' or 'logan' in (env or {}).get('CORRIDOR', '')))
                except Exception as e:
                    d[key] = f'<unresolved: {e}>'
        out[d.get('name')] = d
    return out

aim = load_arms(r'C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\champion_search.py')
sumo_logan = load_arms(r'Z:\tsp\sumo_hpc\sumo_bridge\sweep_arms.py', {'CORRIDOR': 'logan_road_new'})
sumo_kg = load_arms(r'Z:\tsp\sumo_hpc\sumo_bridge\sweep_arms.py', {'CORRIDOR': 'kg'})

print('Aimsun arms:', sorted(aim))
print('SUMO legacy ARMS:', sorted(sumo_logan))
shared = sorted(set(aim) & set(sumo_logan))
print('shared names:', shared)
for name in shared:
    a, s = aim[name], sumo_logan[name]
    print('=' * 80); print('ARM:', name)
    for k in ['strategy', 'method', 'coordinated', 'coordination_algo']:
        if a.get(k) != s.get(k):
            print(f'  META {k}: aimsun={a.get(k)!r} sumo={s.get(k)!r}')
    ao, so = a.get('reward_overrides', {}), s.get('reward_overrides', {})
    if not isinstance(ao, dict) or not isinstance(so, dict):
        print(f'  OVERRIDES unparsed: aimsun={ao!r} sumo={so!r}'); continue
    for k in sorted(set(ao) | set(so)):
        if ao.get(k) != so.get(k):
            print(f'  FLAG {k}: aimsun={ao.get(k)!r} sumo_logan={so.get(k)!r} sumo_kg={sumo_kg[name].get("reward_overrides", {}).get(k)!r}')
