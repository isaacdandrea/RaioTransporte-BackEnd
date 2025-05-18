# testar_algoritmo.py

import os
import django
from django.contrib.gis.geos import Point

# Configura o ambiente do Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mobilidade.settings')
django.setup()

from transporte.algorithms.raio_alcance import calcular_raio

def main():
    # Coordenadas em São Paulo (ex: Av. Paulista)
    lat = -23.561414
    lon = -46.655881
    tempo_limite = 30  # minutos

    print(f"Calculando raio de alcance a partir de {lat}, {lon} em {tempo_limite} minutos...\n")

    resultado = calcular_raio(lat, lon, tempo_limite)

    if "error" in resultado:
        print("Erro:", resultado["error"])
    else:
        print(f"{len(resultado['features'])} paradas alcançáveis encontradas.\n")
        for feature in resultado["features"][:10]:  # mostra só as 10 primeiras
            props = feature["properties"]
            print(f"{props['stop_name']} ({props['stop_id']}) - {props['tempo_min']} min")

if __name__ == '__main__':
    main()
