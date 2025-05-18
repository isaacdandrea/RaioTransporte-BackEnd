import osmnx as ox

def extrair_cidade_sp(osm_path):
    print("Obtendo limite geográfico da cidade de São Paulo...")
    sp_boundary = ox.geocode_to_gdf("São Paulo, São Paulo, Brasil")

    print("Carregando grafo completo do XML...")
    G_raw = ox.graph_from_xml(osm_path, simplify=True)

    print("Filtrando para rede de caminhada...")
    G_walk = ox.utils_graph.get_largest_component(G_raw, strongly=False)
    G_walk = ox.utils_graph.add_edge_lengths(G_walk)

    # (Opcional) filtro manual: remover ruas não caminháveis
    # Aqui você pode aplicar filtros com base nos atributos das arestas, se necessário

    print("Recortando grafo para a cidade de SP...")
    G_sp = ox.truncate.truncate_graph_polygon(G_walk, sp_boundary.geometry[0], retain_all=True)

    ox.save_graphml(G_sp, filepath="grafo_sp_caminhada.graphml")
    print("Grafo de caminhada da cidade de São Paulo salvo com sucesso.")
