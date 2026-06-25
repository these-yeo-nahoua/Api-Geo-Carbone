/**
 * API.GEO.Carbone — Application principale v5.0 (MapLibre GL JS)
 *
 * Architecture :
 *  1. MapLibre WebGL — rendu GPU, 100k+ polygones sans effort
 *  2. Sources GeoJSON — mise à jour via setData() (pas de recréation de layer)
 *  3. Cache frontend 5 min — changement d'année < 5ms après préchargement
 *  4. Double-buffer via setData() atomique de MapLibre
 *  5. Mode stock carbone — source dédiée avec gradient vert
 */
const App = {
    map: null,
    currentYear: 1986,
    currentForet: '',
    foretsData: null,   // FeatureCollection des 6 forêts — utilisé pour le ciblage (fitBounds)
    _loadDebounce: null,
    _preloaded: false,

    async init() {
        console.log('[App] Init MapLibre GL JS...');

        // ── Initialisation MapLibre ──────────────────────────────────
        this.map = new maplibregl.Map({
            container: 'map',
            style: {
                version: 8,
                glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
                sources: {
                    'osm': {
                        type: 'raster',
                        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
                        tileSize: 256,
                        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
                        maxzoom: 19,
                    },
                    'satellite': {
                        type: 'raster',
                        tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
                        tileSize: 256,
                        attribution: '© Esri',
                        maxzoom: 18,
                    },
                    'terrain': {
                        type: 'raster',
                        tiles: ['https://tile.opentopomap.org/{z}/{x}/{y}.png'],
                        tileSize: 256,
                        attribution: '© OpenTopoMap',
                        maxzoom: 17,
                    },
                },
                layers: [
                    { id: 'osm-layer',       type: 'raster', source: 'osm',       layout: { visibility: 'visible' } },
                    { id: 'satellite-layer', type: 'raster', source: 'satellite', layout: { visibility: 'none'    } },
                    { id: 'terrain-layer',   type: 'raster', source: 'terrain',   layout: { visibility: 'none'    } },
                ],
            },
            center: [-5.5, 6.5],   // [lng, lat] — centré sur Oumé
            zoom: 10,
            attributionControl: { compact: true },
        });

        // Attendre que la carte soit prête
        await new Promise(resolve => this.map.on('load', resolve));
        console.log('[App] MapLibre chargé');

        // ── Init des modules ─────────────────────────────────────────
        LayerManager.init(this.map);
        Sidebar.init();
        TimeSlider.init(
            (year) => this.onYearChange(year),
            (mode) => this.onModeChange(mode),
        );
        ChatPanel.init(this.map);
        ReportGenerator.init();

        // Forest selector — sélection + ciblage (fly-to)
        const foretSelect = document.getElementById('foret-select');
        if (foretSelect) {
            foretSelect.addEventListener('change', (e) => this.targetForet(e.target.value));
        }

        // Toggle couche occupation
        const layerOcc = document.getElementById('layer-occupation');
        if (layerOcc) {
            layerOcc.addEventListener('change', (e) => {
                const vis = e.target.checked ? 'visible' : 'none';
                ['occupation-fill', 'occupation-border', 'occupation-ai-fill'].forEach(id => {
                    if (this.map.getLayer(id)) this.map.setLayoutProperty(id, 'visibility', vis);
                });
                if (e.target.checked) this.loadOccupation();
            });
        }

        await this.loadInitialData();
    },

    showLoading(text) {
        const el = document.getElementById('loading-overlay');
        const txt = document.getElementById('loading-text');
        if (el) el.classList.remove('hidden');
        if (txt) txt.textContent = text || 'Chargement...';
    },

    hideLoading() {
        const el = document.getElementById('loading-overlay');
        if (el) el.classList.add('hidden');
    },

    async loadInitialData() {
        this.showLoading('Chargement des forêts classées...');

        try {
            // 1. Ajouter les sources GeoJSON vides (initialisées une seule fois)
            Choropleth.initSources(this.map);

            // 2. Limites administratives en arrière-plan
            LayerManager.loadOverlay('limites');

            // 3. Forêts classées
            const forets = await API.getForets();
            if (forets?.features?.length > 0) {
                this.foretsData = forets;   // stocké pour le ciblage (_flyToForet)
                Choropleth.renderForets(forets, this.map);

                // Populate forest selector
                const sel = document.getElementById('foret-select');
                if (sel) {
                    forets.features.forEach(f => {
                        const p = f.properties || {};
                        const opt = document.createElement('option');
                        opt.value = p.code;
                        opt.textContent = p.nom || p.code;
                        sel.appendChild(opt);
                    });
                }

                // Centrer la carte sur les forêts
                const bounds = this._getBoundsFromGeoJSON(forets);
                if (bounds) this.map.fitBounds(bounds, { padding: 40, duration: 1000 });
            }
            console.log('[App] Forêts:', forets?.features?.length || 0);

            // 4. Occupation du sol — année 1986
            this.showLoading('Chargement occupation du sol 1986...');
            await this.loadOccupation();

            // 5. Statistiques
            this.showLoading('Statistiques...');
            await Stats.load(this.currentYear, this.currentForet);

            // 6. Légende
            await Legend.init();

        } catch (err) {
            console.error('[App] Init error:', err);
        }

        this.hideLoading();
        console.log('[App] Prêt');

        // 7. Préchargement des 3 années + stock carbone
        this._backgroundPreload();
    },

    async _backgroundPreload() {
        if (this._preloaded) return;
        try {
            await Promise.all([
                API.preloadAllYears(this.currentForet),
                API.getStockCarbone(),
            ]);
            this._preloaded = true;
            console.log('[App] Préchargement complet — changement d\'année instantané');
        } catch (err) {
            console.warn('[App] Préchargement (non-critique):', err);
        }
    },

    async loadOccupation() {
        const params = { annee: this.currentYear };
        if (this.currentForet) params.foret_code = this.currentForet;

        const t0 = performance.now();
        try {
            const data = await API.getOccupations(params);
            const dt = Math.round(performance.now() - t0);

            if (data?.features?.length > 0) {
                Choropleth.renderOccupation(data, this.map);
                console.log(`[App] Occupation ${this.currentYear}: ${data.features.length} polygones (${dt}ms)`);
            } else {
                Choropleth.clearOccupation(this.map);
                console.warn(`[App] Occupation ${this.currentYear}: vide (${dt}ms)`);
                // État vide explicite : la forêt existe mais n'a pas de données pour cette année
                if (this.currentForet) {
                    const nom = this.foretsData?.features
                        ?.find(f => f.properties?.code === this.currentForet)?.properties?.nom
                        || this.currentForet;
                    this._showMapNotice(`Aucune donnée d'occupation pour ${nom} en ${this.currentYear}.`);
                }
            }
        } catch (err) {
            console.error('[App] Occupation error:', err);
        }
    },

    /**
     * Affiche une notification flottante non-bloquante sur la carte
     * (ex: forêt sans données pour l'année sélectionnée).
     */
    _showMapNotice(message) {
        let el = document.getElementById('map-notice');
        if (!el) {
            el = document.createElement('div');
            el.id = 'map-notice';
            el.className = 'map-notice';
            document.getElementById('app')?.appendChild(el);
        }
        el.innerHTML = `<i class="fas fa-circle-info"></i><span>${message}</span>`;
        el.classList.add('show');
        clearTimeout(this._noticeTimer);
        this._noticeTimer = setTimeout(() => el.classList.remove('show'), 3500);
    },

    /**
     * Cible une forêt : synchronise le dropdown, filtre l'occupation, recalcule
     * les stats et zoome dessus. Appelé par le <select> ET par les boutons popup.
     * @param {string} code - code forêt (ex: 'TENE') ou '' pour « toutes les forêts »
     */
    targetForet(code) {
        const value = code || '';
        const sel = document.getElementById('foret-select');
        if (sel && sel.value !== value) sel.value = value;

        this.currentForet = value;
        API.clearCachePrefix('/occupations/');
        this._preloaded = false;

        this.loadOccupation();
        Stats.load(this.currentYear, this.currentForet);
        this._flyToForet(value);
        this._backgroundPreload();

        // Fermer un éventuel popup ouvert
        if (Choropleth._popup) Choropleth._popup.remove();
    },

    /**
     * Zoome (fitBounds) sur la forêt ciblée. Sans code → recadre sur l'ensemble.
     */
    _flyToForet(code) {
        if (!this.foretsData?.features?.length || !this.map) return;

        if (!code) {
            const allBounds = this._getBoundsFromGeoJSON(this.foretsData);
            if (allBounds) this.map.fitBounds(allBounds, { padding: 40, duration: 1200 });
            return;
        }

        const feature = this.foretsData.features.find(f => (f.properties?.code) === code);
        if (!feature) { console.warn('[App] Forêt introuvable:', code); return; }

        const fc = { type: 'FeatureCollection', features: [feature] };
        const bounds = this._getBoundsFromGeoJSON(fc);
        if (bounds) this.map.fitBounds(bounds, { padding: 70, duration: 1400, maxZoom: 13 });
    },

    async onYearChange(year) {
        this.currentYear = year;
        if (this._loadDebounce) clearTimeout(this._loadDebounce);
        this._loadDebounce = setTimeout(async () => {
            const layerOcc = document.getElementById('layer-occupation');
            if (!layerOcc || layerOcc.checked) await this.loadOccupation();
            Stats.load(year, this.currentForet);
        }, 100);
    },

    async onModeChange(mode) {
        if (mode === 'carbone') {
            await this.loadStockCarbone();
        } else {
            this.showLoading(`Chargement occupation ${this.currentYear}...`);
            try {
                await this.loadOccupation();
                Stats.load(this.currentYear, this.currentForet);
                Legend.render();
            } catch (err) {
                console.error('[App] Retour mode temporel:', err);
            }
            this.hideLoading();
        }
    },

    async loadStockCarbone() {
        this.showLoading('Chargement du stock carbone 2023...');
        try {
            const t0 = performance.now();
            const data = await API.getStockCarbone();
            const dt = Math.round(performance.now() - t0);

            if (data?.features?.length > 0) {
                Choropleth.renderStockCarbone(data, this.map);
                Stats.loadCarbone(data);
                Legend.renderCarbone(data);
                console.log(`[App] Stock carbone: ${data.features.length} classes (${dt}ms)`);
            } else {
                Choropleth.clearOccupation(this.map);
                console.warn(`[App] Stock carbone: vide (${dt}ms)`);
            }
        } catch (err) {
            console.error('[App] Stock carbone error:', err);
        }
        this.hideLoading();
    },

    /** Calcule les bounds [[minLng,minLat],[maxLng,maxLat]] depuis un GeoJSON. */
    _getBoundsFromGeoJSON(geojson) {
        if (!geojson?.features?.length) return null;
        let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;

        function processCoords(coords) {
            if (typeof coords[0] === 'number') {
                const [lng, lat] = coords;
                if (lng < minLng) minLng = lng;
                if (lng > maxLng) maxLng = lng;
                if (lat < minLat) minLat = lat;
                if (lat > maxLat) maxLat = lat;
            } else {
                coords.forEach(processCoords);
            }
        }

        geojson.features.forEach(f => {
            if (f.geometry?.coordinates) processCoords(f.geometry.coordinates);
        });

        if (!isFinite(minLng)) return null;
        return [[minLng, minLat], [maxLng, maxLat]];
    },
};

document.addEventListener('DOMContentLoaded', () => {
    App.init().catch(err => console.error('[App] Fatal:', err));
});
