"""
API Views — Ultra-fast layer loading via static GeoJSON cache + SQL fallback.

Performance architecture (2 tiers):

  TIER 1 — Static GeoJSON cache (< 50ms response)
  Pre-generated files in media/geocache/ built by `manage.py prebuild_geojson`.
  Served as FileResponse with proper Content-Type and cache headers.
  Used for standard year/forest combinations.

  TIER 2 — Dynamic SQL fallback (200-3000ms response)
  Raw PostGIS query with adaptive simplification.
  Used when no cached file exists or for dynamic filters (bbox, zoom, type).
  Features ST_MakeValid, adaptive tolerance, viewport bbox filtering.
"""
import os
import json
from django.db import connection
from django.http import JsonResponse, FileResponse
from django.conf import settings
from django.utils.http import http_date
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Count
from django_filters.rest_framework import DjangoFilterBackend

GEOCACHE_DIR = os.path.join(settings.MEDIA_ROOT, 'geocache')

from .models import (
    ZoneEtude, ForetClassee, NomenclatureCouvert,
    OccupationSol, Placette, Infrastructure,
)
from .serializers import (
    ZoneEtudeSerializer, ForetClasseeSerializer, ForetClasseeListSerializer,
    NomenclatureCouvertSerializer, OccupationSolSerializer,
    OccupationSolWriteSerializer, PlacetteSerializer,
    InfrastructureSerializer,
)
from .filters import OccupationSolFilter, PlacetteFilter, InfrastructureFilter, ZoneEtudeFilter


# ================================================================
# Adaptive simplification tolerance based on zoom level
# ================================================================
SIMPLIFY_TOLERANCE = {
    # zoom_level: tolerance (degrees). Lower zoom = more aggressive simplification
    # Optimized for heavy polygons (100K-800K vertices from Sentinel 2023 data)
    'occupation': {
        7: 0.01, 8: 0.005, 9: 0.003, 10: 0.002,
        11: 0.001, 12: 0.0008, 13: 0.0005, 14: 0.0003,
    },
    'forets': {
        7: 0.005, 8: 0.003, 9: 0.002, 10: 0.001,
        11: 0.0005, 12: 0.0003, 13: 0.0002,
    },
    'zones': {
        7: 0.005, 8: 0.003, 9: 0.002, 10: 0.001,
        11: 0.0008, 12: 0.0005,
    },
}


def _get_tolerance(layer_type, zoom):
    """Return simplification tolerance for a given layer and zoom level."""
    tolerances = SIMPLIFY_TOLERANCE.get(layer_type, {})
    if zoom is None:
        # Default fallback
        defaults = {'occupation': 0.0008, 'forets': 0.0005, 'zones': 0.001}
        return defaults.get(layer_type, 0.001)
    zoom = int(zoom)
    # Find closest zoom level (clamp to available range)
    levels = sorted(tolerances.keys())
    if not levels:
        return 0.001
    if zoom <= levels[0]:
        return tolerances[levels[0]]
    if zoom >= levels[-1]:
        return tolerances[levels[-1]]
    # Find nearest
    for i, lvl in enumerate(levels):
        if zoom <= lvl:
            return tolerances[lvl]
    return tolerances[levels[-1]]


# ================================================================
# Helper: Execute raw SQL and return GeoJSON FeatureCollection
# ================================================================
def _raw_geojson(sql, params=None):
    """Execute SQL that returns a single JSON column → return as JsonResponse."""
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
        if row and row[0]:
            return JsonResponse(row[0], safe=False, json_dumps_params={'ensure_ascii': False})
    # Empty result
    return JsonResponse({
        'type': 'FeatureCollection',
        'features': [],
    })


def _parse_bbox(bbox_str):
    """Parse 'west,south,east,north' string → tuple of 4 floats, or None."""
    if not bbox_str:
        return None
    try:
        parts = [float(x) for x in bbox_str.split(',')]
        if len(parts) == 4:
            return tuple(parts)
    except (ValueError, TypeError):
        pass
    return None


def _serve_cached(filename):
    """
    Serve a pre-built GeoJSON file from media/geocache/ as FileResponse.
    Returns None if file doesn't exist (caller should fall back to SQL).

    Caching strategy — freshness WITHOUT losing speed:
      - Last-Modified is set from the file's mtime.
      - Cache-Control: no-cache forces the browser to revalidate each time.
      - Combined with ConditionalGetMiddleware, an unchanged file returns a
        tiny 304 (~10-30ms); a rebuilt file (new mtime) returns fresh 200 data.
      This avoids the classic "stale data for 1h after a rebuild" trap while
      keeping repeat loads fast.
    """
    path = os.path.join(GEOCACHE_DIR, filename)
    if os.path.isfile(path):
        response = FileResponse(
            open(path, 'rb'),
            content_type='application/json',
        )
        response['Last-Modified'] = http_date(os.path.getmtime(path))
        response['Cache-Control'] = 'no-cache'
        response['X-GeoCache'] = 'HIT'
        return response
    return None


# ================================================================
# Occupation du sol — THE heavy endpoint (thousands of polygons)
# ================================================================
class OccupationSolViewSet(viewsets.ModelViewSet):
    serializer_class = OccupationSolSerializer
    filterset_class = OccupationSolFilter
    filter_backends = [DjangoFilterBackend]
    pagination_class = None

    def get_queryset(self):
        return OccupationSol.objects.select_related('foret', 'nomenclature')

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return OccupationSolWriteSerializer
        return OccupationSolSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAdminUser()]
        return [permissions.AllowAny()]

    def list(self, request, *args, **kwargs):
        """
        Ultra-fast layer loading: static cache → SQL fallback.

        TIER 1: If a pre-built GeoJSON file exists for this year+forest,
        serve it as a static file (< 50ms, gzipped by middleware).

        TIER 2: Otherwise, run PostGIS query with adaptive simplification.
        """
        annee = request.query_params.get('annee')
        foret_code = request.query_params.get('foret_code')
        foret_id = request.query_params.get('foret')
        type_code = request.query_params.get('type')
        zoom = request.query_params.get('zoom')
        bbox = _parse_bbox(request.query_params.get('bbox'))

        # ── TIER 1: Try static cache (only for simple year/forest queries) ──
        if annee and not type_code and not bbox and not foret_id:
            cache_name = f'occupations_{annee}'
            if foret_code:
                cache_name += f'_{foret_code.upper()}'
            cache_name += '.json'
            cached = _serve_cached(cache_name)
            if cached:
                return cached

        # ── TIER 2: Dynamic SQL fallback ──
        tolerance = _get_tolerance('occupation', zoom)

        conditions = []
        params = []

        if annee:
            conditions.append("o.annee = %s")
            params.append(int(annee))
        if foret_code:
            conditions.append("UPPER(f.code) = UPPER(%s)")
            params.append(foret_code)
        if foret_id:
            conditions.append("o.foret_id = %s")
            params.append(int(foret_id))
        if type_code:
            conditions.append("UPPER(n.code) = UPPER(%s)")
            params.append(type_code)
        if bbox:
            conditions.append(
                "o.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)"
            )
            params.extend(bbox)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

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
                    ST_SimplifyPreserveTopology(ST_MakeValid(o.geom), {tolerance}), 4
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
        return _raw_geojson(sql, params)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Statistiques agregees par type de couvert pour une foret/annee."""
        annee = request.query_params.get('annee')
        foret_code = request.query_params.get('foret')

        qs = OccupationSol.objects.all()
        if annee:
            qs = qs.filter(annee=int(annee))
        if foret_code:
            qs = qs.filter(foret__code__iexact=foret_code)

        stats = qs.values(
            'nomenclature__code',
            'nomenclature__libelle_fr',
            'nomenclature__couleur_hex',
        ).annotate(
            total_superficie_ha=Sum('superficie_ha'),
            total_carbone=Sum('stock_carbone_calcule'),
            nombre_polygones=Count('id'),
        ).order_by('nomenclature__ordre_affichage')

        totaux = qs.aggregate(
            superficie_totale=Sum('superficie_ha'),
            carbone_total=Sum('stock_carbone_calcule'),
        )

        return Response({
            'annee': annee,
            'foret': foret_code,
            'resultats': list(stats),
            'totaux': {
                'superficie_ha': totaux['superficie_totale'] or 0,
                'carbone_tco2': totaux['carbone_total'] or 0,
            },
        })

    @action(detail=False, methods=['get'])
    def evolution(self, request):
        """Evolution temporelle d'une foret entre deux annees."""
        foret_code = request.query_params.get('foret')
        annee1 = request.query_params.get('annee1')
        annee2 = request.query_params.get('annee2')

        if not all([foret_code, annee1, annee2]):
            return Response(
                {'error': 'Parametres requis: foret, annee1, annee2'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        def get_stats(annee):
            return OccupationSol.objects.filter(
                foret__code__iexact=foret_code,
                annee=int(annee),
            ).values(
                'nomenclature__code',
                'nomenclature__libelle_fr',
                'nomenclature__couleur_hex',
            ).annotate(
                superficie_ha=Sum('superficie_ha'),
                carbone=Sum('stock_carbone_calcule'),
            ).order_by('nomenclature__ordre_affichage')

        return Response({
            'foret': foret_code,
            'annee1': {'annee': annee1, 'data': list(get_stats(annee1))},
            'annee2': {'annee': annee2, 'data': list(get_stats(annee2))},
        })


# ================================================================
# Forêts classées — 6 records only, but geometries can be complex
# ================================================================
class ForetClasseeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ForetClassee.objects.all()
    serializer_class = ForetClasseeSerializer
    pagination_class = None

    def list(self, request, *args, **kwargs):
        """Forest boundaries: static cache → SQL fallback."""
        # TIER 1: Try cache
        cached = _serve_cached('forets.json')
        if cached:
            return cached

        # TIER 2: Dynamic SQL
        zoom = request.query_params.get('zoom')
        tolerance = _get_tolerance('forets', zoom)

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
                    ST_SimplifyPreserveTopology(ST_MakeValid(f.geom), {tolerance}), 4
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
        return _raw_geojson(sql)

    @action(detail=False, methods=['get'])
    def liste(self, request):
        """Liste legere des forets sans geometrie."""
        qs = ForetClassee.objects.all()
        serializer = ForetClasseeListSerializer(qs, many=True)
        return Response(serializer.data)


# ================================================================
# Zones d'étude — limites administratives
# ================================================================
class ZoneEtudeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ZoneEtude.objects.all()
    serializer_class = ZoneEtudeSerializer
    filterset_class = ZoneEtudeFilter
    pagination_class = None

    def list(self, request, *args, **kwargs):
        """
        Admin boundaries: static cache → SQL fallback.
        Auto-generates Oumé department boundary if missing.
        """
        type_zone = request.query_params.get('type')
        niveau = request.query_params.get('niveau')
        zoom = request.query_params.get('zoom')
        tolerance = _get_tolerance('zones', zoom)

        # Auto-generate Oumé department boundary if missing
        self._ensure_department_boundary()

        # TIER 1: Try cache (only for unfiltered requests)
        if not type_zone and not niveau:
            cached = _serve_cached('zones.json')
            if cached:
                return cached

        # TIER 2: Dynamic SQL
        conditions = []
        params = []
        if type_zone:
            conditions.append("UPPER(z.type_zone) = UPPER(%s)")
            params.append(type_zone)
        if niveau:
            conditions.append("z.niveau = %s")
            params.append(int(niveau))

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

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
                    ST_SimplifyPreserveTopology(ST_MakeValid(z.geom), {tolerance}), 4
                )::json,
                'properties', json_build_object(
                    'id', z.id,
                    'nom', z.nom,
                    'type_zone', z.type_zone,
                    'niveau', z.niveau
                )
            ) AS feat
            FROM carbone_zoneetude z
            {where}
            ORDER BY z.niveau, z.nom
        ) sub;
        """
        return _raw_geojson(sql, params)

    def _ensure_department_boundary(self):
        """
        If no DEPARTEMENT zone exists, generate one automatically
        from the convex hull of all forest boundaries + 2km buffer.
        This ensures the Oumé department always appears on the map.
        """
        if ZoneEtude.objects.filter(type_zone='DEPARTEMENT').exists():
            return

        # Check if we have any forests to derive boundary from
        if not ForetClassee.objects.exists():
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
        except Exception:
            pass


# ================================================================
# Infrastructures — routes, hydrographie, localités
# ================================================================
class InfrastructureViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Infrastructure.objects.all()
    serializer_class = InfrastructureSerializer
    filterset_class = InfrastructureFilter
    pagination_class = None

    def list(self, request, *args, **kwargs):
        """Raw SQL with geometry simplification for lines/points."""
        type_infra = request.query_params.get('type')

        conditions = []
        params = []
        if type_infra:
            conditions.append("UPPER(i.type_infra) = UPPER(%s)")
            params.append(type_infra)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        sql = f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(feat), '[]'::json)
        )
        FROM (
            SELECT json_build_object(
                'type', 'Feature',
                'id', i.id,
                'geometry', ST_AsGeoJSON(
                    CASE
                        WHEN GeometryType(i.geom) IN ('LINESTRING','MULTILINESTRING')
                        THEN ST_Simplify(i.geom, 0.0005)
                        ELSE i.geom
                    END,
                    5
                )::json,
                'properties', json_build_object(
                    'id', i.id,
                    'type_infra', i.type_infra,
                    'nom', i.nom,
                    'categorie', i.categorie
                )
            ) AS feat
            FROM carbone_infrastructure i
            {where}
            ORDER BY i.type_infra, i.nom
        ) sub;
        """
        return _raw_geojson(sql, params)


# ================================================================
# Lightweight viewsets (no geometry optimization needed)
# ================================================================
# ================================================================
# Stock Carbone — static GeoJSON from geocache (2023 data)
# ================================================================
def stock_carbone_geojson(request):
    """
    Serve the pre-built carbon stock spatialization GeoJSON (2023).
    TIER 1 only: static file from geocache (no SQL fallback needed,
    since data comes from external shapefile, not the database).
    """
    cached = _serve_cached('stock_carbone.json')
    if cached:
        return cached
    return JsonResponse(
        {'error': 'Stock carbone data not available. Run: manage.py import_stock_carbone'},
        status=404,
    )


class NomenclatureCouvertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = NomenclatureCouvert.objects.all()
    serializer_class = NomenclatureCouvertSerializer
    pagination_class = None


class PlacetteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Placette.objects.select_related('foret').all()
    serializer_class = PlacetteSerializer
    filterset_class = PlacetteFilter
    pagination_class = None
