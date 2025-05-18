import datetime
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mobilidade.settings')
django.setup()
from transporte.algorithms.raio_alcance import calcular_raio

def main():
    lat = -23.561414
    lon = -46.655881
    tempo_limite = 30  # minutos

    # Dia da semana atual (ex: 'monday', 'tuesday', etc.)
    hoje = datetime.datetime.today()
    dia_semana = hoje.strftime('%A').lower()

    # Horário atual
    hora_atual = hoje.time()

    print(f"Calculando raio de alcance a partir de {lat}, {lon} em {tempo_limite} minutos...")
    print(f"🕒 Dia: {dia_semana}, Hora: {hora_atual.strftime('%H:%M:%S')}")

    resultado = calcular_raio(lat, lon, tempo_limite, dia_semana, hora_atual)

    print(f"\n{len(resultado['features'])} paradas alcançáveis encontradas.\n")
    for f in sorted(resultado['features'], key=lambda f: f['properties']['tempo_min']):
        nome = f['properties']['stop_name']
        tempo = f['properties']['tempo_min']
        print(f"{nome} ({f['properties']['stop_id']}) - {tempo} min")

if __name__ == "__main__":
    main()
