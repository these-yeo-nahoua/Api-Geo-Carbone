"""
Permanently simplify heavy geometries in the database.

Problem: Some polygons have 500,000-800,000 vertices (imported from very
detailed 2023 shapefiles). This makes EVERY query slow because PostGIS
must simplify these massive geometries on every request.

Solution: Run ST_SimplifyPreserveTopology ONCE and UPDATE the geometry
permanently. This is safe because the map display doesn't need sub-meter
precision. The original shapefile remains as the reference.

Threshold: Only simplify polygons with more than 10,000 vertices.
Tolerance: 0.0003 degrees (~33m) — preserves all visible detail on a map.

Usage:
    python manage.py simplify_geometries              # Preview (dry run)
    python manage.py simplify_geometries --apply       # Apply permanently
    python manage.py simplify_geometries --apply --tolerance 0.0005  # More aggressive
"""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Permanently simplify heavy geometries in the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually update geometries (default is dry run)',
        )
        parser.add_argument(
            '--tolerance', type=float, default=0.0003,
            help='Simplification tolerance in degrees (default: 0.0003 ~ 33m)',
        )
        parser.add_argument(
            '--threshold', type=int, default=10000,
            help='Only simplify polygons with more vertices than this (default: 10000)',
        )

    def handle(self, *args, **options):
        apply = options['apply']
        tolerance = options['tolerance']
        threshold = options['threshold']

        self.stdout.write(f'Tolerance: {tolerance} degrees (~{int(tolerance * 111000)}m)')
        self.stdout.write(f'Threshold: {threshold} vertices')
        self.stdout.write(f'Mode: {"APPLY" if apply else "DRY RUN (preview)"}')
        self.stdout.write('')

        # 1. Show current state
        self.stdout.write('=== Current state ===')
        with connection.cursor() as c:
            c.execute("""
                SELECT annee, COUNT(*),
                       SUM(ST_NPoints(geom)) as total_points,
                       MAX(ST_NPoints(geom)) as max_points,
                       AVG(ST_NPoints(geom))::int as avg_points
                FROM carbone_occupationsol
                GROUP BY annee ORDER BY annee
            """)
            for row in c.fetchall():
                self.stdout.write(
                    f'  Year {row[0]}: {row[1]} polygons, '
                    f'total={row[2]:,} pts, max={row[3]:,} pts, avg={row[4]:,} pts'
                )

        # 2. Count polygons that would be simplified
        with connection.cursor() as c:
            c.execute("""
                SELECT COUNT(*), SUM(ST_NPoints(geom)) as before_points,
                       SUM(ST_NPoints(ST_Simplify(geom, %s))) as after_points
                FROM carbone_occupationsol
                WHERE ST_NPoints(geom) > %s
            """, [tolerance, threshold])
            row = c.fetchone()
            count, before, after = row[0], row[1] or 0, row[2] or 0
            reduction = round((1 - after / before) * 100, 1) if before > 0 else 0

        self.stdout.write('')
        self.stdout.write(f'=== Simplification preview ===')
        self.stdout.write(f'  Polygons to simplify: {count}')
        self.stdout.write(f'  Before: {before:,} vertices')
        self.stdout.write(f'  After:  {after:,} vertices')
        self.stdout.write(f'  Reduction: {reduction}%')

        if not apply:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'DRY RUN. Run with --apply to update geometries permanently.'
            ))
            return

        # 3. Apply simplification
        self.stdout.write('')
        self.stdout.write('Applying simplification...')
        with connection.cursor() as c:
            c.execute("""
                UPDATE carbone_occupationsol
                SET geom = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Simplify(geom, %s)), 3))
                WHERE ST_NPoints(geom) > %s
            """, [tolerance, threshold])
            updated = c.rowcount

        # 4. Also simplify forest boundaries
        with connection.cursor() as c:
            c.execute("""
                UPDATE carbone_foretclassee
                SET geom = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Simplify(geom, %s)), 3))
                WHERE ST_NPoints(geom) > %s
            """, [tolerance * 0.8, threshold])
            updated_forets = c.rowcount

        # 5. Also simplify zone boundaries
        with connection.cursor() as c:
            c.execute("""
                UPDATE carbone_zoneetude
                SET geom = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Simplify(geom, %s)), 3))
                WHERE ST_NPoints(geom) > %s
            """, [tolerance, threshold])
            updated_zones = c.rowcount

        # 6. VACUUM ANALYZE to reclaim space
        self.stdout.write('Running VACUUM ANALYZE...')
        old_isolation = connection.isolation_level
        connection.isolation_level = 0
        with connection.cursor() as c:
            c.execute('VACUUM ANALYZE carbone_occupationsol')
            c.execute('VACUUM ANALYZE carbone_foretclassee')
            c.execute('VACUUM ANALYZE carbone_zoneetude')
        connection.isolation_level = old_isolation

        # 7. Show final state
        self.stdout.write('')
        self.stdout.write('=== Final state ===')
        with connection.cursor() as c:
            c.execute("""
                SELECT annee, COUNT(*),
                       SUM(ST_NPoints(geom)) as total_points,
                       MAX(ST_NPoints(geom)) as max_points,
                       AVG(ST_NPoints(geom))::int as avg_points
                FROM carbone_occupationsol
                GROUP BY annee ORDER BY annee
            """)
            for row in c.fetchall():
                self.stdout.write(
                    f'  Year {row[0]}: {row[1]} polygons, '
                    f'total={row[2]:,} pts, max={row[3]:,} pts, avg={row[4]:,} pts'
                )

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done! Updated: {updated} occupations, '
            f'{updated_forets} forets, {updated_zones} zones'
        ))
