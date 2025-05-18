import osmnx as ox
import networkx as nx

def baixar_grafo_sp():
    print("Baixando grafo de ruas caminháveis de São Paulo...")
    G = ox.graph_from_place("São Paulo, São Paulo, Brasil", network_type='walk')
    ox.save_graphml(G, filepath='grafo_sp_caminhada.graphml')
    print("Grafo salvo como 'grafo_sp_caminhada.graphml'")
