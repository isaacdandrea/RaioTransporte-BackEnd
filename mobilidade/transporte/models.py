from django.db import models
#from django.contrib.gis.db import models as gis_models

class Agency(models.Model):
    agency_id = models.CharField(max_length=100, primary_key=True)
    agency_name = models.CharField(max_length=255)
    agency_url = models.URLField()
    agency_timezone = models.CharField(max_length=100)
    agency_lang = models.CharField(max_length=10, null=True, blank=True)
    agency_phone = models.CharField(max_length=50, null=True, blank=True)

class Calendar(models.Model):
    service_id = models.CharField(max_length=100, primary_key=True)
    monday = models.BooleanField()
    tuesday = models.BooleanField()
    wednesday = models.BooleanField()
    thursday = models.BooleanField()
    friday = models.BooleanField()
    saturday = models.BooleanField()
    sunday = models.BooleanField()
    start_date = models.DateField()
    end_date = models.DateField()

class Route(models.Model):
    route_id = models.CharField(max_length=100, primary_key=True)
    agency = models.ForeignKey(Agency, on_delete=models.SET_NULL, null=True)
    route_short_name = models.CharField(max_length=50)
    route_long_name = models.CharField(max_length=255)
    route_type = models.IntegerField()

class Stop(models.Model):
    stop_id = models.CharField(max_length=100, primary_key=True)
    stop_name = models.CharField(max_length=255)
    stop_lat = models.FloatField()
    stop_lon = models.FloatField()
    stop_desc = models.TextField(null=True, blank=True)
    #geom = gis_models.PointField(geography=True, null=True)

class Trip(models.Model):
    trip_id = models.CharField(max_length=100, primary_key=True)
    route = models.ForeignKey(Route, on_delete=models.CASCADE)
    service_id = models.CharField(max_length=100)
    trip_headsign = models.CharField(max_length=255, null=True, blank=True)
    direction_id = models.IntegerField(null=True, blank=True)
    shape_id = models.CharField(max_length=100, null=True, blank=True)

class StopTime(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    stop = models.ForeignKey(Stop, on_delete=models.CASCADE)
    arrival_time = models.TimeField()
    departure_time = models.TimeField()
    stop_sequence = models.IntegerField()

    class Meta:
        unique_together = ('trip', 'stop_sequence')

class Shape(models.Model):
    shape_id = models.CharField(max_length=100)
    shape_pt_lat = models.FloatField()
    shape_pt_lon = models.FloatField()
    shape_pt_sequence = models.IntegerField()

    class Meta:
        unique_together = ('shape_id', 'shape_pt_sequence')

class FareAttribute(models.Model):
    fare_id = models.CharField(max_length=100, primary_key=True)
    price = models.DecimalField(max_digits=6, decimal_places=2)
    currency_type = models.CharField(max_length=10)
    payment_method = models.IntegerField()
    transfers = models.IntegerField(null=True, blank=True)
    agency = models.ForeignKey(Agency, on_delete=models.SET_NULL, null=True)

class FareRule(models.Model):
    fare = models.ForeignKey(FareAttribute, on_delete=models.CASCADE)
    route = models.ForeignKey(Route, on_delete=models.CASCADE)
    origin_id = models.CharField(max_length=100, null=True, blank=True)
    destination_id = models.CharField(max_length=100, null=True, blank=True)
    contains_id = models.CharField(max_length=100, null=True, blank=True)

class Frequency(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    start_time = models.TimeField()
    end_time = models.TimeField()
    headway_secs = models.IntegerField()
