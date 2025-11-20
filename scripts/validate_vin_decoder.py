"""Lightweight helper to compare our VIN decoding against NHTSA's VPIC API.

Usage:
    poetry run python scripts/validate_vin_decoder.py

The script does live HTTP calls to https://vpic.nhtsa.dot.gov, so it requires
an active internet connection.
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Dict, Iterable, Tuple

import requests

# Make sure `app` is importable when executing the script from the repo root.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.vin_decoder import VinDecoder

VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"

SAMPLE_VINS: Dict[str, str] = {
    "Model S": "5YJSA1E26HF000337",
    "Model 3 RWD": "5YJ3E1EA7JF000000",
    "Model 3 AWD": "5YJ3E1EB5KF317000",
    "Model 3 Performance": "5YJ3E1EC7LF000000",
    "Model X": "5YJXCBE22HF068739",
    "Model Y": "7SAYGAEE8NF354486",
    "Cybertruck": "7G2CEHED7RF000001",
}

KEYS_TO_COMPARE: Tuple[Tuple[str, str], ...] = (
    ("Model", "Model"),
    ("Body Type", "BodyClass"),
    ("Motor", "OtherEngineInfo"),
    ("Factory", "PlantCity"),
)


def decode_official(vin: str) -> Dict[str, str]:
    response = requests.get(VPIC_URL.format(vin=vin), timeout=30)
    response.raise_for_status()
    payload = response.json()
    result = payload.get("Results", [{}])[0]
    return {
        "Model": result.get("Model"),
        "BodyClass": result.get("BodyClass"),
        "OtherEngineInfo": result.get("OtherEngineInfo"),
        "PlantCity": result.get("PlantCity"),
    }


def compare_values(label: str, internal: str | None, official: str | None) -> str:
    if not internal and not official:
        return "-"
    if internal == official or (
        internal
        and official
        and (
            internal.lower() in official.lower()
            or official.lower() in internal.lower()
        )
    ):
        status = "MATCH"
    else:
        status = "MISMATCH"
    return f"{label}: {status}\n    ours={internal}\n    vpic={official}"


def main() -> None:
    decoder = VinDecoder()
    for name, vin in SAMPLE_VINS.items():
        ours = decoder.decode(vin)
        official = decode_official(vin)
        print("=" * 80)
        print(f"{name} — {vin}")
        if ours is None:
            print("Decoder returned None (invalid VIN length)")
            continue
        for internal_key, official_key in KEYS_TO_COMPARE:
            internal_value = ours.get(internal_key)
            official_value = official.get(official_key)
            print(compare_values(internal_key, internal_value, official_value))
        print("\nComputed details:")
        print(json.dumps(ours, indent=2))


if __name__ == "__main__":
    main()
