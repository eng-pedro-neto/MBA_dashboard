import argparse
import math
from pathlib import Path

import geopandas as gpd


def calcular_utm(gdf):
    """Determina o EPSG UTM a partir do centroide da geometria."""
    gdf = gdf.copy()
    if gdf.empty:
        raise ValueError("O GeoDataFrame está vazio.")

    if gdf.crs is None:
        raise ValueError("A camada não possui CRS definido.")

    geometrias = gdf.geometry.dropna()
    if geometrias.empty or geometrias.is_empty.all():
        raise ValueError("A camada não contém geometrias válidas.")

    ponto = geometrias.to_crs("EPSG:4326").union_all().representative_point()
    if ponto.is_empty or not (-180 <= ponto.x <= 180 and -90 <= ponto.y <= 90):
        raise ValueError("Não foi possível determinar a localização da camada.")
    zona = min(60, max(1, math.floor((ponto.x + 180) / 6) + 1))

    if ponto.y > 0:
        epsg = 32600 + zona
    else:
        epsg = 32700 + zona

    return epsg


def padronizar_utm(gdf, epsg=None):
    """Converte o GeoDataFrame para a projeção UTM correta."""
    if epsg is None:
        epsg = calcular_utm(gdf)

    return gdf.to_crs(epsg=epsg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calcula e informa a projeção UTM de uma camada.")
    parser.add_argument("arquivo", type=Path, help="Caminho para um arquivo geoespacial")
    argumentos = parser.parse_args()
    gdf = gpd.read_file(argumentos.arquivo)
    epsg = calcular_utm(gdf)
    gdf_utm = padronizar_utm(gdf, epsg)
    print(f"EPSG: {epsg}")
    print(f"CRS convertido: {gdf_utm.crs}")
