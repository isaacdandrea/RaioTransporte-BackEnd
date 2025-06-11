import requests
import folium
from datetime import datetime

# ---------------- Parâmetros de teste ----------------
lat = -23.557983
lon = -46.660507
tempo = 30  # minutos
URL = "http://localhost:8000/transporte/api/raio/"

# 1️⃣ Consulta ao endpoint
print("⏳ Consultando o endpoint…")
res = requests.post(URL, json={"lat": lat, "lon": lon, "tempo": tempo})
data = res.json()
print("🔍 Resposta:", res.status_code, f"({len(data['features'])} features)")

# 2️⃣ Cria mapa
m = folium.Map(location=[lat, lon], zoom_start=13)
folium.Marker([lat, lon], tooltip="Origem", icon=folium.Icon(color="red")).add_to(m)

for feat in data["features"]:
    geom = feat["geometry"]
    if geom["type"] in ("Polygon", "MultiPolygon"):
        folium.GeoJson(
            geom,
            style_function=lambda _: {
                "color": "purple",
                "weight": 2,
                "fillOpacity": 0.15,
            },
        ).add_to(m)
    elif geom["type"] == "Point":
        folium.CircleMarker(
            location=[geom["coordinates"][1], geom["coordinates"][0]],
            radius=4,
            popup=f"{feat['properties']['stop_name']} ({feat['properties']['tempo_min']} min)",
            color="blue",
            fill=True,
            fill_opacity=0.7,
        ).add_to(m)

# 3️⃣ Salva HTML
nome_arquivo = f"raio_mapa_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
m.save(nome_arquivo)
print("✅ Mapa salvo em:", nome_arquivo)
