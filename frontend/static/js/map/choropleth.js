/**
 * Choropleth — MapLibre GL JS v5.0
 *
 * Remplace Leaflet GeoJSON par des sources/layers MapLibre.
 * L'update de données se fait via source.setData() — pas de recréation de layer.
 * → Transitions fluides, WebGL, 100k+ polygones sans lag.
 *
 * Sources MapLibre utilisées :
 *   occupation  — polygones d'occupation du sol (mis à jour sur changement d'année)
 *   forets      — limites des 6 forêts classées (statique)
 *   ai-results  — résultats de la requête IA (temporaire)
 */
const Choropleth = {
    _popup: null,   // popup singleton réutilisé
    _hoverPopup: null,

    EMPTY_FC: { type: 'FeatureCollection', features: [] },

    /**
     * Initialise les sources et layers MapLibre — appelé UNE SEULE FOIS au démarrage.
     * Les données sont vides au départ et remplies par renderOccupation / renderForets.
     */
    initSources(map) {
        // ── Source occupation (mise à jour fréquente) ──────────────
        map.addSource('occupation', { type: 'geojson', data: this.EMPTY_FC });
        map.addLayer({
            id: 'occupation-fill',
            type: 'fill',
            source: 'occupation',
            paint: {
                'fill-color': ['coalesce', ['get', 'couleur'], '#999999'],
                'fill-opacity': 0.68,
            },
        });
        map.addLayer({
            id: 'occupation-border',
            type: 'line',
            source: 'occupation',
            paint: {
                'line-color': '#44444466',
                'line-width': 0.4,
            },
        });

        // ── Source résultats IA ────────────────────────────────────
        map.addSource('ai-results', { type: 'geojson', data: this.EMPTY_FC });
        map.addLayer({
            id: 'occupation-ai-fill',
            type: 'fill',
            source: 'ai-results',
            paint: {
                'fill-color': ['coalesce', ['get', 'couleur'], '#ff6600'],
                'fill-opacity': 0.75,
            },
            layout: { visibility: 'none' },
        });
        map.addLayer({
            id: 'occupation-ai-border',
            type: 'line',
            source: 'ai-results',
            paint: { 'line-color': '#ff0000', 'line-width': 1.5 },
            layout: { visibility: 'none' },
        });

        // ── Source forêts (statique) ───────────────────────────────
        map.addSource('forets', { type: 'geojson', data: this.EMPTY_FC });
        // Remplissage transparent pour les clics
        map.addLayer({
            id: 'forets-fill',
            type: 'fill',
            source: 'forets',
            paint: { 'fill-color': '#1a5e1a', 'fill-opacity': 0.04 },
        });
        // Bordure en tirets verts
        map.addLayer({
            id: 'forets-border',
            type: 'line',
            source: 'forets',
            paint: {
                'line-color': '#1a5e1a',
                'line-width': 2.5,
                'line-dasharray': [6, 4],
                'line-opacity': 0.9,
            },
        });

        // ── Popups et hover ────────────────────────────────────────
        this._popup = new maplibregl.Popup({
            closeButton: true,
            maxWidth: '280px',
            className: 'geo-popup',
        });

        this._hoverPopup = new maplibregl.Popup({
            closeButton: false,
            closeOnClick: false,
            maxWidth: '200px',
            className: 'geo-hover-popup',
            offset: 8,
        });

        this._bindEvents(map);
    },

    /** Bind les events de clic et hover sur les layers occupation et forêts. */
    _bindEvents(map) {
        const self = this;

        // Clic sur occupation
        map.on('click', 'occupation-fill', (e) => {
            if (!e.features.length) return;
            const props = e.features[0].properties;
            self._popup
                .setLngLat(e.lngLat)
                .setHTML(PopupBuilder.occupation(props))
                .addTo(map);
        });

        // Clic sur résultats IA
        map.on('click', 'occupation-ai-fill', (e) => {
            if (!e.features.length) return;
            const props = e.features[0].properties;
            self._popup
                .setLngLat(e.lngLat)
                .setHTML(PopupBuilder.occupation(props))
                .addTo(map);
        });

        // Clic sur forêt
        map.on('click', 'forets-fill', (e) => {
            if (!e.features.length) return;
            // Éviter doublon si clic sur occupation (priorité à occupation)
            const occ = map.queryRenderedFeatures(e.point, { layers: ['occupation-fill'] });
            if (occ.length) return;
            const props = e.features[0].properties;
            self._popup
                .setLngLat(e.lngLat)
                .setHTML(PopupBuilder.foret(props))
                .addTo(map);
        });

        // Hover tooltip occupation
        map.on('mousemove', 'occupation-fill', (e) => {
            if (!e.features.length) return;
            map.getCanvas().style.cursor = 'pointer';
            const props = e.features[0].properties;
            const label = props.libelle || props.type_couvert || '';
            const foret = props.foret_nom || props.foret_code || '';
            if (label) {
                self._hoverPopup
                    .setLngLat(e.lngLat)
                    .setHTML(`<div class="text-xs font-semibold text-gray-800">${label}</div><div class="text-[10px] text-gray-500">${foret}</div>`)
                    .addTo(map);
            }
        });
        map.on('mouseleave', 'occupation-fill', () => {
            map.getCanvas().style.cursor = '';
            self._hoverPopup.remove();
        });

        // Hover tooltip forêt
        map.on('mousemove', 'forets-border', (e) => {
            const fs = map.queryRenderedFeatures(e.point, { layers: ['forets-fill'] });
            if (!fs.length) return;
            map.getCanvas().style.cursor = 'pointer';
            const nom = fs[0].properties.nom || fs[0].properties.code || '';
            if (nom) {
                self._hoverPopup
                    .setLngLat(e.lngLat)
                    .setHTML(`<div class="text-xs font-bold text-green-800">${nom}</div>`)
                    .addTo(map);
            }
        });
        map.on('mouseleave', 'forets-border', () => {
            map.getCanvas().style.cursor = '';
            self._hoverPopup.remove();
        });
    },

    /**
     * Met à jour les polygones d'occupation — appelé sur chaque changement d'année.
     * Via source.setData() : atomique, pas de flash, WebGL redessine le frame suivant.
     */
    renderOccupation(geojsonData, map) {
        if (!geojsonData) return;
        // Désactiver IA results
        if (map.getLayer('occupation-ai-fill')) map.setLayoutProperty('occupation-ai-fill', 'visibility', 'none');
        if (map.getLayer('occupation-ai-border')) map.setLayoutProperty('occupation-ai-border', 'visibility', 'none');
        // Mettre à jour l'occupation principale
        const src = map.getSource('occupation');
        if (src) src.setData(geojsonData);
        if (map.getLayer('occupation-fill')) map.setLayoutProperty('occupation-fill', 'visibility', 'visible');
        if (map.getLayer('occupation-border')) map.setLayoutProperty('occupation-border', 'visibility', 'visible');
    },

    clearOccupation(map) {
        const src = map.getSource('occupation');
        if (src) src.setData(this.EMPTY_FC);
    },

    /**
     * Initialise les limites des forêts classées — appelé UNE SEULE FOIS.
     */
    renderForets(geojsonData, map) {
        if (!geojsonData) return;
        const src = map.getSource('forets');
        if (src) src.setData(geojsonData);
    },

    /**
     * Mode stock carbone — affiche les 4 classes forestières avec gradient vert.
     * Réutilise la source occupation (setData atomatique).
     */
    renderStockCarbone(geojsonData, map) {
        if (!geojsonData) return;
        const src = map.getSource('occupation');
        if (src) src.setData(geojsonData);
        // Paint spécifique CO2 — couleur depuis la propriété 'couleur' du feature
        if (map.getLayer('occupation-fill')) {
            map.setPaintProperty('occupation-fill', 'fill-opacity', 0.78);
            map.setPaintProperty('occupation-border', 'line-color', '#0a2e0a');
            map.setPaintProperty('occupation-border', 'line-width', 0.7);
        }
        if (map.getLayer('occupation-ai-fill')) map.setLayoutProperty('occupation-ai-fill', 'visibility', 'none');
    },

    /**
     * Affiche les résultats d'une requête IA sur la carte.
     * Utilise la source ai-results distincte pour ne pas écraser l'occupation.
     */
    renderAIResults(geojsonData, map) {
        if (!geojsonData || !map) return;
        const src = map.getSource('ai-results');
        if (!src) return;
        src.setData(geojsonData);
        if (map.getLayer('occupation-ai-fill')) map.setLayoutProperty('occupation-ai-fill', 'visibility', 'visible');
        if (map.getLayer('occupation-ai-border')) map.setLayoutProperty('occupation-ai-border', 'visibility', 'visible');

        // Fly to bounds des résultats
        if (geojsonData.features?.length > 0) {
            const bounds = App._getBoundsFromGeoJSON(geojsonData);
            if (bounds) map.fitBounds(bounds, { padding: 60, duration: 1200, maxZoom: 13 });
        }
    },

    clearAIResults(map) {
        const src = map.getSource('ai-results');
        if (src) src.setData(this.EMPTY_FC);
        if (map.getLayer('occupation-ai-fill')) map.setLayoutProperty('occupation-ai-fill', 'visibility', 'none');
        if (map.getLayer('occupation-ai-border')) map.setLayoutProperty('occupation-ai-border', 'visibility', 'none');
    },

    /**
     * Restaure le style par défaut après mode carbone.
     */
    resetOccupationStyle(map) {
        if (map.getLayer('occupation-fill')) {
            map.setPaintProperty('occupation-fill', 'fill-opacity', 0.68);
        }
        if (map.getLayer('occupation-border')) {
            map.setPaintProperty('occupation-border', 'line-color', '#44444466');
            map.setPaintProperty('occupation-border', 'line-width', 0.4);
        }
    },
};
