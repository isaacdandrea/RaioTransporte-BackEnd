import requests
import folium
from datetime import datetime

# Parâmetros de teste
lat = -23.557983
lon = -46.660507
tempo = 30  # minutos

# Endpoint do Django
URL = "http://localhost:8000/transporte/api/raio/"

# 1️⃣ Enviar requisição POST
print("⏳ Consultando o endpoint...")
res = requests.post(URL, json={"lat": lat, "lon": lon, "tempo": tempo})
data = res.json()
print("🔍 Resposta recebida:")
print(res.status_code)
print(data)
# 2️⃣ Criar mapa com folium
print(f"📍 {len(data['features'])} pontos recebidos.")
m = folium.Map(location=[lat, lon], zoom_start=14)

# Adiciona ponto inicial
folium.Marker([lat, lon], tooltip="Origem", icon=folium.Icon(color="red")).add_to(m)

# Extrair pontos
pontos = []

for feature in data['features']:
    coords = feature['geometry']['coordinates']
    props = feature['properties']
    ponto = [coords[1], coords[0]]  # [lat, lon]
    pontos.append(ponto)

    folium.CircleMarker(
        location=ponto,
        radius=4,
        popup=f"{props['stop_name']} ({props['tempo_min']} min)",
        color="blue",
        fill=True,
        fill_opacity=0.7
    ).add_to(m)

# 3️⃣ Desenhar linhas entre pontos próximos (simplesmente ligando os pontos em ordem)
if len(pontos) > 1:
    folium.PolyLine(pontos, color="green", weight=1, opacity=0.5).add_to(m)

# 4️⃣ Salvar o mapa
now = datetime.now().strftime("%Y%m%d_%H%M")
nome_arquivo = f"raio_mapa_{now}.html"
m.save(nome_arquivo)
print(f"✅ Mapa salvo em: {nome_arquivo}")
