import json
import logging

import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="procesar_input_salas", methods=["POST"])
def procesar_input_salas(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("procesar_input_salas ejecutada")

    return func.HttpResponse(
        json.dumps({
            "status": "OK",
            "mensaje": "Function cargada correctamente"
        }),
        status_code=200,
        mimetype="application/json"
    )