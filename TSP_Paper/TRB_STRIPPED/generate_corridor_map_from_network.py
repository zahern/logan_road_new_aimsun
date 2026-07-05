"""
Generate corridor map for the Kelvin Grove corridor using actual network
coordinates from the Aimsun microsimulation model.
Saves fig_kelvin_grove_corridor.png for inclusion in the LaTeX paper.
"""
import osmnx as ox
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from shapely.geometry import Point
import numpy as np
from pyproj import Transformer

OUTPUT_DIR = r'C:\Users\ahernz\github_for_aimsun\TSP_Paper\TRB_STRIPPED'
OUTPUT_FILE = 'fig_kelvin_grove_corridor.png'

# Actual Aimsun network junction coordinates (UTM EPSG:32756)
# Sorted north-to-south along Kelvin Grove Road corridor
JUNCTION_COORDS_UTM = {
    38339:  (500084.0, 6967501.8),
    39572:  (499518.6, 6966649.1),
    39569:  (499894.5, 6966541.3),
    1043762: (499993.1, 6966493.8),
    39587:  (500491.1, 6965703.3),
    39578:  (500459.2, 6965697.1),
    39576:  (500135.2, 6965615.4),
    39593:  (500700.5, 6964925.2),
    36385:  (500672.0, 6964570.2),
    36393:  (500751.2, 6964307.8),
    39590:  (500895.9, 6964115.5),
    39606:  (500949.1, 6964042.8),
}

# Corridor ordering (north to south, route order per intersection_configs.py)
CORRIDOR_A_ORDER = [39606, 39590, 36393, 36385, 39593]  # descending
CORRIDOR_B_ORDER = [39576, 39578, 39587, 1043762, 39569, 39572, 38339]
# Combined route order (north to south)
ROUTE_ORDER = [38339, 39572, 39569, 1043762, 39587, 39578, 39576,
               39593, 36385, 36393, 39590, 39606]

# Convert UTM to lat/lon for OSM download
transformer = Transformer.from_crs('EPSG:32756', 'EPSG:4326', always_xy=True)
junction_latlon = {}
for jid, (x, y) in JUNCTION_COORDS_UTM.items():
    lon, lat = transformer.transform(x, y)
    junction_latlon[jid] = (lon, lat)

# Bounding box with padding
all_lons = [ll[0] for ll in junction_latlon.values()]
all_lats = [ll[1] for ll in junction_latlon.values()]
margin = 0.005
bbox = (min(all_lons) - margin, min(all_lats) - margin,
        max(all_lons) + margin, max(all_lats) + margin)

print('Downloading road network from Overpass API...')
G = ox.graph_from_bbox(bbox, network_type='drive', simplify=True)
print(f'  {len(G.nodes)} nodes, {len(G.edges)} edges')

gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)

def has_name(series_val, target):
    if series_val is None or (isinstance(series_val, float) and np.isnan(series_val)):
        return False
    if isinstance(series_val, list):
        return any(target in str(x) for x in series_val)
    return target in str(series_val)

mask_kg = gdf_edges['name'].apply(lambda n: has_name(n, 'Kelvin Grove'))
kg_edges = gdf_edges[mask_kg]
mask_side = gdf_edges['name'].notna() & ~mask_kg
side_edges = gdf_edges[mask_side]

print(f'Kelvin Grove Rd: {len(kg_edges)} edges')
print(f'Side streets:    {len(side_edges)} edges')

# Project OSM edges and junction points to UTM
gdf_edges_utm = gdf_edges.to_crs(epsg=32756)
kg_edges_utm = kg_edges.to_crs(epsg=32756)
side_edges_utm = side_edges.to_crs(epsg=32756)

# Convert junction coords to shapely Points in UTM
junction_points = []
for jid in ROUTE_ORDER:
    x, y = JUNCTION_COORDS_UTM[jid]
    junction_points.append((x, y, jid))

# Bounds from junction coordinates plus padding for side streets
utmx_min = min(p[0] for p in junction_points) - 300
utmx_max = max(p[0] for p in junction_points) + 400
utmy_min = min(p[1] for p in junction_points) - 150
utmy_max = max(p[1] for p in junction_points) + 150
corridor_length = utmy_max - utmy_min

print(f'Corridor bounds (UTM): x=[{utmx_min:.0f}, {utmx_max:.0f}] y=[{utmy_min:.0f}, {utmy_max:.0f}]')
print(f'Approx corridor length: {corridor_length:.0f} m')

# Plot
fig, ax = plt.subplots(figsize=(6.5, 4.5), dpi=200)

# Clip to junction area
ax.set_xlim(utmx_min, utmx_max)
ax.set_ylim(utmy_min, utmy_max)

# Side streets in light gray
for geom in side_edges_utm.geometry:
    if geom is not None:
        ax.plot(*geom.coords.xy, color='#c0c0c0', linewidth=0.25, alpha=0.6, zorder=1)

# Kelvin Grove Road in red
for geom in kg_edges_utm.geometry:
    if geom is not None:
        ax.plot(*geom.coords.xy, color='#d62728', linewidth=1.8, alpha=0.9, zorder=3)

# Managed junctions with squares
xs_managed = [p[0] for p in junction_points]
ys_managed = [p[1] for p in junction_points]
ax.scatter(xs_managed, ys_managed, c='#ff7f0e', s=36, edgecolors='black',
           linewidth=0.6, zorder=5, marker='s', label='Managed junctions')

# Active junctions (excluding passive 38339, 39572 at north end)
active_filter = {36385, 36393, 39569, 39576, 39578, 39587, 39590, 39593, 39606, 1043762}
xs_active = [p[0] for p in junction_points if p[2] in active_filter]
ys_active = [p[1] for p in junction_points if p[2] in active_filter]
ax.scatter(xs_active, ys_active, c='#ff7f0e', s=40, edgecolors='#d62728',
           linewidth=1.0, zorder=6, marker='s',
           label=f'TSP-active ({len(active_filter)} junctions)')

# Junction labels
for jid in ROUTE_ORDER:
    x, y = JUNCTION_COORDS_UTM[jid]
    active = "A" if jid in active_filter else "P"
    ax.annotate(f'{jid}',
                xy=(x, y), xytext=(6, 4),
                textcoords='offset points', fontsize=5.5,
                color='#333333', ha='left', va='bottom', zorder=7)

# Corridor extent labels
north_jid = ROUTE_ORDER[0]
south_jid = ROUTE_ORDER[-1]
nx, ny = JUNCTION_COORDS_UTM[north_jid]
sx, sy = JUNCTION_COORDS_UTM[south_jid]
ax.annotate('North (Herston)',
            xy=(nx, ny), xytext=(15, 12),
            textcoords='offset points', fontsize=7, color='#d62728',
            ha='left', va='bottom',
            arrowprops=dict(arrowstyle='->', color='#d62728', lw=0.8))
ax.annotate('South (Normanby)',
            xy=(sx, sy), xytext=(15, -14),
            textcoords='offset points', fontsize=7, color='#d62728',
            ha='left', va='top',
            arrowprops=dict(arrowstyle='->', color='#d62728', lw=0.8))

# Scale bar
scale_len = 200
scale_x = utmx_min + 80
scale_y = utmy_min + 100
ax.plot([scale_x, scale_x + scale_len], [scale_y, scale_y],
        color='black', linewidth=2, zorder=10)
ax.text(scale_x + scale_len/2, scale_y - 25, '200 m',
        ha='center', va='top', fontsize=7, zorder=10)

# Styling
ax.set_aspect('auto')
ax.axis('off')

# Legend
legend_elements = [
    Line2D([0], [0], color='#d62728', lw=1.8, label='Kelvin Grove Rd'),
    Line2D([0], [0], color='#c0c0c0', lw=0.5, label='Side streets'),
    Line2D([0], [0], marker='s', color='w', markerfacecolor='#ff7f0e',
           markersize=7, markeredgecolor='black', markeredgewidth=0.6,
           label=f'TSP-active ({len(active_filter)} of {len(ROUTE_ORDER)} junctions)'),
]
ax.legend(handles=legend_elements, loc='lower right', fontsize=6, framealpha=0.9)

# Title
ax.set_title('Kelvin Grove Corridor, Brisbane — Aimsun Microsimulation Network\n'
             + f'{len(ROUTE_ORDER)} signalized junctions, {corridor_length:.0f} m corridor length',
             fontsize=9, fontweight='bold', pad=8)

plt.tight_layout(pad=0.3)

# Save
output_path = f'{OUTPUT_DIR}\\{OUTPUT_FILE}'
fig.savefig(output_path, format='png', bbox_inches=None, dpi=300)
print(f'\nSaved corridor map to: {output_path}')
plt.close(fig)
