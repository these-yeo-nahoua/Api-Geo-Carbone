"""
Pre-build static GeoJSON files for ultra-fast layer loading.

Instead of running heavy PostGIS simplification on every API request,
this command pre-generates simplified GeoJSON files ONCE and stores them
as static cache files. The API then serves these files directly with
near-instant response times (< 50ms vs 2-5 seconds).

Cache structure:
  media/geocache/
    occupations_1986.json         → all occupation year 1986
    occupations_2003.json         → all occupation year 2003
    occupations_2023.json         → all occupation year 2023
    occupations_1986_TENE.json    → occupation year 1986 filtered by TENE
    ...
    forets.json                   → all forest boundaries
    zones.json                    → all admin zones (incl. Oumé fallback)

Usage:
    python manage.py prebuild_geojson              # Build all
    python manage.py prebuild_geojson --year 2023  # Rebuild one year only
    python manage.py prebuild_geojson --clear      # Clear cache first
"""
import os
import json
import time

from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings

from apps.carbone.models import ForetClassee, ZoneEtude


# ====================================================================
# Simplification tolerance per layer (aggressive for static cache)
# These are optimized for map display at zoom 9-12 (typical overview)
# ====================================================================
TOLERANCES = {
    'occupation': 0.0006,  # ~66m accuracy (good for thematic maps)
    'forets': 0.0004,      # ~44m accuracy (preserve forest shapes)
    'zones': 0.0008,       # ~88m accuracy (admin boundaries)
}

# GeoJSON coordinate precision: 4 decimals ≈ 11m accuracy
GEOJSON_PRECISION = 4

CACHE_DIR = os.path.join(settings.MEDIA_ROOT, 'geocache')


class Command(BaseCommand):
    help = 'Pre-build static GeoJSON files for ultra-fast layer loading'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, help='Only rebuild this year')
        parser.add_argument('--clear', action='store_true', help='Clear cache before building')
        parser.add_argument(
            '--tolerance', type=float,
            help='Override simplification tolerance for occupation',
        )

    def handle(self, *args, **options):
        t0 = time.time()
        os.makedirs(CACHE_DIR, exist_ok=True)

        if options['clear']:
            # Préserver les fichiers générés par d'AUTRES commandes
            # (stock_carbone* vient de import_stock_carbone, pas du prebuild)
            preserve = ('stock_carbone',)
            for f in os.listdir(CACHE_DIR):
                if f.endswith('.json') and not f.startswith(preserve):
                    os.remove(os.path.join(CACHE_DIR, f))
            self.stdout.write(self.style.WARNING('Cache cleared (stock_carbone préservé)'))

        occ_tolerance = options.get('tolerance') or TOLERANCES['occupation']
        target_year = options.get('year')

        # 1. Ensure Oumé department boundary exists (fallback)
        self._ensure_department_boundary()

        # 2. Pre-build forest boundaries
        self._build_forets()

        # 3. Pre-build admin zones
        self._build_zones()

        # 4. Pre-build occupation data per year (and per year+forest)
        years = [target_year] if target_year else [1986, 2003, 2023]
        foret_codes = list(ForetClassee.objects.values_list('code', flat=True))

        for annee in years:
            # Full year (no forest filter)
            self._build_occupation(annee, None, occ_tolerance)
            # Per forest
            for code in foret_codes:
                self._build_occupation(annee, code, occ_tolerance)

        elapsed = round(time.time() - t0, 1)
        total_files = len([f for f in os.listdir(CACHE_DIR) if f.endswith('.json')])
        total_size = sum(
            os.path.getsize(os.path.join(CACHE_DIR, f))
            for f in os.listdir(CACHE_DIR) if f.endswith('.json')
        )
        total_mb = round(total_size / (1024 * 1024), 2)

        self.stdout.write(self.style.SUCCESS(
            f'\nOK Pre-build complete: {total_files} files, {total_mb} MB, {elapsed}s'
        ))

    def _save(self, filename, data):
        """Save GeoJSON dict to cache file."""
        path = os.path.join(CACHE_DIR, filename)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        size_kb = round(os.path.getsize(path) / 1024, 1)
        features = len(data.get('features', []))
        self.stdout.write(f'  OK {filename}: {features} features, {size_kb} KB')

    def _query_geojson(self, sql, params=None):
        """Execute SQL and return GeoJSON dict."""
        with connection.cursor() as cursor:
            cursor.execute(sql, params or [])
            row = cursor.fetchone()
            if row and row[0]:
                return row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return {'type': 'FeatureCollection', 'features': []}

    def _build_occupation(self, annee, foret_code, tolerance):
        """Build occupation GeoJSON for a specific year and optional forest."""
        conditions = ["o.annee = %s"]
        params = [annee]

        if foret_code:
            conditions.append("UPPER(f.code) = UPPER(%s)")
            params.append(foret_code)

        where = "WHERE " + " AND ".join(conditions)
        filename = f'occupations_{annee}' + (f'_{foret_code}' if foret_code else '') + '.json'

        sql = f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(feat), '[]'::json)
        )
        FROM (
            SELECT json_build_object(
                'type', 'Feature',
                'id', o.id,
                'geometry', ST_AsGeoJSON(
                    ST_SimplifyPreserveTopology(
                        ST_MakeValid(o.geom), {tolerance}
                    ), {GEOJSON_PRECISION}
                )::json,
                'properties', json_build_object(
                    'id', o.id,
                    'foret_code', f.code,
                    'foret_nom', f.nom,
                    'type_couvert', n.code,
                    'libelle', n.libelle_fr,
                    'couleur', n.couleur_hex,
                    'annee', o.annee,
                    'superficie_ha', ROUND(o.superficie_ha::numeric, 2),
                    'stock_carbone_calcule', ROUND(o.stock_carbone_calcule::numeric, 2),
                    'source_donnee', o.source_donnee
                )
            ) AS feat
            FROM carbone_occupationsol o
            JOIN carbone_foretclassee f ON o.foret_id = f.id
            JOIN carbone_nomenclaturecouvert n ON o.nomenclature_id = n.id
            {where}
            ORDER BY n.ordre_affichage, o.id
        ) sub;
        """
        data = self._query_geojson(sql, params)
        self._save(filename, data)

    def _build_forets(self):
        """Build forest boundaries GeoJSON."""
        tolerance = TOLERANCES['forets']
        sql = f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(feat), '[]'::json)
        )
        FROM (
            SELECT json_build_object(
                'type', 'Feature',
                'id', f.id,
                'geometry', ST_AsGeoJSON(
                    ST_SimplifyPreserveTopology(
                        ST_MakeValid(f.geom), {tolerance}
                    ), {GEOJSON_PRECISION}
                )::json,
                'properties', json_build_object(
                    'id', f.id,
                    'code', f.code,
                    'nom', f.nom,
                    'superficie_legale_ha', f.superficie_legale_ha,
                    'statut_juridique', f.statut_juridique,
                    'autorite_gestion', f.autorite_gestion
                )
            ) AS feat
            FROM carbone_foretclassee f
            ORDER BY f.code
        ) sub;
        """
        data = self._query_geojson(sql)
        self._save('forets.json', data)

    def _build_zones(self):
        """Build admin zones GeoJSON."""
        tolerance = TOLERANCES['zones']
        sql = f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(feat), '[]'::json)
        )
        FROM (
            SELECT json_build_object(
                'type', 'Feature',
                'id', z.id,
                'geometry', ST_AsGeoJSON(
                    ST_SimplifyPreserveTopology(
                        ST_MakeValid(z.geom), {tolerance}
                    ), {GEOJSON_PRECISION}
                )::json,
                'properties', json_build_object(
                    'id', z.id,
                    'nom', z.nom,
                    'type_zone', z.type_zone,
                    'niveau', z.niveau
                )
            ) AS feat
            FROM carbone_zoneetude z
            ORDER BY z.niveau, z.nom
        ) sub;
        """
        data = self._query_geojson(sql)
        self._save('zones.json', data)

    def _ensure_department_boundary(self):
        """Auto-generate Oumé department boundary if missing."""
        if ZoneEtude.objects.filter(type_zone='DEPARTEMENT').exists():
            return

        if not ForetClassee.objects.exists():
            self.stdout.write(self.style.WARNING('  No forests to generate fallback boundary'))
            return

        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO carbone_zoneetude (nom, type_zone, niveau, geom, created_at, updated_at)
                    SELECT
                        'Département d''Oumé' AS nom,
                        'DEPARTEMENT' AS type_zone,
                        1 AS niveau,
                        ST_Multi(
                            ST_Buffer(
                                ST_ConvexHull(ST_Collect(geom)),
                                0.02
                            )
                        ) AS geom,
                        NOW() AS created_at,
                        NOW() AS updated_at
                    FROM carbone_foretclassee
                    WHERE NOT EXISTS (
                        SELECT 1 FROM carbone_zoneetude
                        WHERE type_zone = 'DEPARTEMENT'
                    );
                """)
            self.stdout.write(self.style.SUCCESS(
                '  OK Département d\'Oumé: generated (fallback from forest hull)'
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  Fallback error: {e}'))
