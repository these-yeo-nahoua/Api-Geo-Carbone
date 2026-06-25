/**
 * Sidebar - Toggle, tabs, responsive
 */
const Sidebar = {
    init() {
        const toggle = document.getElementById('sidebar-toggle');
        const close = document.getElementById('sidebar-close');
        const sidebar = document.getElementById('sidebar');

        // Classe de masquage hors-écran (alignée sur le template — sidebar flottante)
        const HIDDEN = '-translate-x-[120%]';

        if (toggle) {
            toggle.addEventListener('click', () => {
                sidebar.classList.toggle('open');
                sidebar.classList.toggle(HIDDEN);
            });
        }

        if (close) {
            close.addEventListener('click', () => {
                sidebar.classList.remove('open');
                sidebar.classList.add(HIDDEN);
            });
        }

        // Tab switching
        document.querySelectorAll('.sidebar-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                const targetTab = e.currentTarget.dataset.tab;

                // Update tab buttons
                document.querySelectorAll('.sidebar-tab').forEach(t => {
                    t.classList.remove('active');
                    t.classList.add('text-gray-400');
                    t.classList.remove('text-green-700');
                });
                e.currentTarget.classList.add('active');
                e.currentTarget.classList.remove('text-gray-400');
                e.currentTarget.classList.add('text-green-700');

                // Show/hide tab content
                document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
                const content = document.getElementById(`tab-${targetTab}`);
                if (content) content.classList.remove('hidden');
            });
        });
    },
};
