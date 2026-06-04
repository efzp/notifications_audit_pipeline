import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.load.prepare_sql_rows import (
    prepare_all_from_audiencias_result,
    prepare_all_from_correo_result,
    prepare_all_from_salas_result,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepara filas SQL desde resultados JSON de los procesadores."
    )
    parser.add_argument("--source", choices=("salas", "correo", "audiencias"), required=True)
    parser.add_argument("--input", required=True, help="Ruta al JSON de resultado del procesador")
    parser.add_argument("--id-archivo", type=int, required=True)
    return parser.parse_args()


def load_result(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        result = json.load(file)

    if not isinstance(result, dict):
        raise ValueError("El archivo de entrada debe contener un objeto JSON")

    return result


def table_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)

    if isinstance(value, dict):
        return 1

    return 0


def first_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return value[:2]

    if isinstance(value, dict):
        return [value]

    return []


def main() -> int:
    args = parse_args()
    result = load_result(Path(args.input))

    if args.source == "salas":
        prepared = prepare_all_from_salas_result(args.id_archivo, result)
    elif args.source == "correo":
        prepared = prepare_all_from_correo_result(args.id_archivo, result)
    else:
        prepared = prepare_all_from_audiencias_result(args.id_archivo, result)

    summary = {
        table_name: {
            "filas_preparadas": table_count(rows),
            "primeras_2_filas": first_rows(rows),
        }
        for table_name, rows in prepared.items()
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
