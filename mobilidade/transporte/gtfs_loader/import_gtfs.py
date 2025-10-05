import os
import csv
from datetime import datetime
from django.db import transaction
from transporte.models import (
    Agency, Calendar, Stop, Route, Trip, StopTime, Shape,
    FareAttribute, FareRule, Frequency
)

# ---------- Leitor robusto (para cabeçalho entre aspas / BOM / delimitador) ----------
def smart_dict_reader(f):
    """Trata BOM, cabeçalho inteiro entre aspas e detecta delimitador , ; \t |."""
    first = f.readline()
    if not first:
        return iter([])

    header = first.strip().lstrip('\ufeff')
    if (header.startswith('"') and header.endswith('"')) or (header.startswith("'") and header.endswith("'")):
        header = header[1:-1]

    counts = {',': header.count(','), ';': header.count(';'), '\t': header.count('\t'), '|': header.count('|')}
    delim = max(counts, key=counts.get)
    if counts[delim] == 0:
        # fallback se não achar nada
        try:
            sample = header + "\n" + f.read(4096)
            f.seek(len(first))
            dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
            delim = dialect.delimiter
        except csv.Error:
            delim = ','

    fieldnames = [h.strip().lower() for h in header.split(delim)]
    rdr = csv.DictReader(f, fieldnames=fieldnames, delimiter=delim)

    def gen():
        for row in rdr:
            # pula possível 2ª linha de cabeçalho
            if row and all(((row[k] or '').strip().lower() == k) for k in fieldnames):
                continue
            yield { (k.strip().lower() if k else k): (v.strip() if isinstance(v, str) else v)
                    for k, v in row.items() }
    return gen()

def iterate_rows(f, robust=False):
    """Por padrão usa csv.DictReader; se robust=True, usa smart_dict_reader."""
    if robust:
        yield from smart_dict_reader(f)
    else:
        for row in csv.DictReader(f):
            yield row
# ------------------------------------------------------------------------------

def to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default

def to_float(v, default=None):
    try:
        if isinstance(v, str):
            v = v.replace(',', '.')
        return float(v)
    except (TypeError, ValueError):
        return default

def norm_str(v):
    """Normaliza para string comparável (evita mismatch int vs str em PKs)."""
    if v is None:
        return ""
    return str(v).strip()

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

@transaction.atomic
def importar_gtfs(caminho_gtfs):
    print(f"🔄 Iniciando importação GTFS de: {caminho_gtfs}")

    def open_file(nome):
        # newline='' recomendado no Windows; errors='replace' evita quebra por bytes inválidos
        return open(os.path.join(caminho_gtfs, nome), encoding='utf-8', newline='', errors='replace')

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
                stop_lat=to_float(row['stop_lat']),
                stop_lon=to_float(row['stop_lon']),
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
                route_type=to_int(row.get('route_type'), 3),  # default 3 (bus) se vier vazio
            ))
        Route.objects.bulk_create(routes, ignore_conflicts=True)
        print(f"✅ Routes: {len(routes)} registros importados.")

    # Conjunto de route_ids válidos (normalizado como string)
    route_ids_db = set(norm_str(x) for x in Route.objects.values_list('route_id', flat=True))

    # Trips — cria rotas "stub" quando necessário (sem descartar viagens)
    with open_file('trips.txt') as f:
        trips = []
        imported_trip_ids = set()

        stub_route_ids = set()   # route_ids faltantes (distintos) nas trips
        stub_routes = []         # objetos Route a criar por causa das trips
        stub_trip_count = 0      # número de trips que referiam rotas ausentes

        for row in iterate_rows(f, robust=True):
            rid = norm_str(row.get('route_id'))
            if rid not in route_ids_db:
                if rid and rid not in stub_route_ids:
                    stub_route_ids.add(rid)
                    stub_routes.append(Route(
                        route_id=rid,
                        agency_id=None,
                        route_short_name=rid,
                        route_long_name=f"(stub auto) {rid}",
                        route_type=3,
                    ))
                stub_trip_count += 1

            trip = Trip(
                trip_id=row['trip_id'],
                route_id=rid,
                service_id=row['service_id'],
                trip_headsign=(row.get('trip_headsign') or None),
                direction_id=to_int(row.get('direction_id'), 0),
                shape_id=row.get('shape_id'),
            )
            trips.append(trip)
            imported_trip_ids.add(norm_str(row['trip_id']))

        if stub_routes:
            Route.objects.bulk_create(stub_routes, ignore_conflicts=True)
            print(f"🧱 Routes stub criadas: {len(stub_routes)} (distintas). Ex.: {', '.join(sorted(list(stub_route_ids))[:10])}")
            route_ids_db.update(stub_route_ids)
        else:
            print("🧱 Routes stub criadas: 0")

        Trip.objects.bulk_create(trips, ignore_conflicts=True)
        print(f"✅ Trips: {len(trips)} registros importados. "
              f"({stub_trip_count} viagens referiam rotas ausentes e motivaram stub)")

    # StopTimes (verifica trip_id importado)
    with open_file('stop_times.txt') as f:
        stoptimes = []
        skipped_stoptimes = 0
        for row in csv.DictReader(f):
            tid = norm_str(row.get('trip_id'))
            if tid and tid not in imported_trip_ids:
                skipped_stoptimes += 1
                continue
            stoptimes.append(StopTime(
                trip_id=tid,
                stop_id=row['stop_id'],
                arrival_time=parse_time(row['arrival_time']),
                departure_time=parse_time(row['departure_time']),
                stop_sequence=to_int(row.get('stop_sequence')),
            ))
        StopTime.objects.bulk_create(stoptimes, ignore_conflicts=True)
        print(f"✅ StopTimes: {len(stoptimes)} registros importados.")
        if skipped_stoptimes:
            print(f"⚠️ StopTimes ignorados por trip_id não importado: {skipped_stoptimes}")

    # Shapes
    with open_file('shapes.txt') as f:
        shapes = []
        for row in csv.DictReader(f):
            shapes.append(Shape(
                shape_id=row['shape_id'],
                shape_pt_lat=to_float(row['shape_pt_lat']),
                shape_pt_lon=to_float(row['shape_pt_lon']),
                shape_pt_sequence=to_int(row.get('shape_pt_sequence')),
            ))
        Shape.objects.bulk_create(shapes, ignore_conflicts=True)
        print(f"✅ Shapes: {len(shapes)} registros importados.")

    # FareAttributes (importa do arquivo)
    with open_file('fare_attributes.txt') as f:
        fares = []
        for row in csv.DictReader(f):
            fares.append(FareAttribute(
                fare_id=row['fare_id'],
                price=row['price'],
                currency_type=row['currency_type'],
                payment_method=to_int(row.get('payment_method')),
                transfers=to_int(row.get('transfers')),
                agency_id=row.get('agency_id'),
            ))
        FareAttribute.objects.bulk_create(fares, ignore_conflicts=True)
        print(f"✅ FareAttributes: {len(fares)} registros importados.")

    # Base atual de fares + moeda padrão para stubs
    fare_ids_db = set(norm_str(x) for x in FareAttribute.objects.values_list('fare_id', flat=True))
    default_currency = FareAttribute.objects.order_by().values_list('currency_type', flat=True).first() or 'BRL'

    # FareRules — cria FareAttributes stub e (se preciso) Routes stub
    with open_file('fare_rules.txt') as f:
        rules = []
        stub_fare_ids = set()   # fare_ids faltantes (distintos) nas rules
        stub_fares = []         # FareAttributes a criar
        stub_rules_fare_count = 0  # quantas linhas de rule referiam fare ausente

        stub_rule_route_ids = set()  # route_ids faltantes detectados nas rules
        stub_rule_routes = []        # Routes a criar por causa das rules
        stub_rules_route_count = 0   # quantas rules referiam route ausente

        for row in csv.DictReader(f):
            fid = norm_str(row.get('fare_id'))
            rid = norm_str(row.get('route_id'))

            # garantir route
            if rid and rid not in route_ids_db:
                if rid not in stub_rule_route_ids:
                    stub_rule_route_ids.add(rid)
                    stub_rule_routes.append(Route(
                        route_id=rid,
                        agency_id=None,
                        route_short_name=rid,
                        route_long_name=f"(stub auto) {rid}",
                        route_type=3,
                    ))
                stub_rules_route_count += 1

            # garantir fare
            if fid and fid not in fare_ids_db:
                if fid not in stub_fare_ids:
                    stub_fare_ids.add(fid)
                    stub_fares.append(FareAttribute(
                        fare_id=fid,
                        price='0',  # seguro como string (se seu model for DecimalField, ajuste)
                        currency_type=default_currency or 'BRL',
                        payment_method=0,
                        transfers=None,
                        agency_id=None,
                    ))
                stub_rules_fare_count += 1

            rules.append(FareRule(
                fare_id=fid,
                route_id=rid,
                origin_id=row.get('origin_id'),
                destination_id=row.get('destination_id'),
                contains_id=row.get('contains_id'),
            ))

        # criar stubs detectados nas rules
        if stub_rule_routes:
            Route.objects.bulk_create(stub_rule_routes, ignore_conflicts=True)
            print(f"🧱 Routes stub criadas (via fare_rules): {len(stub_rule_routes)}. Ex.: {', '.join(sorted(list(stub_rule_route_ids))[:10])}")
            route_ids_db.update(stub_rule_route_ids)
        else:
            print("🧱 Routes stub criadas (via fare_rules): 0")

        if stub_fares:
            FareAttribute.objects.bulk_create(stub_fares, ignore_conflicts=True)
            print(f"💳 FareAttributes stub criados: {len(stub_fares)}. Ex.: {', '.join(sorted(list(stub_fare_ids))[:10])}")
            fare_ids_db.update(stub_fare_ids)
        else:
            print("💳 FareAttributes stub criados: 0")

        print(f"ℹ️ FareRules com fare_id ausente (que motivaram stub): {stub_rules_fare_count}")
        print(f"ℹ️ FareRules com route_id ausente (que motivaram stub): {stub_rules_route_count}")

        FareRule.objects.bulk_create(rules, ignore_conflicts=True)
        print(f"✅ FareRules: {len(rules)} registros importados.")

    # Frequencies (opcional)
    freqs_path = os.path.join(caminho_gtfs, 'frequencies.txt')
    if os.path.exists(freqs_path):
        with open(freqs_path, encoding='utf-8', newline='', errors='replace') as f:
            freqs = []
            skipped_freqs = 0
            for row in csv.DictReader(f):
                tid = norm_str(row.get('trip_id'))
                if tid and tid not in imported_trip_ids:
                    skipped_freqs += 1
                    continue
                freqs.append(Frequency(
                    trip_id=tid,
                    start_time=parse_time(row['start_time']),
                    end_time=parse_time(row['end_time']),
                    headway_secs=to_int(row.get('headway_secs')),
                ))
            Frequency.objects.bulk_create(freqs, ignore_conflicts=True)
            print(f"✅ Frequencies: {len(freqs)} registros importados.")
            if skipped_freqs:
                print(f"⚠️ Frequencies ignoradas por trip_id não importado: {skipped_freqs}")
    else:
        print("⏭️ Frequencies: arquivo não encontrado (opcional no GTFS) — pulando.")

    print("🎉 Importação GTFS concluída com sucesso.")


def importar_shapes(caminho_gtfs):
    from transporte.models import Shape
    import os, csv

    def open_file(nome):
        return open(os.path.join(caminho_gtfs, nome), encoding='utf-8', newline='', errors='replace')

    print("🚀 Iniciando importação de Shapes (lotes de 99)...")

    shapes = []
    total = 0
    batch_size = 99

    with open_file('shapes.txt') as f:
        for i, row in enumerate(csv.DictReader(f), start=1):
            shape = Shape(
                shape_id=row['shape_id'],
                shape_pt_lat=to_float(row['shape_pt_lat']),
                shape_pt_lon=to_float(row['shape_pt_lon']),
                shape_pt_sequence=to_int(row.get('shape_pt_sequence')),
            )
            shapes.append(shape)

            if len(shapes) >= batch_size:
                Shape.objects.bulk_create(shapes, ignore_conflicts=True)
                total += len(shapes)
                print(f"✅ Lote de {len(shapes)} shapes importados (total até agora: {total})")
                shapes = []

        if shapes:
            Shape.objects.bulk_create(shapes, ignore_conflicts=True)
            total += len(shapes)
            print(f"✅ Último lote de {len(shapes)} shapes importados (total: {total})")

    print(f"🎉 Importação finalizada. Total de shapes importados: {total}")


def importar_fare_attributes(caminho_gtfs):
    from transporte.models import FareAttribute
    import os, csv

    def open_file(nome):
        return open(os.path.join(caminho_gtfs, nome), encoding='utf-8', newline='', errors='replace')

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
                payment_method=to_int(row.get('payment_method')),
                transfers=to_int(row.get('transfers')),
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
        return open(os.path.join(caminho_gtfs, nome), encoding='utf-8', newline='', errors='replace')

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
        return open(os.path.join(caminho_gtfs, nome), encoding='utf-8', newline='', errors='replace')

    def parse_time_local(value):
        try:
            return datetime.strptime(value, "%H:%M:%S").time()
        except:
            return None

    print("🚀 Iniciando importação de Frequencies (lotes de 499)...")

    freqs = []
    total = 0
    batch_size = 499

    freqs_path = os.path.join(caminho_gtfs, 'frequencies.txt')
    if not os.path.exists(freqs_path):
        print("⏭️ Frequencies: arquivo não encontrado (opcional no GTFS) — nada a importar.")
        return

    with open_file('frequencies.txt') as f:
        for row in csv.DictReader(f):
            tid = norm_str(row.get('trip_id'))
            freqs.append(Frequency(
                trip_id=tid,
                start_time=parse_time_local(row['start_time']),
                end_time=parse_time_local(row['end_time']),
                headway_secs=to_int(row.get('headway_secs')),
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
