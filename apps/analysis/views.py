"""
AI Query View — Chat-to-Map v5.0 "Mistral"

Nouveautés v5 :
- Intégration Mistral AI (mistral-small-latest) pour NLP de haute qualité
- Fallback automatique vers NLPEngine local si MISTRAL_API_KEY absent
- authentication_classes = [] → plus de blocage CSRF sur cet endpoint
- chart_data, fun_fact, suggestions, confidence conservés
- Structured output JSON depuis Mistral (response_format)
"""
import json
import time
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from .nlp_engine import (
    NLPEngine,
    FOREST_CENTERS,
    get_fun_fact,
    get_suggestions,
    compute_confidence,
)
from .models import RequeteNLP
from apps.carbone.serializers import OccupationSolSerializer

# ──────────────────────────────────────────────────────────────────────
# Mistral prompt système
# ──────────────────────────────────────────────────────────────────────
MISTRAL_SYSTEM = """Tu es un assistant géospatial expert en forêts classées du département d'Oumé (Côte d'Ivoire).
Tu analyses des requêtes en français et extrais des entités forestières.

Forêts disponibles : TENE, DOKA, SANGOUE, LAHOUDA, ZOUEKE_1, ZOUEKE_2
Années disponibles : 1986, 2003, 2023
Types de couverture : FORET_DENSE, FORET_CLAIRE, FORET_DEGRADEE, JACHERE, CACAO, CAFE, HEVEA, CULTURE_HERBACEE, SOL_NU
Intents possibles : show, stats, compare, deforestation, ranking, resume, stock_carbone, help

Règles de mapping des intents :
- "aide" / "bonjour" / "help" → help
- "résumé" / "synthèse" / "global" / "vue d'ensemble" → resume
- "compare" / "évolution" / "entre X et Y" / "changement" → compare
- "déforestation" / "perte" / "déboisement" / "destruction" → deforestation
- "classement" / "top" / "meilleur" / "le plus" / "ranking" → ranking
- "CO2" / "mode carbone" / "spatialisation carbone" / "activer carbone" → stock_carbone
- "superficie" / "statistiques" / "combien" / "données" → stats
- tout le reste (afficher polygones, "montre-moi", zones) → show

Pour l'intent "ranking", détermine ranking_by :
- "par carbone" / "stock" → carbone
- sinon → superficie

Réponds UNIQUEMENT avec un objet JSON valide, rien d'autre.
Exemple : {"forests":["TENE"],"years":[2023],"cover_types":["FORET_DENSE"],"intent":"show","ranking_by":"superficie"}
"""


def _parse_with_mistral(query: str) -> dict | None:
    """Appelle l'API Mistral et retourne le dict parsé, ou None si erreur."""
    api_key = getattr(settings, 'MISTRAL_API_KEY', '')
    if not api_key:
        return None

    try:
        from mistralai import Mistral  # import tardif pour ne pas bloquer si absent
        client = Mistral(api_key=api_key)
        resp = client.chat.complete(
            model='mistral-small-latest',
            messages=[
                {'role': 'system', 'content': MISTRAL_SYSTEM},
                {'role': 'user', 'content': query},
            ],
            response_format={'type': 'json_object'},
            temperature=0.0,
            max_tokens=256,
        )
        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw)

        # Validation et nettoyage
        valid_forests = {'TENE', 'DOKA', 'SANGOUE', 'LAHOUDA', 'ZOUEKE_1', 'ZOUEKE_2'}
        valid_years = {1986, 2003, 2023}
        valid_covers = {
            'FORET_DENSE', 'FORET_CLAIRE', 'FORET_DEGRADEE', 'JACHERE',
            'CACAO', 'CAFE', 'HEVEA', 'CULTURE_HERBACEE', 'SOL_NU',
        }
        valid_intents = {
            'show', 'stats', 'compare', 'deforestation',
            'ranking', 'resume', 'stock_carbone', 'help',
        }

        parsed = {
            'forests': [f for f in data.get('forests', []) if f in valid_forests],
            'years': sorted(set(y for y in data.get('years', []) if y in valid_years)),
            'cover_types': [c for c in data.get('cover_types', []) if c in valid_covers],
            'intent': data.get('intent', 'show') if data.get('intent') in valid_intents else 'show',
            'ranking_by': data.get('ranking_by', 'superficie'),
            'raw_query': query,
            '_inherited': [],
            '_explanation': '[Mistral AI]',
        }

        # Auto-complétion années pour comparaison/déforestation
        if parsed['intent'] in ('compare', 'deforestation') and len(parsed['years']) < 2:
            parsed['years'] = [1986, 2023]
            parsed['_explanation'] += ' Comparaison auto 1986→2023.'

        return parsed

    except Exception as exc:
        import logging
        logging.getLogger('analysis').warning('Mistral parse error: %s', exc)
        return None


class AIQueryView(APIView):
    """
    POST /api/v1/ai/query/
    Body: {"query": "texte en français"}

    Ordre de priorité :
      1. Mistral AI  (si MISTRAL_API_KEY configuré)
      2. NLPEngine local (fallback regex/fuzzy)
    """
    # Pas de SessionAuthentication → pas de vérification CSRF côté DRF
    authentication_classes = []
    permission_classes = [AllowAny]

    GEOJSON_LIMIT = 200

    def post(self, request):
        query = request.data.get('query', '').strip()
        if not query:
            return Response(
                {'error': 'Le champ "query" est requis.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(query) > 500:
            query = query[:500]

        start = time.time()

        # ── 1. Essai Mistral ──────────────────────────────────────────
        parsed = _parse_with_mistral(query)
        used_mistral = parsed is not None

        # ── 2. Fallback NLPEngine local ───────────────────────────────
        if parsed is None:
            engine = NLPEngine()
            parsed = engine.parse(query)
        else:
            engine = NLPEngine()  # gardé pour build_* helpers

        # ── Contexte conversationnel (session) ────────────────────────
        session_context = request.session.get('nlp_context', {})
        if parsed['intent'] != 'help':
            if not parsed['forests'] and session_context.get('forests'):
                parsed['forests'] = session_context['forests']
                parsed['_inherited'] = parsed.get('_inherited', []) + ['forests']
            if not parsed['years'] and session_context.get('years'):
                parsed['years'] = session_context['years']
                parsed['_inherited'] = parsed.get('_inherited', []) + ['years']
            if not parsed['cover_types'] and session_context.get('cover_types'):
                parsed['cover_types'] = session_context['cover_types']
                parsed['_inherited'] = parsed.get('_inherited', []) + ['cover_types']

            try:
                request.session['nlp_context'] = {
                    'forests': parsed['forests'],
                    'cover_types': parsed['cover_types'],
                    'years': parsed['years'],
                }
            except Exception:
                pass  # session non disponible (API sans cookies)

        nb_results = 0
        orm_desc = ''

        # ── Dispatch par intent ───────────────────────────────────────
        if parsed['intent'] == 'help':
            response_data = self._build_help(parsed)
            orm_desc = 'help'
            return self._finalize(request, query, parsed, response_data, 0, orm_desc, start, used_mistral)

        if parsed['intent'] == 'stock_carbone':
            response_data = {
                'type': 'stock_carbone',
                'parsed': parsed,
                'data': {
                    'message': (
                        'Activation du mode Stock Carbone (CO2) sur la carte. '
                        'Les 4 classes forestières sont affichées avec un gradient vert '
                        'proportionnel au stock de carbone (tCO₂/ha).'
                    ),
                    'action': 'activate_carbone_mode',
                },
            }
            return self._finalize(request, query, parsed, response_data, 4, 'stock_carbone', start, used_mistral)

        if parsed['intent'] == 'resume':
            resume = engine.build_resume(parsed)
            nb_results = len(resume.get('par_type', []))
            chart_data = self._build_chart_data(resume.get('par_type', []))
            response_data = {
                'type': 'resume',
                'parsed': parsed,
                'data': resume,
                'chart_data': chart_data,
            }
            return self._finalize(request, query, parsed, response_data, nb_results, f"resume {resume.get('annee', '?')}", start, used_mistral)

        if parsed['intent'] == 'compare' and len(parsed['years']) >= 2:
            comparison = engine.build_comparison(parsed)
            chart_data = self._build_comparison_chart(comparison) if comparison else None
            response_data = {
                'type': 'comparison',
                'parsed': parsed,
                'data': comparison,
                'chart_data': chart_data,
            }
            return self._finalize(request, query, parsed, response_data, 0, f"compare {parsed['years']}", start, used_mistral)

        if parsed['intent'] == 'deforestation' and len(parsed['years']) >= 2:
            deforestation = engine.build_deforestation(parsed)
            response_data = {
                'type': 'deforestation',
                'parsed': parsed,
                'data': deforestation,
            }
            return self._finalize(request, query, parsed, response_data, 0, f"deforestation {parsed['years']}", start, used_mistral)

        if parsed['intent'] in ('stats', 'carbon'):
            stats = list(engine.build_stats(parsed))
            nb_results = len(stats)
            if nb_results == 0:
                return self._no_results(request, query, parsed, engine, start, used_mistral)
            chart_data = self._build_chart_data(stats)
            response_data = {
                'type': 'stats',
                'parsed': parsed,
                'data': stats,
                'chart_data': chart_data,
            }
            return self._finalize(request, query, parsed, response_data, nb_results, f"stats {nb_results} types", start, used_mistral)

        if parsed['intent'] == 'ranking':
            ranking = engine.build_ranking(parsed)
            nb_results = len(ranking)
            response_data = {
                'type': 'ranking',
                'parsed': parsed,
                'data': ranking,
                'ranking_by': parsed.get('ranking_by', 'superficie'),
            }
            return self._finalize(request, query, parsed, response_data, nb_results, f"ranking {nb_results} forêts", start, used_mistral)

        # Default: show → GeoJSON
        qs = engine.build_queryset(parsed)
        count = qs.count()
        if count == 0:
            return self._no_results(request, query, parsed, engine, start, used_mistral)

        features = qs[:self.GEOJSON_LIMIT]
        serializer = OccupationSolSerializer(features, many=True)
        response_data = {
            'type': 'geojson',
            'parsed': parsed,
            'count': count,
            'displayed': min(count, self.GEOJSON_LIMIT),
            'truncated': count > self.GEOJSON_LIMIT,
            'data': serializer.data,
        }
        return self._finalize(request, query, parsed, response_data, count, f"geojson {count} features", start, used_mistral)

    # ──────────────────────────────────────────────────────────────────
    # Chart builders
    # ──────────────────────────────────────────────────────────────────
    def _build_chart_data(self, stats_list):
        if not stats_list:
            return None
        labels, sup_vals, carb_vals, colors = [], [], [], []
        for s in stats_list:
            labels.append(s.get('nomenclature__libelle_fr') or s.get('nomenclature__code', '?'))
            sup_vals.append(round(float(s.get('total_superficie_ha', 0)), 1))
            carb_vals.append(round(float(s.get('total_carbone', 0)), 1))
            colors.append(s.get('nomenclature__couleur_hex', '#999'))
        return {'labels': labels, 'colors': colors, 'superficie': sup_vals, 'carbone': carb_vals}

    def _build_comparison_chart(self, comparison):
        if not comparison:
            return None
        a1, a2 = comparison.get('annee1', {}), comparison.get('annee2', {})
        labels, values1, values2, colors = [], [], [], []
        map2 = {s.get('nomenclature__code'): round(float(s.get('superficie_ha', 0)), 1) for s in (a2.get('data') or [])}
        for s in (a1.get('data') or []):
            code = s.get('nomenclature__code', '')
            labels.append(s.get('nomenclature__libelle_fr', code))
            values1.append(round(float(s.get('superficie_ha', 0)), 1))
            values2.append(map2.get(code, 0))
            colors.append(s.get('nomenclature__couleur_hex', '#999'))
        return {'labels': labels, 'colors': colors, 'annee1': a1.get('annee'), 'values1': values1, 'annee2': a2.get('annee'), 'values2': values2}

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────
    def _build_help(self, parsed):
        return {
            'type': 'help',
            'parsed': parsed,
            'data': {
                'message': (
                    "Je suis l'assistant IA de la plateforme API.GEO.Carbone. "
                    "Je peux analyser les données forestières du département d'Oumé "
                    "(6 forêts classées, 3 années : 1986, 2003, 2023)."
                ),
                'examples': [
                    "Montre les zones de forêt dense à DOKA en 2003",
                    "Quelle est la superficie de forêt claire à SANGOUÉ ?",
                    "Compare TENÉ entre 1986 et 2023",
                    "Déforestation à LAHOUDA",
                    "Stock carbone pour 2023",
                    "Classement des forêts par carbone",
                    "Résumé global pour 2023",
                    "Active le mode CO2 sur la carte",
                ],
                'capabilities': [
                    "Afficher des couches sur la carte (forêt dense, claire, dégradée...)",
                    "Calculer des statistiques de superficie et stock carbone",
                    "Comparer l'évolution entre deux années (1986, 2003, 2023)",
                    "Analyser la déforestation (perte de couvert forestier)",
                    "Classer les forêts par superficie ou par carbone",
                    "Générer une synthèse globale (résumé)",
                    "Activer la spatialisation du stock carbone (mode CO2)",
                ],
                'forests': ['TENE', 'DOKA', 'SANGOUE', 'LAHOUDA', 'ZOUEKE_1', 'ZOUEKE_2'],
                'years': [1986, 2003, 2023],
            },
        }

    def _no_results(self, request, query, parsed, engine, start, used_mistral=False):
        suggestions = engine.suggest_queries(parsed)
        response_data = {'type': 'no_results', 'parsed': parsed, 'suggestions': suggestions, 'data': None}
        return self._finalize(request, query, parsed, response_data, 0, 'no_results', start, used_mistral)

    def _finalize(self, request, query, parsed, response_data, nb_results, orm_desc, start, used_mistral=False):
        processing_ms = int((time.time() - start) * 1000)
        response_data['processing_ms'] = processing_ms
        response_data['engine'] = 'mistral' if used_mistral else 'nlp_local'

        if parsed.get('_explanation'):
            response_data['explanation'] = parsed['_explanation'].strip()

        response_data['confidence'] = compute_confidence(parsed)
        response_data['fun_fact'] = get_fun_fact(
            parsed.get('intent', 'general'),
            parsed.get('cover_types', []),
        )

        session_ctx = {}
        try:
            session_ctx = request.session.get('nlp_context', {})
        except Exception:
            pass
        response_data['suggestions'] = get_suggestions(parsed, session_ctx)

        forests = parsed.get('forests', [])
        if forests:
            coords = [{'code': f, 'center': FOREST_CENTERS[f]} for f in forests if f in FOREST_CENTERS]
            if coords:
                response_data['coordinates'] = coords

        try:
            RequeteNLP.objects.create(
                texte_requete=query,
                entites_extraites=parsed,
                filtre_orm=orm_desc,
                nombre_resultats=nb_results,
                temps_traitement_ms=processing_ms,
            )
        except Exception:
            pass

        return Response(response_data)
