from django.db.models import Count
from transporte.models import (
    Agency, Calendar, Stop, Route, Trip, StopTime, Shape,
    FareAttribute, FareRule, Frequency
)

def verificar_duplicatas():
    print("🔍 Verificando duplicatas nas tabelas GTFS...\n")

    def verificar(model, campos, nome=None):
        nome = nome or model.__name__
        # Usa o primeiro campo como base para contagem (sempre existente)
        contagem_por = campos[0]

        duplicatas = model.objects.values(*campos).annotate(qtd=Count(contagem_por)).filter(qtd__gt=1)

        if duplicatas.exists():
            print(f"❗ {nome}: {duplicatas.count()} grupos de duplicatas encontrados por campos {campos}")
            for d in duplicatas[:5]:  # mostra até 5 exemplos
                print(f"   ➥ Exemplo: {d}")
        else:
            print(f"✅ {nome}: sem duplicatas por campos {campos}")

    verificar(Agency, ['agency_id'])
    verificar(Calendar, ['service_id'])
    verificar(Stop, ['stop_id'])
    verificar(Route, ['route_id'])
    verificar(Trip, ['trip_id'])
    verificar(StopTime, ['trip_id', 'stop_sequence'])
    verificar(Shape, ['shape_id', 'shape_pt_sequence'])
    verificar(FareAttribute, ['fare_id'])
    verificar(FareRule, ['fare_id', 'route_id'])
    verificar(Frequency, ['trip_id', 'start_time', 'end_time'])

    print("\n✅ Verificação de duplicatas concluída.")
