import osmnx as ox
import geopandas as gpd

def grafo_de_geojson(caminho_geojson):
    print("Lendo GeoJSON...")
    gdf = gpd.read_file(caminho_geojson)

    print("Convertendo para grafo...")
    G = ox.graph_from_gdfs(edges=gdf)  # Removido nodes=None

    ox.save_graphml(G, "grafo_sp_caminhada.graphml")
    print("Grafo salvo como grafo_sp_caminhada.graphml")
