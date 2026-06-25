/**
 * Popup Builder - Formatage des popups d'information
 */
const PopupBuilder = {
    occupation(props) {
        return `
            <div class="popup-header">${props.foret_nom || 'Foret'}</div>
            <div class="popup-body">
                <div class="row"><span class="label">Type</span><span class="value">${props.libelle || props.type_couvert || '-'}</span></div>
                <div class="row"><span class="label">Annee</span><span class="value">${props.annee || '-'}</span></div>
                <div class="row"><span class="label">Superficie</span><span class="value">${props.superficie_ha ? props.superficie_ha.toLocaleString('fr', {maximumFractionDigits: 1}) + ' ha' : '-'}</span></div>
                <div class="row"><span class="label">Stock carbone</span><span class="value">${props.stock_carbone_calcule ? props.stock_carbone_calcule.toLocaleString('fr', {maximumFractionDigits: 0}) + ' tCO2/ha' : '-'}</span></div>
                <div class="row"><span class="label">Source</span><span class="value">${props.source_donnee || '-'}</span></div>
                ${this._targetBtn(props.foret_code)}
            </div>`;
    },

    /** Bouton « Cibler cette forêt » — zoome et filtre sur la forêt au clic. */
    _targetBtn(code) {
        if (!code) return '';
        return `<button type="button" class="popup-target-btn" onclick="App.targetForet('${code}')">
            <i class="fas fa-crosshairs"></i> Cibler cette forêt
        </button>`;
    },

    stockCarbone(props) {
        const stock = props.stock_tco2_ha || 0;
        const sup = props.superficie_ha || 0;
        const totalCarbone = Math.round(stock * sup);
        return `
            <div class="popup-header" style="background:linear-gradient(135deg,#14532d,#166534);">
                <i class="fas fa-leaf" style="margin-right:6px;opacity:0.7;"></i>Stock Carbone 2023
            </div>
            <div class="popup-body">
                <div class="row"><span class="label">Classe</span><span class="value">${props.libelle || props.class_code || '-'}</span></div>
                <div class="row"><span class="label">Ann\u00e9e</span><span class="value">${props.annee || '2023'}</span></div>
                <div class="row">
                    <span class="label">Stock carbone</span>
                    <span class="value" style="color:#166534;font-weight:700;">
                        ${stock ? stock.toLocaleString('fr') + ' tCO\u2082/ha' : '-'}
                    </span>
                </div>
                <div class="row"><span class="label">Superficie</span><span class="value">${sup ? sup.toLocaleString('fr', {maximumFractionDigits: 1}) + ' ha' : '-'}</span></div>
                <div class="row" style="border-top:2px solid #dcfce7;padding-top:6px;margin-top:2px;">
                    <span class="label" style="font-weight:600;">Total carbone</span>
                    <span class="value" style="color:#14532d;font-weight:800;font-size:13px;">
                        ${totalCarbone > 0 ? totalCarbone.toLocaleString('fr') + ' tCO\u2082' : '-'}
                    </span>
                </div>
            </div>`;
    },

    foret(props) {
        return `
            <div class="popup-header">${props.nom || 'Foret classee'}</div>
            <div class="popup-body">
                <div class="row"><span class="label">Code</span><span class="value">${props.code || '-'}</span></div>
                <div class="row"><span class="label">Superficie legale</span><span class="value">${props.superficie_legale_ha ? props.superficie_legale_ha.toLocaleString('fr') + ' ha' : '-'}</span></div>
                <div class="row"><span class="label">Gestion</span><span class="value">${props.autorite_gestion || '-'}</span></div>
                ${this._targetBtn(props.code)}
            </div>`;
    },

    placette(props) {
        return `
            <div class="popup-header">Placette ${props.code_placette || ''}</div>
            <div class="popup-body">
                <div class="row"><span class="label">Foret</span><span class="value">${props.foret_nom || '-'}</span></div>
                <div class="row"><span class="label">Annee</span><span class="value">${props.annee_mesure || '-'}</span></div>
                <div class="row"><span class="label">Biomasse</span><span class="value">${props.biomasse_tonne_ha ? props.biomasse_tonne_ha + ' t/ha' : '-'}</span></div>
                <div class="row"><span class="label">Carbone</span><span class="value">${props.stock_carbone_mesure ? props.stock_carbone_mesure + ' tCO2/ha' : '-'}</span></div>
            </div>`;
    },
};
