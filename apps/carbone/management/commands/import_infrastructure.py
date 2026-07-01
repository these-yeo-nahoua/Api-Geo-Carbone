import os
import geopandas as gpd
from django.core.management.base import BaseCommand
from django.contrib.gis.geos import GEOSGeometry
from django.conf import settings
from apps.carbone.models import Infrastructure


INFRA_FILES = [
    {
        'file': 'Routes_Oum\u00e9.shp',
        'type_infra': 'ROUTE',
        'name_col': ['NOM', 'Nom', 'NAME', 'ROUTE_NAME'],
    },
    {
        'file': 'Res\u00e9au_hidrographique_Oum\u00e9.shp',
        'type_infra': 'HYDROGRAPHIE',
        'name_col': ['NOM', 'Nom', 'NAME', 'NOM_COURS'],
    },
    {
        'file': 'Chef_lieu_sous_prefecture.shp',
        'type_infra': 'CHEF_LIEU_SP',
        'name_col': ['NOM', 'Nom', 'NAME', 'NOM_SP'],
    },
    {
        'file': 'Localit\u00e9s_d\u00e9partement_Oum\u00e9.shp',
        'type_infra': 'LOCALITE',
        'name_col': ['NOM', 'Nom', 'NAME', 'NOM_LOC', 'LOCALITE'],
    },
]


class Command(BaseCommand):
    help = 'Import infrastructure data (roads, rivers, towns)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--data-dir',
            default=os.path.join(settings.SHAPEFILE_DATA_DIR, 'SIG_DATA'),
        )
        parser.add_argument('--clear', action='store_true')

    def handle(self, *args, **options):
        data_dir = options['data_dir']

        if options['clear']:
            Infrastructure.objects.all().delete()
            self.stdout.write('Cleared all infrastructure data.')

        for infra in INFRA_FILES:
            shp_path = os.path.join(data_dir, infra['file'])
            if not os.path.exists(shp_path):
                self.stdout.write(self.style.WARNING(f'  SKIP: {infra["file"]} not found'))
                continue

            self.stdout.write(f'  Importing: {infra["file"]} as {infra["type_infra"]}')
            try:
                gdf = gpd.read_file(shp_path)
                # Certains shapefiles (ex. Localites_departement_Oume) n'ont pas
                # de fichier .prj -> CRS absent. Les donnees SIG d'Oume sont en
                # UTM Zone 30N (EPSG:32630), comme les autres couches SIG_DATA.
                if gdf.crs is None:
                    gdf = gdf.set_crs(epsg=32630)
                    self.stdout.write(self.style.WARNING(
                        '    CRS absent (.prj manquant) -> EPSG:32630 assume'))
                gdf = gdf.to_crs(epsg=4326)
                imported = 0

                for _, row in gdf.iterrows():
                    try:
                        geom = GEOSGeometry(row.geometry.wkt, srid=4326)

                        nom = ''
                        for col in infra['name_col']:
                            if col in gdf.columns and row[col] and str(row[col]) != 'nan':
                                nom = str(row[col])
                                break

                        extra = {}
                        for col in gdf.columns:
                            if col != 'geometry':
                                val = row[col]
                                if val is not None and str(val) != 'nan':
                                    extra[col] = str(val)

                        Infrastructure.objects.create(
                            type_infra=infra['type_infra'],
                            nom=nom,
                            geom=geom,
                            donnees=extra,
                        )
                        imported += 1
                    except Exception:
                        pass

                self.stdout.write(self.style.SUCCESS(f'    Imported: {imported} features'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'    ERROR: {e}'))

        self.stdout.write(self.style.SUCCESS('Infrastructure import complete.'))
