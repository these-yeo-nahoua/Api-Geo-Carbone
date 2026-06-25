/**
 * Chat-to-Map IA Panel v5.0 — "Mistral"
 *
 * Compatible MapLibre GL JS :
 * - flyTo utilise maplibregl Map API
 * - Pulse marker via maplibregl.Marker
 * - Toutes les autres fonctionnalités v4 conservées (Chart.js, counters, etc.)
 */
const ChatPanel = {
    map: null,
    _chartInstances: [],
    _pulseMarker: null,

    init(map) {
        this.map = map;

        const toggle = document.getElementById('chat-toggle');
        const close  = document.getElementById('chat-close');
        const panel  = document.getElementById('chat-panel');
        const send   = document.getElementById('chat-send');
        const input  = document.getElementById('chat-input');
        const self   = this;

        if (toggle) toggle.addEventListener('click', () => {
            panel.classList.toggle('hidden');
            if (!panel.classList.contains('hidden') && !self._welcomed) self._showWelcome();
        });
        if (close) close.addEventListener('click', () => panel.classList.add('hidden'));
        if (send) send.addEventListener('click', () => self.sendQuery());
        if (input) input.addEventListener('keypress', (e) => { if (e.key === 'Enter') self.sendQuery(); });

        const aiSearch = document.getElementById('ai-search');
        if (aiSearch) {
            aiSearch.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    const q = aiSearch.value.trim();
                    if (q && input) {
                        input.value = q;
                        self.sendQuery();
                        if (panel) panel.classList.remove('hidden');
                    }
                }
            });
        }

        this._createParticles();
    },

    _welcomed: false,

    _showWelcome() {
        this._welcomed = true;
        const container = document.getElementById('chat-messages');
        if (!container) return;

        const div = document.createElement('div');
        div.className = 'chat-msg-ai';
        div.innerHTML =
            '<div class="space-y-3 stagger-children">' +
                '<div class="flex items-center gap-2">' +
                    '<div class="ai-avatar" style="width:24px;height:24px;border-radius:7px;">' +
                        '<i class="fas fa-leaf text-white text-[10px]"></i>' +
                    '</div>' +
                    '<span class="text-sm font-bold text-green-900" id="welcome-text"></span>' +
                    '<span class="typewriter-cursor" id="welcome-cursor">|</span>' +
                '</div>' +
                '<div id="welcome-body" style="display:none">' +
                    '<p class="text-xs text-gray-500 mb-2">Je peux analyser <strong>6 forêts classées</strong> du département d\'Oumé sur <strong>3 époques</strong> (1986, 2003, 2023). Propulsé par <strong>Mistral AI</strong>.</p>' +
                    '<div class="grid grid-cols-1 gap-1.5" id="welcome-examples"></div>' +
                '</div>' +
            '</div>';
        container.appendChild(div);

        const text = 'Bienvenue sur GEO-Carbone IA !';
        const target = document.getElementById('welcome-text');
        const cursor = document.getElementById('welcome-cursor');
        let i = 0;
        const self = this;
        function type() {
            if (i < text.length) {
                target.textContent += text.charAt(i++);
                setTimeout(type, 35);
            } else {
                if (cursor) cursor.remove();
                const body = document.getElementById('welcome-body');
                if (body) body.style.display = 'block';
                self._addWelcomeExamples();
            }
        }
        setTimeout(type, 400);
    },

    _addWelcomeExamples() {
        const container = document.getElementById('welcome-examples');
        if (!container) return;
        const examples = [
            { icon: 'fa-chart-bar',    text: 'Résumé global pour 2023',       color: 'bg-green-50 text-green-700 border-green-200' },
            { icon: 'fa-exchange-alt', text: 'Compare TENÉ 1986 vs 2023',     color: 'bg-blue-50 text-blue-700 border-blue-200' },
            { icon: 'fa-fire-alt',     text: 'Déforestation à DOKA',          color: 'bg-red-50 text-red-700 border-red-200' },
            { icon: 'fa-leaf',         text: 'Active le mode CO2',            color: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
        ];
        const self = this;
        examples.forEach((ex, idx) => {
            const pill = document.createElement('div');
            pill.className = 'flex items-center gap-2 p-2 rounded-lg border cursor-pointer transition-all hover:shadow-md hover:-translate-y-0.5 chat-example ' + ex.color;
            pill.style.animationDelay = (0.5 + idx * 0.1) + 's';
            pill.innerHTML = `<i class="fas ${ex.icon} text-xs"></i><span class="text-xs font-medium">${ex.text}</span>`;
            container.appendChild(pill);
        });
        this._bindExamples();
    },

    _createParticles() {
        const container = document.getElementById('chat-particles');
        if (!container) return;
        const leaves = ['🍃', '🌿', '🍂', '🌱', '☘️', '🍃'];
        for (let i = 0; i < 6; i++) {
            const leaf = document.createElement('span');
            leaf.className = 'leaf-particle';
            leaf.textContent = leaves[i];
            leaf.style.setProperty('--duration', (10 + Math.random() * 8) + 's');
            leaf.style.setProperty('--delay', (i * 2.5) + 's');
            leaf.style.setProperty('--size', (10 + Math.random() * 8) + 'px');
            leaf.style.setProperty('--left', (10 + Math.random() * 80) + '%');
            leaf.style.setProperty('--max-opacity', (0.12 + Math.random() * 0.1).toFixed(2));
            container.appendChild(leaf);
        }
    },

    async sendQuery() {
        const input = document.getElementById('chat-input');
        const query = (input ? input.value : '').trim();
        if (!query) return;

        this.addMessage(query, 'user');
        if (input) input.value = '';

        const loading = document.getElementById('ai-loading');
        if (loading) loading.classList.remove('hidden');
        this.showTyping();

        const self = this;
        try {
            const result = await API.queryAI(query);
            self.hideTyping();

            if (!result) {
                self.addMessage('⚠️ Impossible de contacter le serveur IA. Vérifiez votre connexion et réessayez.', 'ai');
                return;
            }

            if (result.parsed) self.showTags(result.parsed);
            self._updateContextBadge(result.parsed);

            // Badge moteur IA
            if (result.engine === 'mistral') {
                self.addMessage(
                    '<div class="text-[10px] text-purple-600 bg-purple-50/80 rounded-lg px-2.5 py-1 mb-1 flex items-center gap-1.5">' +
                    '<i class="fas fa-bolt text-purple-500"></i>Analysé par <strong>Mistral AI</strong></div>',
                    'ai', true
                );
            }

            if (result.explanation && result.explanation !== '[Mistral AI]') {
                self.addMessage(
                    `<div class="text-[10px] text-amber-600 bg-amber-50/80 rounded-lg px-2.5 py-1.5 mb-1 flex items-center gap-1.5">` +
                    `<i class="fas fa-magic text-amber-500"></i>${self._esc(result.explanation)}</div>`,
                    'ai', true
                );
            }

            self._handleResponse(result);

            const countEl = document.getElementById('ai-results-count');
            if (countEl) {
                const n = result.count || 0;
                const ms = result.processing_ms || 0;
                countEl.textContent = n > 0 ? `${n} résultat(s) — ${ms}ms` : `Traité en ${ms}ms`;
                countEl.classList.remove('hidden');
            }

        } catch (err) {
            self.hideTyping();
            self.addMessage(
                '<div class="text-red-600 flex items-center gap-2"><i class="fas fa-exclamation-triangle"></i>Erreur lors du traitement. Reformulez votre question.</div>',
                'ai', true
            );
            console.error('AI query error:', err);
        }

        if (loading) loading.classList.add('hidden');
    },

    _handleResponse(result) {
        switch (result.type) {
            case 'help':          this._renderHelp(result);         break;
            case 'stock_carbone': this._renderStockCarbone(result);  break;
            case 'resume':        this._renderResume(result);        break;
            case 'geojson':       this._renderGeojson(result);       break;
            case 'stats':         this._renderStats(result);         break;
            case 'comparison':    this._renderComparison(result);    break;
            case 'deforestation': this._renderDeforestation(result); break;
            case 'ranking':       this._renderRanking(result);       break;
            case 'no_results':    this._renderNoResults(result);     break;
            default:              this.addMessage('Aucun résultat. Essayez une autre formulation.', 'ai');
        }
    },

    _renderHelp(result) {
        const data = result.data;
        if (!data) return;
        const capIcons = [
            { icon: 'fa-map',          bg: 'bg-green-100 text-green-600' },
            { icon: 'fa-calculator',   bg: 'bg-blue-100 text-blue-600' },
            { icon: 'fa-exchange-alt', bg: 'bg-purple-100 text-purple-600' },
            { icon: 'fa-chart-line',   bg: 'bg-red-100 text-red-600' },
            { icon: 'fa-trophy',       bg: 'bg-amber-100 text-amber-600' },
            { icon: 'fa-file-alt',     bg: 'bg-teal-100 text-teal-600' },
            { icon: 'fa-leaf',         bg: 'bg-emerald-100 text-emerald-600' },
        ];
        const self = this;
        let html = '<div class="space-y-3 stagger-children">';
        html += `<div class="flex items-center gap-2"><div class="ai-avatar" style="width:24px;height:24px;border-radius:7px;"><i class="fas fa-leaf text-white text-[10px]"></i></div><span class="text-sm font-bold text-green-900">${this._esc(data.message)}</span></div>`;
        if (data.capabilities?.length) {
            html += '<div class="space-y-1.5">';
            data.capabilities.forEach((c, i) => {
                const ci = capIcons[i] || capIcons[0];
                html += `<div class="capability-card"><div class="capability-icon ${ci.bg}"><i class="fas ${ci.icon}"></i></div><span class="text-gray-700">${self._esc(c)}</span></div>`;
            });
            html += '</div>';
        }
        if (data.examples?.length) {
            html += '<div class="flex flex-wrap gap-1.5 mt-1">';
            data.examples.forEach(ex => { html += `<span class="quick-action-pill chat-example">${ex}</span>`; });
            html += '</div>';
        }
        html += '</div>';
        this._addAIMessage(html, result);
    },

    _renderStockCarbone(result) {
        if (typeof TimeSlider !== 'undefined' && TimeSlider.setMode) TimeSlider.setMode('carbone');
        this._showToast('Mode CO₂ activé !', 'success');
        const data = result.data;
        const html = `<div class="space-y-3 stagger-children"><div class="flex items-center gap-3"><div style="font-size:28px">🌍</div><div><div class="text-sm font-bold text-green-800">${this._esc(data?.message || '')}</div><div class="text-[10px] text-green-600 mt-0.5">4 classes forestières • Gradient tCO₂/ha</div></div></div></div>`;
        this._addAIMessage(html, result);
    },

    _renderResume(result) {
        const data = result.data;
        if (!data) { this.addMessage('Données insuffisantes pour la synthèse.', 'ai'); return; }
        const t = data.totaux || {};
        const chartData = result.chart_data;
        const chartId = 'resume-chart-' + Date.now();
        const self = this;
        let html = `<div class="space-y-3 stagger-children"><div class="text-sm font-bold text-green-900 flex items-center gap-2">📋 Synthèse ${data.annee}</div>`;
        html += '<div class="grid grid-cols-3 gap-2">';
        html += `<div class="metric-card"><div class="text-[9px] text-green-600 font-bold uppercase">Superficie</div><div class="text-sm font-bold text-green-900 anim-counter" data-target="${Math.round(t.superficie_ha || 0)}" data-suffix=" ha">0 ha</div></div>`;
        html += `<div class="metric-card"><div class="text-[9px] text-blue-600 font-bold uppercase">Carbone</div><div class="text-sm font-bold text-blue-900 anim-counter" data-target="${Math.round(t.carbone_tco2 || 0)}" data-suffix=" tCO₂">0 tCO₂</div></div>`;
        html += `<div class="metric-card"><div class="text-[9px] text-amber-600 font-bold uppercase">Polygones</div><div class="text-sm font-bold text-amber-900 anim-counter" data-target="${t.nb_polygones || 0}" data-suffix="">0</div></div>`;
        html += '</div>';
        if (chartData) html += `<div class="chat-chart-wrap"><div class="chat-chart-container"><canvas id="${chartId}"></canvas></div></div>`;
        if (data.par_type?.length) {
            const totalSup = t.superficie_ha || 1;
            html += '<div class="text-[9px] text-gray-500 font-bold uppercase tracking-wider">Répartition</div><div class="space-y-1.5">';
            data.par_type.forEach(s => {
                const color = s.nomenclature__couleur_hex || '#999';
                const label = s.nomenclature__libelle_fr || '?';
                const sup = s.total_superficie_ha || 0;
                const pct = (sup / totalSup * 100).toFixed(1);
                html += `<div class="text-xs"><div class="flex justify-between mb-0.5"><span><span class="inline-block w-2 h-2 rounded-sm mr-1" style="background:${self._escAttr(color)}"></span>${self._esc(label)}</span><span class="text-gray-500 font-medium">${sup.toLocaleString('fr-FR', {maximumFractionDigits:0})} ha (${pct}%)</span></div><div class="progress-bar-track"><div class="progress-bar-fill" style="background:${self._escAttr(color)}" data-width="${pct}%"></div></div></div>`;
            });
            html += '</div>';
        }
        html += '</div>';
        this._addAIMessage(html, result);
        if (chartData) setTimeout(() => self._renderMiniDoughnut(chartId, chartData), 100);
        setTimeout(() => { self._animateAllCounters(); self._animateProgressBars(); }, 200);
    },

    _renderStats(result) {
        const data = result.data;
        const chartData = result.chart_data;
        if (!data?.length) { this.addMessage('Aucune statistique disponible.', 'ai'); return; }
        let totalSup = 0, totalCarb = 0;
        data.forEach(s => { totalSup += (s.total_superficie_ha || 0); totalCarb += (s.total_carbone || 0); });
        const chartId = 'stats-chart-' + Date.now();
        const self = this;
        let html = '<div class="space-y-3 stagger-children"><div class="text-sm font-bold text-green-900">📊 Statistiques</div>';
        if (chartData) html += `<div class="chat-chart-wrap"><div class="chat-chart-container chart-sm"><canvas id="${chartId}"></canvas></div></div>`;
        html += '<div class="space-y-1.5">';
        data.forEach(s => {
            const color = s.nomenclature__couleur_hex || '#999';
            const label = s.nomenclature__libelle_fr || s.nomenclature__code || '?';
            const sup = s.total_superficie_ha || 0;
            const pct = totalSup > 0 ? (sup / totalSup * 100).toFixed(1) : '0';
            html += `<div class="text-xs"><div class="flex justify-between mb-0.5"><span><span class="inline-block w-2 h-2 rounded-sm mr-1" style="background:${self._escAttr(color)}"></span>${self._esc(label)}</span><span class="font-medium">${sup.toLocaleString('fr-FR', {maximumFractionDigits:0})} ha <span class="text-gray-400">(${pct}%)</span></span></div><div class="progress-bar-track"><div class="progress-bar-fill" style="background:${self._escAttr(color)}" data-width="${pct}%"></div></div></div>`;
        });
        html += '</div>';
        html += `<div class="flex justify-between text-xs font-bold bg-green-50/80 rounded-lg px-3 py-2 border border-green-200/50"><span>Total</span><span>${totalSup.toLocaleString('fr-FR', {maximumFractionDigits:0})} ha • ${totalCarb.toLocaleString('fr-FR', {maximumFractionDigits:0})} tCO₂</span></div>`;
        html += '</div>';
        this._addAIMessage(html, result);
        if (chartData) setTimeout(() => self._renderMiniDoughnut(chartId, chartData), 100);
        setTimeout(() => self._animateProgressBars(), 200);
    },

    _renderComparison(result) {
        const data = result.data;
        if (!data) { this.addMessage('Comparaison impossible.', 'ai'); return; }
        const a1 = data.annee1, a2 = data.annee2;
        const chartData = result.chart_data;
        const chartId = 'comp-chart-' + Date.now();
        const self = this;
        let html = `<div class="space-y-3 stagger-children"><div class="text-sm font-bold text-green-900">🔄 Comparaison ${a1.annee} vs ${a2.annee}</div>`;
        if (chartData) html += `<div class="chat-chart-wrap"><div class="chat-chart-container" style="width:240px;height:160px;"><canvas id="${chartId}"></canvas></div></div>`;
        const map2 = {};
        (a2.data || []).forEach(s => { map2[s.nomenclature__code] = s; });
        html += '<div class="space-y-1">';
        (a1.data || []).forEach(s1 => {
            const code = s1.nomenclature__code;
            const s2 = map2[code] || {};
            const color = s1.nomenclature__couleur_hex || '#999';
            const label = s1.nomenclature__libelle_fr || code;
            const v1 = s1.superficie_ha || 0, v2 = s2.superficie_ha || 0;
            const delta = v2 - v1;
            const icon = delta > 0 ? '↑' : delta < 0 ? '↓' : '–';
            const cls = delta > 0 ? 'text-green-600' : delta < 0 ? 'text-red-600' : 'text-gray-400';
            const sign = delta > 0 ? '+' : '';
            html += `<div class="flex items-center justify-between text-xs py-1 border-b border-gray-100"><span><span class="inline-block w-2 h-2 rounded-sm mr-1" style="background:${self._escAttr(color)}"></span>${self._esc(label)}</span><span class="flex items-center gap-2"><span class="text-gray-400">${v1.toLocaleString('fr-FR', {maximumFractionDigits:0})}</span><span>→</span><span class="font-medium">${v2.toLocaleString('fr-FR', {maximumFractionDigits:0})}</span><span class="${cls} font-bold">${icon} ${sign}${delta.toLocaleString('fr-FR', {maximumFractionDigits:0})}</span></span></div>`;
        });
        html += '</div></div>';
        this._addAIMessage(html, result);
        if (chartData) setTimeout(() => self._renderComparisonChart(chartId, chartData), 100);
    },

    _renderDeforestation(result) {
        const data = result.data;
        if (!data) { this.addMessage('Analyse de déforestation impossible.', 'ai'); return; }
        const lossPct = Math.min(Math.abs(data.perte_pct || 0), 100);
        const self = this;
        let html = `<div class="space-y-3 stagger-children"><div class="text-sm font-bold text-green-900">📉 Déforestation ${data.annee1} → ${data.annee2}</div>`;
        html += `<div class="text-center py-2"><div class="text-3xl font-bold text-red-600 anim-counter" data-target="${Math.abs(Math.round(data.perte_ha))}" data-suffix=" ha" data-prefix="-">0 ha</div><div class="text-xs text-red-500 font-medium">de couvert forestier perdu</div></div>`;
        html += `<div class="loss-bar-track"><div class="loss-bar-fill" data-width="${lossPct}%" style="width:0%"><span>${lossPct.toFixed(1)}%</span></div></div>`;
        html += '<div class="grid grid-cols-2 gap-2">';
        html += `<div class="metric-card"><div class="text-[9px] text-gray-500 font-bold uppercase">${data.annee1}</div><div class="text-sm font-bold text-green-800 anim-counter" data-target="${Math.round(data.superficie_foret_1)}" data-suffix=" ha">0 ha</div></div>`;
        html += `<div class="metric-card"><div class="text-[9px] text-gray-500 font-bold uppercase">${data.annee2}</div><div class="text-sm font-bold text-red-700 anim-counter" data-target="${Math.round(data.superficie_foret_2)}" data-suffix=" ha">0 ha</div></div>`;
        html += '</div></div>';
        this._addAIMessage(html, result);
        setTimeout(() => {
            self._animateAllCounters();
            document.querySelectorAll('.loss-bar-fill[data-width]').forEach(f => { f.style.width = f.dataset.width; });
        }, 200);
    },

    _renderRanking(result) {
        const data = result.data;
        const rankingBy = result.ranking_by;
        if (!data?.length) { this.addMessage('Aucune donnée pour le classement.', 'ai'); return; }
        const byCarbon = rankingBy === 'carbone';
        const maxVal = data[0] ? (byCarbon ? (data[0].total_carbone || 0) : (data[0].total_superficie_ha || 0)) : 1;
        const medals = ['🥇', '🥈', '🥉'];
        const self = this;
        let html = `<div class="space-y-2 stagger-children"><div class="text-sm font-bold text-green-900">🏆 Classement par ${byCarbon ? 'stock carbone' : 'superficie'}</div>`;
        data.forEach((item, idx) => {
            const medal = idx < 3 ? medals[idx] : `<span class="text-sm text-gray-400 font-bold">${idx+1}</span>`;
            const nom = item.foret__nom || item.foret__code || '?';
            const code = item.foret__code || '';
            const sup = item.total_superficie_ha || 0;
            const carb = item.total_carbone || 0;
            const mainVal = byCarbon ? carb : sup;
            const pct = maxVal > 0 ? (mainVal / maxVal * 100) : 0;
            html += `<div class="ranking-card" data-forest="${self._escAttr(code)}" style="animation-delay:${idx*0.08}s"><div class="ranking-medal">${medal}</div><div class="flex-1 min-w-0"><div class="text-xs font-bold text-gray-800 truncate">${self._esc(nom)}</div><div class="text-[10px] text-gray-500">${sup.toLocaleString('fr-FR', {maximumFractionDigits:0})} ha • ${carb.toLocaleString('fr-FR', {maximumFractionDigits:0})} tCO₂</div><div class="progress-bar-track mt-1"><div class="progress-bar-fill" style="background:${byCarbon?'#16a34a':'#2563eb'}" data-width="${pct.toFixed(0)}%"></div></div></div><i class="fas fa-map-marker-alt text-green-500 text-xs flex-shrink-0"></i></div>`;
        });
        html += '</div>';
        this._addAIMessage(html, result);
        setTimeout(() => {
            self._animateProgressBars();
            document.querySelectorAll('.ranking-card[data-forest]').forEach(card => {
                card.addEventListener('click', () => self._flyToForest(card.dataset.forest));
            });
        }, 200);
    },

    _renderGeojson(result) {
        if (result.data && App.map) Choropleth.renderAIResults(result.data, App.map);
        const count = result.count || 0, displayed = result.displayed || count, ms = result.processing_ms || 0;
        if (result.coordinates?.length) this._flyToForest(result.coordinates[0].code);
        let html = `<div class="space-y-2 stagger-children"><div class="flex items-center gap-3"><div style="font-size:24px">🗺️</div><div><div class="text-sm font-medium"><strong>${displayed}</strong> polygone(s) affiché(s)</div><div class="text-[10px] text-gray-400">${ms}ms de traitement</div></div></div>`;
        if (result.truncated) html += `<div class="text-[10px] text-amber-600 bg-amber-50/80 rounded-lg px-2.5 py-1.5 flex items-center gap-1.5"><i class="fas fa-info-circle"></i>${count} résultats au total, ${displayed} affichés.</div>`;
        html += '</div>';
        this._addAIMessage(html, result);
    },

    _renderNoResults(result) {
        const suggestions = result.suggestions;
        let html = '<div class="space-y-2 stagger-children"><div class="flex items-center gap-2"><span style="font-size:20px">🔍</span><span class="text-sm text-gray-600">Aucun résultat trouvé.</span></div>';
        if (suggestions?.length) {
            html += '<div class="text-[9px] text-gray-500 font-bold uppercase tracking-wider">Essayez :</div><div class="flex flex-wrap gap-1.5">';
            suggestions.forEach(s => { html += `<span class="quick-action-pill chat-example">${s}</span>`; });
            html += '</div>';
        }
        html += '</div>';
        this._addAIMessage(html, result);
    },

    _addAIMessage(html, result) {
        if (result?.fun_fact) html += `<div class="fun-fact-card"><span class="mr-1">🌿</span><strong>Le saviez-vous ?</strong> ${this._esc(result.fun_fact)}</div>`;
        if (result?.confidence) {
            const conf = result.confidence;
            const confColor = conf >= 80 ? '#22c55e' : conf >= 50 ? '#f59e0b' : '#ef4444';
            html += `<div class="flex items-center gap-2 mt-1"><span class="text-[9px] text-gray-400">Confiance</span><div class="confidence-bar flex-1"><div class="confidence-fill" style="width:${conf}%;background:${confColor}"></div></div><span class="text-[9px] font-bold" style="color:${confColor}">${conf}%</span></div>`;
        }
        if (result?.suggestions?.length) {
            html += '<div class="quick-actions-v4">';
            result.suggestions.forEach(s => { html += `<span class="quick-action-pill chat-example">${s}</span>`; });
            html += '</div>';
        }
        const fullHtml = html + '<div class="msg-reactions"><button class="reaction-btn" data-reaction="up" title="Utile"><i class="fas fa-thumbs-up"></i></button><button class="reaction-btn" data-reaction="down" title="Pas utile"><i class="fas fa-thumbs-down"></i></button></div>';
        this.addMessage(fullHtml, 'ai', true);
        this._bindExamples();
        this._bindReactions();
    },

    addMessage(text, type, isHtml) {
        const container = document.getElementById('chat-messages');
        if (!container) return;
        const div = document.createElement('div');
        div.className = type === 'user' ? 'chat-msg-user' : 'chat-msg-ai';
        if (isHtml) div.innerHTML = text;
        else { div.style.whiteSpace = 'pre-wrap'; div.textContent = text; }
        container.appendChild(div);
        setTimeout(() => container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' }), 50);
    },

    showTyping() {
        const container = document.getElementById('chat-messages');
        if (!container) return;
        const div = document.createElement('div');
        div.id = 'typing-indicator';
        div.className = 'chat-msg-ai typing-v4';
        div.innerHTML = '<div class="ai-avatar-sm"><i class="fas fa-leaf text-white text-[8px]"></i></div><div class="typing-dots"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div><span class="text-[10px] text-gray-400 ml-1">Mistral analyse...</span>';
        container.appendChild(div);
        container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    },

    hideTyping() {
        const el = document.getElementById('typing-indicator');
        if (el) el.remove();
    },

    // ── Chart.js renderers ─────────────────────────────────────────
    _renderMiniDoughnut(canvasId, chartData) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;
        const chart = new Chart(canvas.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: chartData.labels,
                datasets: [{ data: chartData.superficie, backgroundColor: chartData.colors, borderWidth: 2, borderColor: 'rgba(255,255,255,0.8)' }],
            },
            options: {
                responsive: true, maintainAspectRatio: true, cutout: '62%',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(20,83,45,0.92)', cornerRadius: 8, padding: 8,
                        callbacks: { label: ctx => { const t = ctx.dataset.data.reduce((a,b)=>a+b,0); return `${ctx.label}: ${ctx.parsed.toLocaleString('fr-FR')} ha (${t>0?(ctx.parsed/t*100).toFixed(1):0}%)`; } },
                    },
                },
                animation: { animateRotate: true, duration: 1200, easing: 'easeOutQuart' },
            },
        });
        this._chartInstances.push(chart);
    },

    _renderComparisonChart(canvasId, chartData) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || typeof Chart === 'undefined') return;
        const chart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: chartData.labels.map(l => l.length > 10 ? l.substring(0,10)+'…' : l),
                datasets: [
                    { label: String(chartData.annee1), data: chartData.values1, backgroundColor: chartData.colors.map(c=>c+'99'), borderColor: chartData.colors, borderWidth: 1, borderRadius: 4 },
                    { label: String(chartData.annee2), data: chartData.values2, backgroundColor: chartData.colors, borderColor: chartData.colors, borderWidth: 1, borderRadius: 4 },
                ],
            },
            options: {
                responsive: true, maintainAspectRatio: false, indexAxis: 'y',
                plugins: { legend: { display: true, position: 'top', labels: { font: { size: 9 }, padding: 6, boxWidth: 10 } } },
                scales: { x: { ticks: { font: { size: 8 } }, grid: { display: false } }, y: { ticks: { font: { size: 8 } }, grid: { display: false } } },
                animation: { duration: 1000 },
            },
        });
        this._chartInstances.push(chart);
    },

    _animateAllCounters() {
        document.querySelectorAll('.anim-counter[data-target]').forEach(el => {
            const target = parseInt(el.dataset.target) || 0;
            if (el._animated) return;
            el._animated = true;
            this._animateCounter(el, target, 1500, el.dataset.suffix || '', el.dataset.prefix || '');
        });
    },

    _animateCounter(el, target, duration, suffix, prefix) {
        const start = performance.now();
        function easeOut(t) { return 1 - Math.pow(1-t, 4); }
        function update(now) {
            const p = Math.min((now - start) / duration, 1);
            el.textContent = (prefix||'') + Math.round(easeOut(p)*target).toLocaleString('fr-FR') + (suffix||'');
            if (p < 1) requestAnimationFrame(update);
        }
        requestAnimationFrame(update);
    },

    _animateProgressBars() {
        document.querySelectorAll('.progress-bar-fill[data-width]').forEach(bar => {
            if (bar._animated) return;
            bar._animated = true;
            setTimeout(() => { bar.style.width = bar.dataset.width; }, 50);
        });
    },

    // ── FlyTo MapLibre ─────────────────────────────────────────────
    _flyToForest(forestCode) {
        if (!this.map || !forestCode) return;
        const CENTERS = {
            'TENE':     [-5.718, 6.525],
            'DOKA':     [-5.603, 6.398],
            'SANGOUE':  [-5.480, 6.350],
            'LAHOUDA':  [-5.390, 6.290],
            'ZOUEKE_1': [-5.550, 6.440],
            'ZOUEKE_2': [-5.520, 6.410],
        };
        const center = CENTERS[forestCode];
        if (!center) return;
        this.map.flyTo({ center, zoom: 11, duration: 1500, essential: true });
        this._addPulseMarker(center);
    },

    _addPulseMarker(lngLat) {
        if (!this.map) return;
        if (this._pulseMarker) this._pulseMarker.remove();

        const el = document.createElement('div');
        el.className = 'pulse-ring-maplibre';
        el.style.cssText = 'width:44px;height:44px;border-radius:50%;background:rgba(34,197,94,0.25);border:2px solid #22c55e;animation:pulseRing 1.2s ease-out infinite;';

        this._pulseMarker = new maplibregl.Marker({ element: el, anchor: 'center' })
            .setLngLat(lngLat)
            .addTo(this.map);

        setTimeout(() => {
            if (this._pulseMarker) { this._pulseMarker.remove(); this._pulseMarker = null; }
        }, 4000);
    },

    _showToast(message, type) {
        const panel = document.getElementById('chat-panel');
        if (!panel) return;
        const existing = panel.querySelector('.chat-toast');
        if (existing) existing.remove();
        const toast = document.createElement('div');
        toast.className = `chat-toast toast-${type || 'info'}`;
        toast.innerHTML = `<i class="fas ${type==='success'?'fa-check-circle':'fa-info-circle'}"></i><span>${this._esc(message)}</span>`;
        panel.appendChild(toast);
        setTimeout(() => { toast.classList.add('chat-toast-exit'); setTimeout(() => toast.remove(), 300); }, 3000);
    },

    _updateContextBadge(parsed) {
        const badge = document.getElementById('chat-context-badge');
        if (!badge || !parsed) return;
        const parts = [];
        if (parsed.forests?.length) parts.push(parsed.forests[0]);
        if (parsed.years?.length) parts.push(parsed.years[parsed.years.length-1]);
        if (parts.length) { badge.textContent = parts.join(' • '); badge.classList.remove('hidden'); }
        else badge.classList.add('hidden');
    },

    showTags(parsed) {
        const container = document.getElementById('ai-tags');
        if (!container || !parsed) return;
        container.innerHTML = '';
        const tags = [];
        const inherited = parsed._inherited || [];
        (parsed.forests||[]).forEach(f => tags.push({ label: f, color: inherited.includes('forests')?'bg-green-50 text-green-600 border border-green-200':'bg-green-100 text-green-800', icon: 'fa-tree' }));
        (parsed.cover_types||[]).forEach(c => tags.push({ label: c, color: inherited.includes('cover_types')?'bg-blue-50 text-blue-600 border border-blue-200':'bg-blue-100 text-blue-800', icon: 'fa-layer-group' }));
        (parsed.years||[]).forEach(y => tags.push({ label: y, color: inherited.includes('years')?'bg-amber-50 text-amber-600 border border-amber-200':'bg-amber-100 text-amber-800', icon: 'fa-calendar' }));
        if (parsed.intent) tags.push({ label: parsed.intent, color: 'bg-purple-100 text-purple-800', icon: 'fa-bolt' });
        container.innerHTML = tags.map(t => `<span class="text-[10px] px-2 py-0.5 rounded-full ${t.color}"><i class="fas ${t.icon} mr-0.5 text-[8px] opacity-60"></i>${t.label}</span>`).join(' ');
    },

    _bindReactions() {
        document.querySelectorAll('.reaction-btn:not([data-bound])').forEach(btn => {
            btn.setAttribute('data-bound', '1');
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                btn.parentElement.querySelectorAll('.reaction-btn').forEach(s => s.classList.remove('reacted'));
                btn.classList.add('reacted');
            });
        });
    },

    _bindExamples() {
        const input = document.getElementById('chat-input');
        const self = this;
        document.querySelectorAll('.chat-example').forEach(el => {
            const newEl = el.cloneNode(true);
            el.parentNode.replaceChild(newEl, el);
            newEl.addEventListener('click', () => {
                if (input) {
                    input.value = newEl.textContent.replace(/["«»“”]/g, '').trim();
                    self.sendQuery();
                    const panel = document.getElementById('chat-panel');
                    if (panel) panel.classList.remove('hidden');
                }
            });
        });
    },

    _esc(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    _escAttr(str) {
        return String(str).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    },
};
