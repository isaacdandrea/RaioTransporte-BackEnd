import os
import csv
from datetime import datetime
from django.db import transaction
from transporte.models import (
    Agency, Calendar, Stop, Route, Trip, StopTime, Shape,
    FareAttribute, FareRule, Frequency
)

def parse_time(value):
    try:
        return datetime.strptime(value, "%H:%M:%S").time()
    except:
        return None

def parse_date(value):
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except:
        return None

#@transaction.atomic
def importar_gtfs(caminho_gtfs):
    print(f"🔄 Iniciando importação GTFS de: {caminho_gtfs}")

    def open_file(nome):
        return open(os.path.join(caminho_gtfs, nome), encoding='utf-8')

    # Agency
    with open_file('agency.txt') as f:
        agencies = []
        for row in csv.DictReader(f):
            agencies.append(Agency(
                agency_id=row['agency_id'],
                agency_name=row['agency_name'],
                agency_url=row['agency_url'],
                agency_timezone=row['agency_timezone'],
                agency_lang=row.get('agency_lang'),
                agency_phone=row.get('agency_phone'),
            ))
        Agency.objects.bulk_create(agencies, ignore_conflicts=True)
        print(f"✅ Agency: {len(agencies)} registros importados.")

    # Calendar
    with open_file('calendar.txt') as f:
        calendars = []
        for row in csv.DictReader(f):
            calendars.append(Calendar(
                service_id=row['service_id'],
                monday=row['monday'] == '1',
                tuesday=row['tuesday'] == '1',
                wednesday=row['wednesday'] == '1',
                thursday=row['thursday'] == '1',
                friday=row['friday'] == '1',
                saturday=row['saturday'] == '1',
                sunday=row['sunday'] == '1',
                start_date=parse_date(row['start_date']),
                end_date=parse_date(row['end_date']),
            ))
        Calendar.objects.bulk_create(calendars, ignore_conflicts=True)
        print(f"✅ Calendar: {len(calendars)} registros importados.")

    # Stops
    with open_file('stops.txt') as f:
        stops = []
        for row in csv.DictReader(f):
            stops.append(Stop(
                stop_id=row['stop_id'],
                stop_name=row['stop_name'],
                stop_lat=float(row['stop_lat']),
                stop_lon=float(row['stop_lon']),
                stop_desc=row.get('stop_desc'),
            ))
        Stop.objects.bulk_create(stops, ignore_conflicts=True)
        print(f"✅ Stops: {len(stops)} registros importados.")

    # Routes
    with open_file('routes.txt') as f:
        routes = []
        for row in csv.DictReader(f):
            routes.append(Route(
                route_id=row['route_id'],
                agency_id=row.get('agency_id'),
                route_short_name=row['route_short_name'],
                route_long_name=row['route_long_name'],
                route_type=int(row['route_type']),
            ))
        Route.objects.bulk_create(routes, ignore_conflicts=True)
        print(f"✅ Routes: {len(routes)} registros importados.")

    # Trips
    with open_file('trips.txt') as f:
        trips = []
        for row in csv.DictReader(f):
            trips.append(Trip(
                trip_id=row['trip_id'],
                route_id=row['route_id'],
                service_id=row['service_id'],
                trip_headsign=row.get('trip_headsign'),
                direction_id=int(row.get('direction_id', 0)),
                shape_id=row.get('shape_id'),
            ))
        Trip.objects.bulk_create(trips, ignore_conflicts=True)
        print(f"✅ Trips: {len(trips)} registros importados.")

    # StopTimes
    with open_file('stop_times.txt') as f:
        stoptimes = []
        for row in csv.DictReader(f):
            stoptimes.append(StopTime(
                trip_id=row['trip_id'],
                stop_id=row['stop_id'],
                arrival_time=parse_time(row['arrival_time']),
                departure_time=parse_time(row['departure_time']),
                stop_sequence=int(row['stop_sequence']),
            ))
        StopTime.objects.bulk_create(stoptimes, ignore_conflicts=True)
        print(f"✅ StopTimes: {len(stoptimes)} registros importados.")

    # Shapes
    with open_file('shapes.txt') as f:
        shapes = []
        for row in csv.DictReader(f):
            shapes.append(Shape(
                shape_id=row['shape_id'],
                shape_pt_lat=float(row['shape_pt_lat']),
                shape_pt_lon=float(row['shape_pt_lon']),
                shape_pt_sequence=int(row['shape_pt_sequence']),
            ))
        Shape.objects.bulk_create(shapes, ignore_conflicts=True)
        print(f"✅ Shapes: {len(shapes)} registros importados.")

    # FareAttributes
    with open_file('fare_attributes.txt') as f:
        fares = []
        for row in csv.DictReader(f):
            fares.append(FareAttribute(
                fare_id=row['fare_id'],
                price=row['price'],
                currency_type=row['currency_type'],
                payment_method=int(row['payment_method']),
                transfers=int(row['transfers']),
                agency_id=row.get('agency_id'),
            ))
        FareAttribute.objects.bulk_create(fares, ignore_conflicts=True)
        print(f"✅ FareAttributes: {len(fares)} registros importados.")

    # FareRules
    with open_file('fare_rules.txt') as f:
        rules = []
        for row in csv.DictReader(f):
            rules.append(FareRule(
                fare_id=row['fare_id'],
                route_id=row['route_id'],
                origin_id=row.get('origin_id'),
                destination_id=row.get('destination_id'),
                contains_id=row.get('contains_id'),
            ))
        FareRule.objects.bulk_create(rules, ignore_conflicts=True)
        print(f"✅ FareRules: {len(rules)} registros importados.")

    # Frequencies
    with open_file('frequencies.txt') as f:
        freqs = []
        for row in csv.DictReader(f):
            freqs.append(Frequency(
                trip_id=row['trip_id'],
                start_time=parse_time(row['start_time']),
                end_time=parse_time(row['end_time']),
                headway_secs=int(row['headway_secs']),
            ))
        Frequency.objects.bulk_create(freqs, ignore_conflicts=True)
        print(f"✅ Frequencies: {len(freqs)} registros importados.")

    print("🎉 Importação GTFS concluída com sucesso.")


def importar_shapes(caminho_gtfs):
    from transporte.models import Shape
    import os, csv

    def open_file(nome):
        return open(os.path.join(caminho_gtfs, nome), encoding='utf-8')

    print("🚀 Iniciando importação de Shapes (lotes de 99)...")

    shapes = []
    total = 0
    batch_size = 99

    with open_file('shapes.txt') as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            shape = Shape(
                shape_id=row['shape_id'],
                shape_pt_lat=float(row['shape_pt_lat']),
                shape_pt_lon=float(row['shape_pt_lon']),
                shape_pt_sequence=int(row['shape_pt_sequence']),
            )
            shapes.append(shape)

            # Quando atingir o tamanho do lote, envia ao banco
            if len(shapes) >= batch_size:
                Shape.objects.bulk_create(shapes, ignore_conflicts=True)
                total += len(shapes)
                print(f"✅ Lote de {len(shapes)} shapes importados (total até agora: {total})")
                shapes = []

        # Importar qualquer restante final
        if shapes:
            Shape.objects.bulk_create(shapes, ignore_conflicts=True)
            total += len(shapes)
            print(f"✅ Último lote de {len(shapes)} shapes importados (total: {total})")

    print(f"🎉 Importação finalizada. Total de shapes importados: {total}")

def importar_fare_attributes(caminho_gtfs):
    from transporte.models import FareAttribute
    import os, csv

    def open_file(nome):
        return open(os.path.join(caminho_gtfs, nome), encoding='utf-8')

    print("🚀 Iniciando importação de FareAttributes (lotes de 499)...")

    fares = []
    total = 0
    batch_size = 499

    with open_file('fare_attributes.txt') as f:
        for row in csv.DictReader(f):
            fares.append(FareAttribute(
                fare_id=row['fare_id'],
                price=row['price'],
                currency_type=row['currency_type'],
                payment_method=int(row['payment_method']),
                transfers=int(row['transfers']) if row['transfers'].isdigit() else None,
                agency_id=row.get('agency_id'),
            ))

            if len(fares) >= batch_size:
                FareAttribute.objects.bulk_create(fares, ignore_conflicts=True)
                total += len(fares)
                print(f"✅ Lote de {len(fares)} fare_attributes importados (total: {total})")
                fares = []

        if fares:
            FareAttribute.objects.bulk_create(fares, ignore_conflicts=True)
            total += len(fares)
            print(f"✅ Último lote de {len(fares)} fare_attributes importados (total: {total})")

    print(f"🎉 Importação finalizada. Total de fare_attributes: {total}")

def importar_fare_rules(caminho_gtfs):
    from transporte.models import FareRule
    import os, csv

    def open_file(nome):
        return open(os.path.join(caminho_gtfs, nome), encoding='utf-8')

    print("🚀 Iniciando importação de FareRules (lotes de 499)...")

    rules = []
    total = 0
    batch_size = 499

    with open_file('fare_rules.txt') as f:
        for row in csv.DictReader(f):
            rules.append(FareRule(
                fare_id=row['fare_id'],
                route_id=row['route_id'],
                origin_id=row.get('origin_id'),
                destination_id=row.get('destination_id'),
                contains_id=row.get('contains_id'),
            ))

            if len(rules) >= batch_size:
                FareRule.objects.bulk_create(rules, ignore_conflicts=True)
                total += len(rules)
                print(f"✅ Lote de {len(rules)} fare_rules importados (total: {total})")
                rules = []

        if rules:
            FareRule.objects.bulk_create(rules, ignore_conflicts=True)
            total += len(rules)
            print(f"✅ Último lote de {len(rules)} fare_rules importados (total: {total})")

    print(f"🎉 Importação finalizada. Total de fare_rules: {total}")

def importar_frequencies(caminho_gtfs):
    from transporte.models import Frequency
    import os, csv
    from datetime import datetime

    def open_file(nome):
        return open(os.path.join(caminho_gtfs, nome), encoding='utf-8')

    def parse_time(value):
        try:
            return datetime.strptime(value, "%H:%M:%S").time()
        except:
            return None

    print("🚀 Iniciando importação de Frequencies (lotes de 499)...")

    freqs = []
    total = 0
    batch_size = 499

    with open_file('frequencies.txt') as f:
        for row in csv.DictReader(f):
            freqs.append(Frequency(
                trip_id=row['trip_id'],
                start_time=parse_time(row['start_time']),
                end_time=parse_time(row['end_time']),
                headway_secs=int(row['headway_secs']),
            ))

            if len(freqs) >= batch_size:
                Frequency.objects.bulk_create(freqs, ignore_conflicts=True)
                total += len(freqs)
                print(f"✅ Lote de {len(freqs)} frequencies importados (total: {total})")
                freqs = []

        if freqs:
            Frequency.objects.bulk_create(freqs, ignore_conflicts=True)
            total += len(freqs)
            print(f"✅ Último lote de {len(freqs)} frequencies importados (total: {total})")

    print(f"🎉 Importação finalizada. Total de frequencies: {total}")
