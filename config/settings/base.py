import os
import sys
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ──────────────────────────────────────────────
# Chargement du fichier .env (développement local)
# En production (Render/Railway/Neon), les variables sont fournies par
# l'hébergeur : load_dotenv() n'écrase pas les variables déjà définies.
# ──────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

# ──────────────────────────────────────────────
# GDAL / GEOS / PROJ — auto-détection par OS
# ──────────────────────────────────────────────
if sys.platform == 'win32':
    # Ajout du dossier bin de votre PostgreSQL portable au PATH système
    os.environ['PATH'] = r'C:\pgsql\bin' + ';' + os.environ.get('PATH', '')
    
    # Détection automatique de la DLL GDAL présente dans votre dossier bin
    import glob
    gdal_dlls = glob.glob(r'C:\pgsql\bin\libgdal-*.dll')
    if gdal_dlls:
        GDAL_LIBRARY_PATH = gdal_dlls[0]
    else:
        GDAL_LIBRARY_PATH = r'C:\pgsql\bin\libgdal-35.dll' # Valeur de secours
        
    GEOS_LIBRARY_PATH = r'C:\pgsql\bin\libgeos_c.dll'
    
    # Chemins vers les données partagées du bundle PostGIS
    os.environ.setdefault('GDAL_DATA', r'C:\pgsql\share\gdal')
    
    # Détection automatique du dossier proj (contenant proj.db)
    proj_dirs = glob.glob(r'C:\pgsql\share\contrib\postgis-*\proj')
    proj_dir = proj_dirs[0] if proj_dirs else r'C:\pgsql\share\contrib\postgis-3.4\proj'
    # PROJ 9 (livré avec GDAL 3.9) lit PROJ_DATA en priorité ; PROJ_LIB est
    # l'ancien nom conservé pour compatibilité. Sans PROJ_DATA, les reprojections
    # (ex. calcul de superficie en UTM dans OccupationSol.save) échouent
    # silencieusement -> superficie_ha/stock_carbone NULL -> stats à 0.
    # Affectation directe (pas setdefault) pour écraser une valeur périmée.
    os.environ['PROJ_DATA'] = proj_dir
    os.environ['PROJ_LIB'] = proj_dir


# ──────────────────────────────────────────────
# Sécurité
# ──────────────────────────────────────────────
SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-l+b%vcsa1=mqh1xrc023&g(%!_qye0#11g_3r+5_wu4ho%fvhe',
)

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Application definition
INSTALLED_APPS = [
    # Admin theme
    'jazzmin',
    # Django core
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',
    # Third-party
    'rest_framework',
    'rest_framework_gis',
    'rest_framework.authtoken',
    'django_filters',
    'corsheaders',
    'leaflet',
    'crispy_forms',
    'crispy_bootstrap5',
    # Project apps
    'apps.accounts',
    'apps.carbone',
    'apps.geodata',
    'apps.analysis',
]

MIDDLEWARE = [
    'django.middleware.gzip.GZipMiddleware',
    'django.middleware.http.ConditionalGetMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'frontend' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# ──────────────────────────────────────────────
# Database — PostGIS
# ──────────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': os.environ.get('DB_NAME', 'api_geo_db'),
        'USER': os.environ.get('DB_USER', 'PC 2'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}


# Custom user model
AUTH_USER_MODEL = 'accounts.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Abidjan'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'frontend' / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files (uploaded shapefiles)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
}

# JWT settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=12),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
}

# CORS
CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]
CORS_ALLOW_ALL_ORIGINS = True  # Dev only — overridden in production.py

# Leaflet configuration
LEAFLET_CONFIG = {
    'DEFAULT_CENTER': (6.5, -5.5),
    'DEFAULT_ZOOM': 10,
    'MIN_ZOOM': 5,
    'MAX_ZOOM': 18,
    'TILES': [],
}

# Crispy forms
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

# Jazzmin admin theme
JAZZMIN_SETTINGS = {
    'site_title': 'API.GEO.Carbone',
    'site_header': 'GEO.Carbone',
    'site_brand': 'GEO.Carbone',
    'welcome_sign': 'Administration API.GEO.Carbone',
    'site_logo': None,
    'login_logo': None,
    'site_icon': None,
    'copyright': "API.GEO.Carbone - Departement d'Oume",
    'search_model': ['carbone.ForetClassee', 'carbone.OccupationSol'],
    'topmenu_links': [
        {'name': 'Carte', 'url': '/', 'new_window': True},
        {'name': 'API', 'url': '/api/v1/', 'new_window': True},
    ],
    'show_sidebar': True,
    'navigation_expanded': True,
    'icons': {
        'accounts.User': 'fas fa-user',
        'carbone.ForetClassee': 'fas fa-tree',
        'carbone.OccupationSol': 'fas fa-layer-group',
        'carbone.NomenclatureCouvert': 'fas fa-palette',
        'carbone.ZoneEtude': 'fas fa-map',
        'carbone.Placette': 'fas fa-map-pin',
        'carbone.Infrastructure': 'fas fa-road',
    },
}

# File upload limits
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50 MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800

# Shapefile data path
# ──────────────────────────────────────────────
# Mistral AI
# ──────────────────────────────────────────────
MISTRAL_API_KEY = os.environ.get('MISTRAL_API_KEY', '')

SHAPEFILE_DATA_DIR = os.environ.get(
    'SHAPEFILE_DATA_DIR', r'C:\Users\LENOVO\Pictures\DATA YEO ALL'
)
