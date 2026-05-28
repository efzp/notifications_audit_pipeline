import json
import logging

import azure.functions as func

import procesador
import procesador_correo


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def build_json_response(body: dict, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(body, ensure_ascii=False),
        status_code=status_code,
        mimetype="application/json",
    )


def get_request_payload(req: func.HttpRequest) -> dict:
    try:
        payload = req.get_json()
    except ValueError as exc:
        raise ValueError("El body debe ser un JSON valido") from exc

    if not isinstance(payload, dict):
        raise ValueError("El body debe ser un objeto JSON")

    return payload


def handle_processing(req: func.HttpRequest, processor, route_name: str) -> func.HttpResponse:
    logging.info("%s ejecutada", route_name)

    try:
        payload = get_request_payload(req)
        result = processor(payload)
    except Exception as exc:
        logging.exception("Error procesando %s", route_name)
        return build_json_response(
            {
                "status": "ERROR",
                "mensaje": str(exc),
            },
            status_code=400,
        )

    status_code = 200 if result.get("status") == "OK" else 422
    return build_json_response(result, status_code=status_code)


@app.route(route="procesar_input_salas", methods=["POST"])
def procesar_input_salas(req: func.HttpRequest) -> func.HttpResponse:
    return handle_processing(req, procesador.process_payload_data, "procesar_input_salas")


@app.route(route="procesar_correo", methods=["POST"])
def procesar_correo(req: func.HttpRequest) -> func.HttpResponse:
    return handle_processing(req, procesador_correo.process_payload_data, "procesar_correo")
