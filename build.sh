#!/usr/bin/env bash
# ===== Script de build pour Render =====
set -o errexit

# Installer les dependances systeme pour GeoDjango (GDAL, GEOS, PROJ)
apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    && rm -rf /var/lib/apt/lists/*

# Installer les dependances Python
pip install --upgrade pip
pip install -r requirements.txt

# Attendre que la base soit joignable PUIS activer l'extension PostGIS.
# Retry sur erreur DNS/connexion : sur Render free-tier la base peut mettre
# du temps a provisionner (ou son DNS a se propager) apres (re)creation.
python -c "
import dj_database_url, psycopg2, os, sys, time

db = dj_database_url.config(default=os.environ.get('DATABASE_URL'))
if not db or not db.get('HOST'):
    print('ERREUR: DATABASE_URL non defini ou invalide.')
    sys.exit(1)

last = None
for attempt in range(12):  # ~2 min max (12 x 10s)
    try:
        conn = psycopg2.connect(
            dbname=db['NAME'], user=db['USER'], password=db['PASSWORD'],
            host=db['HOST'], port=db['PORT'], connect_timeout=10,
        )
        conn.autocommit = True
        conn.cursor().execute('CREATE EXTENSION IF NOT EXISTS postgis;')
        conn.close()
        print('PostGIS extension activated.')
        break
    except Exception as e:
        last = e
        print(f'Base pas encore joignable (tentative {attempt + 1}/12): {e}')
        time.sleep(10)
else:
    print('ERREUR: base injoignable apres ~2 min.')
    print('--> Verifiez sur le dashboard Render que la base PostgreSQL existe')
    print('    et que DATABASE_URL pointe vers le bon hote. Sur le plan gratuit,')
    print('    une base inactive depuis 90 jours est supprimee : recreez-la.')
    print(f'Derniere erreur: {last}')
    sys.exit(1)
"

# Appliquer les migrations
python manage.py migrate --no-input

# Collecter les fichiers statiques
python manage.py collectstatic --no-input

# Pre-construire le cache GeoJSON si des donnees existent en base
# (les fichiers media/geocache/ du repo sont aussi deployes comme fallback)
python manage.py seed_nomenclature 2>/dev/null || echo "Nomenclature: skipped or already seeded"
python manage.py prebuild_geojson 2>/dev/null || echo "GeoCache prebuild: skipped (no data in DB yet)"

# ===== Auto-creation superuser depuis variables d'environnement =====
# Wrapped with retry logic: Render free-tier DB may drop connections during build
python -c "
import django, os, time
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()
from django.contrib.auth import get_user_model
from django.db import connection

User = get_user_model()
username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@admin.com')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')

for attempt in range(5):
    try:
        connection.ensure_connection()
        if password and not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, email=email, password=password)
            print(f'Superuser {username} created.')
        else:
            print('Superuser already exists or no password set.')
        break
    except Exception as e:
        print(f'DB not ready (attempt {attempt+1}/5): {e}')
        if attempt < 4:
            connection.close()
            time.sleep(5)
        else:
            print('Skipping superuser creation (DB unavailable). Will retry on next deploy.')
"
