import uuid
from datetime import datetime, timedelta, timezone

import boto3
import requests

API_URL = "https://ultimosismo.igp.gob.pe/api/ultimo-sismo/ajaxb/{anio}"
TABLE_NAME = "TablaSismosIGP"
MAX_SISMOS = 10


def obtener_sismos(anio):
    """Descarga la lista de sismos de un anio desde la API del IGP."""
    resp = requests.get(API_URL.format(anio=anio),
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()
    return resp.json()


def a_item(s):
    """Convierte un sismo de la API en un item para DynamoDB."""
    item = {
        "codigo": s.get("codigo"),
        "fecha_local": (s.get("fecha_local") or "")[:10],     # 2026-10-28
        "hora_local": (s.get("hora_local") or "")[11:19],     # 12:30:45
        "referencia": s.get("referencia"),
        "magnitud": s.get("magnitud"),
        "profundidad": s.get("profundidad"),                  # km
        "latitud": s.get("latitud"),
        "longitud": s.get("longitud"),
        "intensidad": s.get("intensidad"),
        "reporte_pdf": s.get("reporte_acelerometrico_pdf"),
    }
    return {k: v for k, v in item.items() if v not in (None, "")}


def lambda_handler(event, context):
    # Hora de Lima (UTC-5) para decidir el anio actual
    anio = (datetime.now(timezone.utc) - timedelta(hours=5)).year

    try:
        sismos = obtener_sismos(anio)
        if len(sismos) < MAX_SISMOS:  # inicio de anio: completar con el anterior
            sismos = obtener_sismos(anio - 1) + sismos
    except Exception as e:
        return {"statusCode": 502,
                "body": f"Error al acceder a la API del IGP: {e}"}

    if not sismos:
        return {"statusCode": 404, "body": "No se encontraron sismos"}

    # La API devuelve del mas antiguo al mas reciente: ordenar y tomar los 10 ultimos
    sismos.sort(key=lambda s: s.get("idlistasismos") or 0, reverse=True)
    rows = [a_item(s) for s in sismos[:MAX_SISMOS]]

    table = boto3.resource("dynamodb").Table(TABLE_NAME)

    # Limpiar la tabla (con paginacion) antes de insertar los nuevos datos
    scan = table.scan(ProjectionExpression="id")
    items = scan["Items"]
    while "LastEvaluatedKey" in scan:
        scan = table.scan(ProjectionExpression="id",
                          ExclusiveStartKey=scan["LastEvaluatedKey"])
        items.extend(scan["Items"])
    with table.batch_writer() as batch:
        for it in items:
            batch.delete_item(Key={"id": it["id"]})

    with table.batch_writer() as batch:
        for n, row in enumerate(rows, start=1):
            row["#"] = n
            row["id"] = str(uuid.uuid4())
            batch.put_item(Item=row)

    return {"statusCode": 200, "body": rows}
