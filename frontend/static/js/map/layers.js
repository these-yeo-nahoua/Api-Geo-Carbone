/**
 * Layer Manager — MapLibre GL JS v5.0
 *
 * Gère :
 *   - Fond de carte (OSM / Satellite / Terrain) → toggle visibility
 *   - Couches overlay (limites, placettes, routes, hydro, localités) → sources/layers MapLibre
 *   - Lazy loading : charge uniquement au clic sur la checkbox
 */
const LayerManager = {
    map: null,
    loadedOverlays: new Set(),
    _loadingOverlays: new Set(),

    EMPTY_FC: { type: 'FeatureCollection', features: [] },

    init(map) {
        this.map = map;
        this.bindEvents();
    },

    bindEvents() {
        // Basemap radio buttons
        document.querySelectorAll('input[name="baseLayer"]').forEach(radio => {
            radio.addEventListener('change', (e) => this.switchBaseLayer(e.target.value));
        });

        // Overlay checkboxes
        const overlayMap = {
            'layer-forets':    'forets',
            'layer-limites':   'limites',
            'layer-placettes': 'placettes',
            'layer-routes':    'routes',
            'layer-hydro':     'hydro',
            'layer-localites': 'localites',
        };

        Object.entries(overlayMap).forEach(([cbId, key]) => {
            const cb = document.getElementById(cbId);
            if (!cb) return;
            cb.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.showOverlay(key);
                    this.loadOverlay(key);
                } else {
                    this.hideOverlay(key);
                }
            });
        });
    },

    switchBaseLayer(key) {
        const map = ['osm', 'satellite', 'terrain'];
        map.forEach(id => {
            const layerId = `${id}-layer`;
            if (this.map.getLayer(layerId)) {
                this.map.setLayoutProperty(layerId, 'visibility', id === key ? 'visible' : 'none');
            }
        });
    },

    showOverlay(key) {
        this._getLayerIds(key).forEach(id => {
            if (this.map.getLayer(id)) this.map.setLayoutProperty(id, 'visibility', 'visible');
        });
    },

    hideOverlay(key) {
        this._getLayerIds(key).forEach(id => {
            if (this.map.getLayer(id)) this.map.setLayoutProperty(id, 'visibility', 'none');
        });
    },

    _getLayerIds(key) {
        const map = {
            forets:    ['forets-fill', 'forets-border'],
            limites:   ['limites-fill', 'limites-border'],
            placettes: ['placettes-circle'],
            routes:    ['routes-line'],
            hydro:     ['hydro-line'],
            localites: ['localites-chef-circle', 'localites-loc-circle'],
        };
        return map[key] || [];
    },

    _setLoading(key, loading) {
        const cb = document.getElementById('layer-' + key);
        if (cb?.parentElement) cb.parentElement.classList.toggle('layer-loading', loading);
        if (loading) this._loadingOverlays.add(key);
        else this._loadingOverlays.delete(key);
    },

    async loadOverlay(key) {
        if (this.loadedOverlays.has(key) || this._loadingOverlays.has(key)) return;
        this._setLoading(key, true);

        try {
            switch (key) {
                case 'limites':   await this._loadLimites();   break;
                case 'placettes': await this._loadPlacettes(); break;
                case 'routes':    await this._loadRoutes();    break;
                case 'hydro':     await this._loadHydro();     break;
                case 'localites': await this._loadLocalites(); break;
                case 'forets':    break; // déjà chargé par Choropleth
            }
            this.loadedOverlays.add(key);
        } catch (err) {
            console.error(`[Layers] ${key}:`, err);
        }
        this._setLoading(key, false);
    },

    _addGeoJSONSource(id, data) {
        if (!this.map.getSource(id)) {
            this.map.addSource(id, { type: 'geojson', data: data || this.EMPTY_FC });
        } else {
            this.map.getSource(id).setData(data || this.EMPTY_FC);
        }
    },

    async _loadLimites() {
        const data = await API.getZonesEtude();
        if (!data?.features?.length) { console.warn('[Layers] Limites: vide'); return; }

        this._addGeoJSONSource('limites', data);

        if (!this.map.getLayer('limites-fill')) {
            this.map.addLayer({
                id: 'limites-fill',
                type: 'fill',
                source: 'limites',
                paint: {
                    'fill-color': '#7c3aed',
                    'fill-opacity': ['match', ['get', 'niveau'], 1, 0.04, 2, 0.03, 0.02],
                },
                layout: { visibility: 'none' },
            });
            this.map.addLayer({
                id: 'limites-border',
                type: 'line',
                source: 'limites',
                paint: {
                    'line-color': [
                        'match', ['get', 'niveau'],
                        1, '#7c3aed',
                        2, '#a855f7',
                        '#c084fc',
                    ],
                    'line-width': [
                        'match', ['get', 'niveau'],
                        1, 3,
                        2, 2.5,
                        1.5,
                    ],
                    'line-dasharray': [8, 4],
                    'line-opacity': 0.8,
                },
                layout: { visibility: 'none' },
            });
        }
        this.showOverlay('limites');
        console.log(`[Layers] Limites: ${data.features.length}`);
    },

    async _loadPlacettes() {
        const data = await API.getPlacettes();
        if (!data?.features?.length) { console.warn('[Layers] Placettes: vide'); return; }

        this._addGeoJSONSource('placettes', data);

        if (!this.map.getLayer('placettes-circle')) {
            this.map.addLayer({
                id: 'placettes-circle',
                type: 'circle',
                source: 'placettes',
                paint: {
                    'circle-radius': 5,
                    'circle-color': '#e74c3c',
                    'circle-stroke-color': '#c0392b',
                    'circle-stroke-width': 1.5,
                    'circle-opacity': 0.85,
                },
                layout: { visibility: 'visible' },
            });

            // Popup clic placette
            const self = this;
            this.map.on('click', 'placettes-circle', (e) => {
                if (!e.features.length) return;
                new maplibregl.Popup({ maxWidth: '260px', className: 'geo-popup' })
                    .setLngLat(e.lngLat)
                    .setHTML(PopupBuilder.placette(e.features[0].properties))
                    .addTo(self.map);
            });
            this.map.on('mouseenter', 'placettes-circle', () => { this.map.getCanvas().style.cursor = 'pointer'; });
            this.map.on('mouseleave', 'placettes-circle', () => { this.map.getCanvas().style.cursor = ''; });
        }
        console.log(`[Layers] Placettes: ${data.features.length}`);
    },

    async _loadRoutes() {
        const data = await API.getInfrastructures({ type: 'ROUTE' });
        if (!data?.features?.length) { console.warn('[Layers] Routes: vide'); return; }

        this._addGeoJSONSource('routes', data);

        if (!this.map.getLayer('routes-line')) {
            this.map.addLayer({
                id: 'routes-line',
                type: 'line',
                source: 'routes',
                paint: { 'line-color': '#8B4513', 'line-width': 2.5, 'line-opacity': 0.75 },
                layout: { visibility: 'visible' },
            });
        }
        console.log(`[Layers] Routes: ${data.features.length}`);
    },

    async _loadHydro() {
        const data = await API.getInfrastructures({ type: 'HYDROGRAPHIE' });
        if (!data?.features?.length) { console.warn('[Layers] Hydro: vide'); return; }

        this._addGeoJSONSource('hydro', data);

        if (!this.map.getLayer('hydro-line')) {
            this.map.addLayer({
                id: 'hydro-line',
                type: 'line',
                source: 'hydro',
                paint: { 'line-color': '#3498db', 'line-width': 2, 'line-opacity': 0.75 },
                layout: { visibility: 'visible' },
            });
        }
        console.log(`[Layers] Hydro: ${data.features.length}`);
    },

    async _loadLocalites() {
        const [locs, chefs] = await Promise.all([
            API.getInfrastructures({ type: 'LOCALITE' }),
            API.getInfrastructures({ type: 'CHEF_LIEU_SP' }),
        ]);
        const allFeatures = [
            ...((locs?.features) || []),
            ...((chefs?.features) || []),
        ];
        if (!allFeatures.length) { console.warn('[Layers] Localités: vide'); return; }

        // Séparer chefs-lieux et localités simples
        const chefsFC = { type: 'FeatureCollection', features: allFeatures.filter(f => f.properties.type_infra === 'CHEF_LIEU_SP') };
        const locsFC  = { type: 'FeatureCollection', features: allFeatures.filter(f => f.properties.type_infra !== 'CHEF_LIEU_SP') };

        this._addGeoJSONSource('localites-chef', chefsFC);
        this._addGeoJSONSource('localites-loc', locsFC);

        if (!this.map.getLayer('localites-chef-circle')) {
            this.map.addLayer({
                id: 'localites-chef-circle',
                type: 'circle',
                source: 'localites-chef',
                paint: {
                    'circle-radius': 7,
                    'circle-color': '#f59e0b',
                    'circle-stroke-color': '#d97706',
                    'circle-stroke-width': 2,
                    'circle-opacity': 0.9,
                },
                layout: { visibility: 'visible' },
            });
            this.map.addLayer({
                id: 'localites-loc-circle',
                type: 'circle',
                source: 'localites-loc',
                paint: {
                    'circle-radius': 4,
                    'circle-color': '#9ca3af',
                    'circle-stroke-color': '#6b7280',
                    'circle-stroke-width': 1,
                    'circle-opacity': 0.9,
                },
                layout: { visibility: 'visible' },
            });

            // Hover tooltip localités
            const self = this;
            ['localites-chef-circle', 'localites-loc-circle'].forEach(layerId => {
                self.map.on('mouseenter', layerId, (e) => {
                    self.map.getCanvas().style.cursor = 'pointer';
                    const nom = e.features[0]?.properties?.nom;
                    if (nom) {
                        new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: 'geo-hover-popup', offset: 8 })
                            .setLngLat(e.lngLat)
                            .setHTML(`<span class="text-xs font-semibold">${nom}</span>`)
                            .addTo(self.map);
                    }
                });
                self.map.on('mouseleave', layerId, () => {
                    self.map.getCanvas().style.cursor = '';
                    document.querySelectorAll('.geo-hover-popup').forEach(el => el.remove());
                });
            });
        }
        console.log(`[Layers] Localités: ${allFeatures.length}`);
    },
};
