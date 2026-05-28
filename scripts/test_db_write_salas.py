import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.load.write_salas import write_salas_result_to_sql


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Escribe un resultado de salas en Azure SQL.")
    parser.add_argument("--input", required=True, help="Ruta al JSON de resultado de procesador.py")
    parser.add_argument("--id-archivo", type=int, required=True)
    return parser.parse_args()


def load_result(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        result = json.load(file)

    if not isinstance(result, dict):
        raise ValueError("El archivo de entrada debe contener un objeto JSON")

    return result


def main() -> int:
    args = parse_args()
    result = load_result(Path(args.input))
    summary = write_salas_result_to_sql(args.id_archivo, result)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
