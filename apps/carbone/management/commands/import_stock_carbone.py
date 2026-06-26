"""
Import carbon stock spatialization shapefile -> static GeoJSON cache.

Reads data_carb.shp (UTM Zone 30N), simplifies in UTM space (fast),
reprojects to WGS84, and writes media/geocache/stock_carbone.json.

Usage:
    python manage.py import_stock_carbone --shapefile "path/to/data_carb.shp"
    python manage.py import_stock_carbone --shapefile "path/to/data_carb.shp" --tolerance 200
"""
import os
import json
import geopandas as gpd
from shapely.validation import make_valid
from shapely.geometry import Polygon, MultiPolygon
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.carbone.constants import (
    STOCK_CARBONE_CLASS_MAP,
    STOCK_CARBONE_COLORS,
    NOMENCLATURE_DATA,
    STOCK_CARBONE_REFERENCE,
)


# ---------------------------------------------------------------------------
# Lissage Chaikin (corner-cutting) — transforme les bords anguleux/pixelisés
# en courbes lisses par interpolation des sommets. Équivalent shapely de
# ST_ChaikinSmoothing (utilisé pour l'occupation côté PostGIS).
# ---------------------------------------------------------------------------
def _chaikin_ring(coords, iterations):
    pts = [(float(x), float(y)) for x, y in coords]
    for _ in range(iterations):
        new = []
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            new.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            new.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        if new:
            new.append(new[0])  # refermer l'anneau
        pts = new
    return pts


def _chaikin_polygon(poly, iterations):
    ext = _chaikin_ring(poly.exterior.coords, iterations)
    holes = [_chaikin_ring(r.coords, iterations) for r in poly.interiors]
    return Polygon(ext, holes)


def chaikin_smooth(geom, iterations=2):
    """Lisse un Polygon / MultiPolygon par corner-cutting de Chaikin."""
    try:
        if geom.geom_type == 'Polygon':
            return _chaikin_polygon(geom, iterations)
        if geom.geom_type == 'MultiPolygon':
            return MultiPolygon([_chaikin_polygon(p, iterations) for p in geom.geoms])
    except Exception:
        pass
    return geom


class Command(BaseCommand):
    help = 'Import carbon stock shapefile and generate geocache GeoJSON'

    def add_arguments(self, parser):
        parser.add_argument(
            '--shapefile', required=True,
            help='Path to data_carb.shp',
        )
        parser.add_argument(
            '--tolerance', type=float, default=100,
            help='Simplification tolerance in meters (UTM, default: 100m — base grossière puis lissée par Chaikin)',
        )
        parser.add_argument(
            '--output', default=None,
            help='Output path (default: media/geocache/stock_carbone.json)',
        )

    def handle(self, *args, **options):
        shapefile_path = options['shapefile']
        tolerance = options['tolerance']
        output_path = options['output'] or os.path.join(
            settings.MEDIA_ROOT, 'geocache', 'stock_carbone.json'
        )

        if not os.path.isfile(shapefile_path):
            self.stderr.write(self.style.ERROR(
                'Shapefile not found: %s' % shapefile_path
            ))
            return

        # -- Step 1: Read shapefile --
        self.stdout.write('Reading shapefile: %s' % shapefile_path)
        gdf = gpd.read_file(shapefile_path)
        self.stdout.write('  %d features' % len(gdf))

        # -- Step 2: Ensure projected CRS for area + simplification --
        if gdf.crs and gdf.crs.is_geographic:
            gdf = gdf.to_crs(epsg=32630)

        # Compute areas BEFORE simplification (more accurate)
        self.stdout.write('Computing areas...')
        gdf['superficie_ha'] = gdf.geometry.area / 10000.0

        # -- Step 3: Simplify in UTM (meters) PUIS lissage Chaikin --
        # preserve_topology=False (Douglas-Peucker) rapide et O(n log n) ;
        # preserve_topology=True se fige sur ces géométries massives.
        # On simplifie grossièrement (réduit les vertex + le bruit pixel), PUIS
        # ST_Chaikin arrondit les coins en courbes lisses (fin du triangulaire).
        self.stdout.write('Simplifying (tolerance=%sm, Douglas-Peucker)...' % int(tolerance))
        gdf['geometry'] = gdf.geometry.simplify(tolerance, preserve_topology=False)
        self.stdout.write('  Lissage Chaikin (interpolation des sommets)...')
        gdf['geometry'] = gdf.geometry.apply(lambda g: chaikin_smooth(g, 2))
        self.stdout.write('  Validating...')
        gdf['geometry'] = gdf.geometry.apply(make_valid)
        self.stdout.write('  Done.')

        # -- Step 4: Reproject to WGS84 --
        self.stdout.write('Reprojecting to WGS84...')
        gdf = gdf.to_crs(epsg=4326)

        # -- Step 5: Build nomenclature lookup --
        nomenclature_lookup = {}
        for item in NOMENCLATURE_DATA:
            nomenclature_lookup[item['code']] = item['libelle_fr']

        # -- Step 6: Build GeoJSON features --
        self.stdout.write('Building GeoJSON...')
        features = []
        for idx, row in gdf.iterrows():
            class_id = int(row.get('Class_Id') or row.get('class_id') or 0)
            class_code = STOCK_CARBONE_CLASS_MAP.get(class_id)

            if not class_code:
                self.stdout.write(self.style.WARNING(
                    '  Skip Class_Id=%d' % class_id
                ))
                continue

            libelle = nomenclature_lookup.get(class_code, class_code)
            couleur = STOCK_CARBONE_COLORS.get(class_code, '#228B22')
            stock_ref = STOCK_CARBONE_REFERENCE.get(class_code, 0)

            # Geometry to GeoJSON dict
            geom = json.loads(
                gpd.GeoSeries([row['geometry']], crs='EPSG:4326').to_json()
            )['features'][0]['geometry']

            features.append({
                'type': 'Feature',
                'id': class_id,
                'geometry': geom,
                'properties': {
                    'class_code': class_code,
                    'libelle': libelle,
                    'annee': 2023,
                    'stock_tco2_ha': stock_ref,
                    'couleur': couleur,
                    'superficie_ha': round(row['superficie_ha'], 2),
                },
            })

            self.stdout.write('  [OK] %s: %s (%.0f ha)' % (
                class_code, libelle, row['superficie_ha']
            ))

        # -- Step 7: Write GeoJSON --
        geojson = {'type': 'FeatureCollection', 'features': features}
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(geojson, f, ensure_ascii=False, separators=(',', ':'))

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(
            'Generated %s (%.2f MB, %d features)' % (
                output_path, size_mb, len(features)
            )
        ))
