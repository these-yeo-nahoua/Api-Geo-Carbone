from django.contrib.gis.db import models
from .constants import ANNEE_CHOICES


class ZoneEtude(models.Model):
    """Limites administratives (departement, sous-prefectures, localites)."""

    TYPE_CHOICES = [
        ('DEPARTEMENT', 'Departement'),
        ('SOUS_PREFECTURE', 'Sous-prefecture'),
        ('LOCALITE', 'Localite'),
        ('CHEF_LIEU', 'Chef-lieu'),
    ]

    nom = models.CharField(max_length=150, verbose_name='Nom')
    type_zone = models.CharField(
        max_length=50,
        choices=TYPE_CHOICES,
        default='DEPARTEMENT',
        verbose_name='Type de zone',
    )
    niveau = models.IntegerField(
        default=1,
        help_text='Niveau hierarchique (1=Departement, 2=S/P, 3=Localite)',
    )
    geom = models.MultiPolygonField(srid=4326, verbose_name='Geometrie')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Zone d'etude"
        verbose_name_plural = "Zones d'etude"
        ordering = ['niveau', 'nom']

    def __str__(self):
        return f"{self.nom} ({self.get_type_zone_display()})"


class ForetClassee(models.Model):
    """Entites geographiques fixes : les 6 forets classees du departement d'Oume."""

    code = models.CharField(max_length=20, unique=True, verbose_name='Code')
    nom = models.CharField(max_length=200, verbose_name='Nom complet')
    superficie_legale_ha = models.FloatField(
        null=True, blank=True,
        verbose_name='Superficie legale (ha)',
    )
    statut_juridique = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name='Statut juridique',
    )
    date_classement = models.DateField(
        null=True, blank=True,
        verbose_name='Date de classement',
    )
    autorite_gestion = models.CharField(
        max_length=200, blank=True, default='',
        verbose_name='Autorite de gestion',
    )
    geom = models.MultiPolygonField(srid=4326, verbose_name='Geometrie')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Foret classee'
        verbose_name_plural = 'Forets classees'
        ordering = ['code']
        indexes = [
            models.Index(fields=['code']),
        ]

    def __str__(self):
        return self.nom


class NomenclatureCouvert(models.Model):
    """Referentiel des types de couverture vegetale."""

    code = models.CharField(max_length=30, unique=True, verbose_name='Code')
    libelle_fr = models.CharField(max_length=100, verbose_name='Libelle francais')
    stock_carbone_reference = models.FloatField(
        null=True, blank=True,
        verbose_name='Stock carbone reference (tCO2/ha)',
    )
    couleur_hex = models.CharField(
        max_length=7,
        verbose_name='Couleur (hex)',
        help_text='Format #RRGGBB',
    )
    ordre_affichage = models.IntegerField(
        default=0,
        verbose_name='Ordre dans la legende',
    )

    class Meta:
        verbose_name = 'Nomenclature de couvert'
        verbose_name_plural = 'Nomenclatures de couvert'
        ordering = ['ordre_affichage']

    def __str__(self):
        return f"{self.libelle_fr} ({self.code})"


class OccupationSol(models.Model):
    """Table centrale : donnees temporelles d'occupation du sol."""

    foret = models.ForeignKey(
        ForetClassee,
        on_delete=models.CASCADE,
        related_name='occupations',
        verbose_name='Foret classee',
    )
    nomenclature = models.ForeignKey(
        NomenclatureCouvert,
        on_delete=models.PROTECT,
        related_name='occupations',
        verbose_name='Type de couvert',
    )
    annee = models.SmallIntegerField(
        choices=ANNEE_CHOICES,
        verbose_name="Annee d'observation",
    )
    superficie_ha = models.FloatField(
        null=True, blank=True,
        verbose_name='Superficie (ha)',
    )
    stock_carbone_calcule = models.FloatField(
        null=True, blank=True,
        verbose_name='Stock carbone (tCO2/ha)',
    )
    source_donnee = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name='Source des donnees',
    )
    fiabilite_pct = models.FloatField(
        null=True, blank=True,
        verbose_name='Fiabilite (%)',
    )
    notes_admin = models.TextField(blank=True, default='', verbose_name='Notes')
    geom = models.MultiPolygonField(srid=4326, verbose_name='Geometrie')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Occupation du sol'
        verbose_name_plural = 'Occupations du sol'
        ordering = ['annee', 'foret', 'nomenclature']
        indexes = [
            models.Index(fields=['annee']),
            models.Index(fields=['foret', 'annee']),
            models.Index(fields=['nomenclature', 'annee']),
            models.Index(fields=['foret', 'nomenclature', 'annee']),
        ]

    def __str__(self):
        return f"{self.foret.code} - {self.nomenclature.code} ({self.annee})"

    def save(self, *args, **kwargs):
        # 1) Persister d'abord la geometrie (et obtenir un id).
        super().save(*args, **kwargs)

        recompute = False

        # 2) Superficie (ha) calculee cote PostGIS via geography (geodesique).
        #    On evite volontairement geom.transform() cote client : sur Windows,
        #    la DLL GDAL ne "voit" pas PROJ_DATA defini depuis Python et la
        #    reprojection echoue silencieusement -> superficie NULL -> stats a 0.
        #    ST_Area(::geography) est fait par le serveur, portable (local + Neon).
        if self.geom and not self.superficie_ha:
            try:
                from django.db import connection
                with connection.cursor() as cur:
                    cur.execute(
                        "SELECT ST_Area(geom::geography) / 10000.0 "
                        "FROM carbone_occupationsol WHERE id = %s",
                        [self.pk],
                    )
                    row = cur.fetchone()
                if row and row[0] is not None:
                    self.superficie_ha = row[0]
                    recompute = True
            except Exception:
                pass

        # 3) Stock TOTAL du polygone (tCO2) = superficie (ha) x reference (tCO2/ha).
        #    Les stats/evolution SOMMENT ce champ comme total tCO2.
        if self.superficie_ha and self.nomenclature_id and not self.stock_carbone_calcule:
            try:
                ref = self.nomenclature.stock_carbone_reference
                if ref:
                    self.stock_carbone_calcule = self.superficie_ha * ref
                    recompute = True
            except Exception:
                pass

        if recompute:
            super().save(update_fields=['superficie_ha', 'stock_carbone_calcule'])


class Placette(models.Model):
    """Points de mesure terrain."""

    foret = models.ForeignKey(
        ForetClassee,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='placettes',
        verbose_name='Foret classee',
    )
    code_placette = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='Code placette',
    )
    annee_mesure = models.SmallIntegerField(
        null=True, blank=True,
        verbose_name='Annee de mesure',
    )
    type_foret_observe = models.CharField(
        max_length=100, blank=True, default='',
        verbose_name='Type de foret observe',
    )
    biomasse_tonne_ha = models.FloatField(
        null=True, blank=True,
        verbose_name='Biomasse (t/ha)',
    )
    stock_carbone_mesure = models.FloatField(
        null=True, blank=True,
        verbose_name='Stock carbone mesure (tCO2/ha)',
    )
    donnees = models.JSONField(
        default=dict, blank=True,
        verbose_name='Donnees supplementaires',
    )
    geom = models.PointField(srid=4326, verbose_name='Geometrie')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Placette'
        verbose_name_plural = 'Placettes'

    def __str__(self):
        return self.code_placette or f"Placette #{self.pk}"


class Infrastructure(models.Model):
    """Donnees contextuelles : routes, hydrographie, chefs-lieux."""

    TYPE_CHOICES = [
        ('ROUTE', 'Route'),
        ('HYDROGRAPHIE', 'Hydrographie'),
        ('CHEF_LIEU_DEPT', 'Chef-lieu Departement'),
        ('CHEF_LIEU_SP', 'Chef-lieu Sous-prefecture'),
        ('LOCALITE', 'Localite'),
    ]

    type_infra = models.CharField(
        max_length=50,
        choices=TYPE_CHOICES,
        verbose_name="Type d'infrastructure",
    )
    nom = models.CharField(max_length=200, blank=True, default='', verbose_name='Nom')
    categorie = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='Categorie',
    )
    geom = models.GeometryField(srid=4326, verbose_name='Geometrie')
    donnees = models.JSONField(
        default=dict, blank=True,
        verbose_name='Donnees supplementaires',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Infrastructure'
        verbose_name_plural = 'Infrastructures'
        ordering = ['type_infra', 'nom']
        indexes = [
            models.Index(fields=['type_infra']),
        ]

    def __str__(self):
        return f"{self.get_type_infra_display()} - {self.nom or 'Sans nom'}"
