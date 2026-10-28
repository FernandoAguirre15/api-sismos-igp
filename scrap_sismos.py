import uuid
import requests
import boto3
from bs4 import BeautifulSoup

URL = "https://ultimosismo.igp.gob.pe/productos/reportes-sismicos"
TABLE_NAME = "TablaSismosIGP"
MAX_SISMOS = 10
DEFAULT_HEADERS = ["Reporte", "Referencia", "Fecha y hora local", "Magnitud"]


def parse_sismos(html, limit=MAX_SISMOS):
    """Extrae las primeras `limit` filas de la tabla de sismos."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return None

    headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]

    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not cells:  # fila de encabezado u hoja vacia
            continue
        names = headers if len(headers) == len(cells) else DEFAULT_HEADERS
        item = {}
        for i, value in enumerate(cells):
            key = names[i] if i < len(names) else f"Columna {i + 1}"
            item[key] = value
        rows.append(item)
        if len(rows) == limit:
            break
    return rows


def lambda_handler(event, context):
    response = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    if response.status_code != 200:
        return {"statusCode": response.status_code,
                "body": "Error al acceder a la pagina web"}

    rows = parse_sismos(response.content)
    if rows is None:
        return {"statusCode": 404,
                "body": "No se encontro la tabla en la pagina web"}
    if not rows:
        return {"statusCode": 404, "body": "La tabla no contiene sismos"}

    table = boto3.resource("dynamodb").Table(TABLE_NAME)

    # Limpiar la tabla (paginando el scan) antes de insertar los nuevos datos
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
