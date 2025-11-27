from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypeVar

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .metrics import build_metrics_from_env
from .monitor import TeslaOrderMonitor
from .vin_decoder import VinDecoder

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SW_FILE = STATIC_DIR / "sw.js"

app = FastAPI(title="Tesla Order Status")
monitor = TeslaOrderMonitor()
vin_decoder = VinDecoder()
metrics_enabled = os.getenv("ENABLE_VISIT_METRICS", "1") != "0"
visit_metrics = build_metrics_from_env() if metrics_enabled else None

ResponseT = TypeVar("ResponseT", HTMLResponse, RedirectResponse)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

logger = logging.getLogger(__name__)

TOKEN_HEADER = "x-tesla-bundle"
CLEAR_HEADER = "x-tesla-clear"
VISIT_PATHS = frozenset({"/", "/history", "/refresh"})


@app.middleware("http")
async def visit_metrics_middleware(request: Request, call_next):
    response = await call_next(request)
    if visit_metrics and request.method == "GET" and request.url.path in VISIT_PATHS:
        visit_metrics.record(request.url.path, logger=logger)
    return response


@app.on_event("shutdown")
async def flush_visit_metrics() -> None:
    if visit_metrics:
        visit_metrics.force_log(logger=logger)


MARKET_OPTION_CATALOG: Dict[str, Dict[str, str]] = {
    # Vehicle / drive / manufacturing
    "MDL3": {"category": "Vehicle", "name": "Model 3 Platform"},
    "MDLY": {"category": "Vehicle", "name": "Model Y Platform"},
    "MDLS": {"category": "Vehicle", "name": "Model S Platform"},
    "MDLX": {"category": "Vehicle", "name": "Model X Platform"},
    "MTS03": {"category": "Manufacturing", "name": "Model S Long Range"},
    "MTS07": {"category": "Manufacturing", "name": "Model S Long Range Plus"},
    "MTS11": {"category": "Manufacturing", "name": "Model S Plaid"},
    "MTX03": {"category": "Manufacturing", "name": "Model X Long Range"},
    "MTX04": {"category": "Manufacturing", "name": "Model X Performance"},
    "MTX07": {"category": "Manufacturing", "name": "Model X Long Range Plus"},
    "MTX11": {"category": "Manufacturing", "name": "Model X Plaid"},
    "MT300": {"category": "Manufacturing", "name": "Model 3 Standard Range RWD"},
    "MT301": {"category": "Manufacturing", "name": "Model 3 Standard Range Plus RWD"},
    "MT302": {"category": "Manufacturing", "name": "Model 3 Long Range RWD"},
    "MT303": {"category": "Manufacturing", "name": "Model 3 Long Range AWD"},
    "MT304": {"category": "Manufacturing", "name": "Model 3 Long Range Performance"},
    "MT323": {"category": "Manufacturing", "name": "Model 3 Long Range AWD (refresh)"},
    "MT353": {"category": "Manufacturing", "name": "Model 3 Performance Highland"},
    "ADPX0": {"category": "Drive", "name": "Rear-wheel drive single motor"},
    "ADPX1": {"category": "Drive", "name": "Long Range dual motor"},
    "ADPX2": {"category": "Drive", "name": "Performance dual motor"},
    "DUALMOTOR": {"category": "Drive", "name": "Dual Motor AWD badging"},
    "DV4W": {"category": "Drive", "name": "Dual motor all-wheel drive"},
    "P3WS": {"category": "Performance", "name": "Performance Upgrade Package"},
    "MT322": {"category": "Manufacturing", "name": "Model year 2022 Q2 build"},
    "MT337": {"category": "Manufacturing", "name": "Model year 2023 Q4 build"},
    "MTY01": {"category": "Manufacturing", "name": "Model Y Standard Range RWD"},
    "MTY02": {"category": "Manufacturing", "name": "Model Y Long Range RWD"},
    "MTY03": {"category": "Manufacturing", "name": "Model Y Long Range AWD"},
    "MTY04": {"category": "Manufacturing", "name": "Model Y Performance AWD"},
    "MTY05": {"category": "Manufacturing", "name": "Model Y Performance"},
    "MTY47": {
        "category": "Manufacturing",
        "name": "Model Y LR AWD (LG 5L pack)",
    },
    "MTY62": {
        "category": "Manufacturing",
        "name": "Model Y LR AWD (LG 5M pack)",
    },
    "TM00": {"category": "Towing", "name": "Towing package deleted"},
    "TOW1": {"category": "Towing", "name": "Factory tow package"},
    # Batteries / powertrain
    "BT37": {"category": "Battery", "name": "Long Range battery pack"},
    "BT38": {"category": "Battery", "name": "Standard Range battery pack"},
    "BT42": {"category": "Battery", "name": "4680 structural battery pack"},
    "BP00": {"category": "Battery", "name": "No Ludicrous upgrade"},
    # Paint options
    "PPSW": {"category": "Paint", "name": "Pearl White Multi-Coat paint"},
    "PPMR": {"category": "Paint", "name": "Red Multi-Coat paint"},
    "PMNG": {"category": "Paint", "name": "Midnight Silver Metallic paint"},
    "PPSB": {"category": "Paint", "name": "Deep Blue Metallic paint"},
    "PMBL": {"category": "Paint", "name": "Obsidian Black Metallic paint"},
    "PMTL": {"category": "Paint", "name": "Titanium Metallic paint"},
    "PBCW": {"category": "Paint", "name": "Solid Black paint"},
    "PB02": {"category": "Paint", "name": "Marine Blue"},
    # Wheels / tires / suspension
    "WTAS": {"category": "Wheels", "name": '19" Sport Wheels'},
    "W38B": {"category": "Wheels", "name": '18" Aero Wheels'},
    "W39B": {"category": "Wheels", "name": '19" Sport Wheels'},
    "W40B": {"category": "Wheels", "name": '20" Induction Wheels'},
    "W41B": {"category": "Wheels", "name": '20" Gemini Wheels'},
    "WTUR": {"category": "Wheels", "name": '21" Überturbine Wheels'},
    "WY19P": {"category": "Wheels", "name": '19" Crossflow Wheels'},
    "ST33": {"category": "Suspension", "name": "All-season tires"},
    "SU3C": {"category": "Suspension", "name": "Coil suspension setup"},
    # Interior
    "IN3PB": {"category": "Interior", "name": "Premium all-black interior"},
    "IN3PW": {"category": "Interior", "name": "Premium black & white interior"},
    "INYPB": {"category": "Interior", "name": "Model Y black interior"},
    "INYPW": {"category": "Interior", "name": "Model Y black & white interior"},
    "IPB8": {"category": "Interior", "name": "Premium all-black interior"},
    "IL31": {"category": "Interior", "name": "Interior ambient lighting"},
    "AU3P": {"category": "Interior", "name": "Premium audio system"},
    "AF02": {"category": "Interior", "name": "Subzero weather / heated components"},
    # Comfort / seating
    "ST01": {"category": "Seating", "name": "Front heated seats"},
    "RSF1": {"category": "Seating", "name": "Rear heated seats"},
    "RSF2": {"category": "Seating", "name": "Second row seat heaters"},
    "STY5S": {"category": "Seating", "name": "MY 5 Seat Interior"},
    # Autopilot / software / connectivity
    "APBS": {"category": "Software", "name": "Basic Autopilot"},
    "APF0": {"category": "Software", "name": "Autopilot hardware with no features"},
    "APF1": {"category": "Software", "name": "Autopilot convenience features"},
    "APF2": {"category": "Software", "name": "Enhanced Autopilot"},
    "APF3": {"category": "Software", "name": "Full Self-Driving computer (HW3)"},
    "APPB": {"category": "Software", "name": "Full Self-Driving capability"},
    "ACC1": {"category": "Connectivity", "name": "Premium connectivity"},
    "CPF0": {"category": "Connectivity", "name": "Premium connectivity (trial)"},
    "CPF1": {
        "category": "Connectivity",
        "name": "Premium connectivity (1 year included)",
    },
    "SC04": {"category": "Charging", "name": "Pay-as-you-go Supercharging"},
    "SC05": {"category": "Charging", "name": "Free unlimited Supercharging"},
    # Safety / hardware
    "FR04": {"category": "Hardware", "name": "HEPA filter & Bioweapon Defense Mode"},
    "HM31": {"category": "Hardware", "name": "Power folding, heated side mirrors"},
    "HL32": {"category": "Hardware", "name": "Matrix LED headlights"},
    "PI01": {"category": "Hardware", "name": "Premium audio amplifier"},
    "DRLH": {"category": "Hardware", "name": "Left-hand drive configuration"},
    "DRRH": {"category": "Hardware", "name": "Right-hand drive configuration"},
    "OPPF": {"category": "Protection", "name": "Factory paint protection film"},
    "BC3R": {"category": "Hardware", "name": "Performance red brake calipers"},
}

OPTION_HINT_RULES: List[tuple[re.Pattern[str], tuple[str, str]]] = [
    (re.compile(r"^(PP|PM|PBC|PRS|PBS)"), ("Paint", "Exterior paint option")),
    (re.compile(r"^W\d+"), ("Wheels", "Wheel package")),
    (re.compile(r"^IN"), ("Interior", "Interior trim or material")),
    (re.compile(r"^AP|^FS|^FSD|^EAP"), ("Software", "Autopilot or software package")),
    (re.compile(r"^SC"), ("Charging", "Supercharging config")),
    (re.compile(r"^MDL|^MDY|^MDX"), ("Vehicle", "Model designation")),
    (re.compile(r"^BT"), ("Battery", "Battery configuration")),
    (re.compile(r"^ST|^RS"), ("Seating", "Seat or interior comfort")),
    (re.compile(r"^HP|^DU|^MT"), ("Performance", "Drive-unit or performance upgrade")),
    (re.compile(r"^PK|^PRM"), ("Package", "Equipment package")),
    (re.compile(r"^HM|^FR|^HL|^FG"), ("Hardware", "Hardware feature")),
]

DELIVERY_TYPE_DESCRIPTIONS: Dict[str, str] = {
    "PICKUP_SERVICE_CENTER": "Pickup at service/delivery center",
    "PICKUP_HOME": "Home delivery",
    "PICKUP_EXPRESS": "Express pickup",
    "PICKUP_DC": "Delivery center appointment",
    "PICKUP_STORE": "Retail store pickup",
    "PICKUP_DIRECT": "Direct-to-customer handoff",
}

PAYMENT_STATUS_DESCRIPTIONS: Dict[str, str] = {
    "MAKE_YOUR_FINAL_PAYMENT": "Final payment required",
    "PAYMENT_SUCCESS": "Payment received",
    "FUNDS_IN_TRANSIT": "Funds in transit",
    "PAYMENT_SCHEDULED": "Payment scheduled",
    "PAYMENT_PENDING": "Payment pending",
    "PAYMENT_NOT_REQUIRED": "No payment required",
    "PAYMENT_VERIFICATION": "Payment under verification",
}

APPOINTMENT_STATUS_DESCRIPTIONS: Dict[str, str] = {
    "NOT_SCHEDULED": "Not scheduled",
    "SCHEDULED": "Appointment scheduled",
    "CONFIRMED": "Appointment confirmed",
    "RESCHEDULED": "Appointment rescheduled",
    "AWAITING_CUSTOMER": "Waiting for customer to schedule",
    "AWAITING_TESLA": "Tesla scheduling in progress",
    "COMPLETED": "Appointment completed",
    "CANCELLED": "Appointment cancelled",
}

REGISTRATION_STATUS_DESCRIPTIONS: Dict[str, str] = {
    "NOT_STARTED": "Registration not started",
    "IN_PROGRESS": "Registration in progress",
    "SUBMITTED": "Registration submitted",
    "APPROVED": "Registration approved",
    "COMPLETED": "Registration completed",
    "PENDING": "Registration pending review",
}

REGISTRANT_TYPE_DESCRIPTIONS: Dict[str, str] = {
    "INDIVIDUAL": "Individual registrant",
    "BUSINESS": "Business registrant",
    "LEASE": "Leased vehicle",
    "COMPANY": "Company-owned",
    "GOVERNMENT": "Government fleet",
}

LOCALE_DESCRIPTIONS: Dict[str, str] = {
    "EN_US": "English (United States)",
    "EN_CA": "English (Canada)",
    "EN_GB": "English (United Kingdom)",
    "FR_FR": "French (France)",
    "FR_CA": "French (Canada)",
    "DE_DE": "German (Germany)",
    "NL_NL": "Dutch (Netherlands)",
    "ES_ES": "Spanish (Spain)",
    "ES_MX": "Spanish (Mexico)",
    "SV_SE": "Swedish (Sweden)",
}

ORDER_STATUS_DESCRIPTIONS: Dict[str, str] = {
    "NEW": "Order placed",
    "ORDERED": "Order confirmed",
    "BUILDING": "Vehicle in production",
    "BUILT": "Vehicle built",
    "IN_TRANSIT": "Vehicle in transit",
    "DELIVERED": "Vehicle delivered",
    "CANCELLED": "Order cancelled",
    "HOLD": "Order on hold",
}

ORDER_SUBSTATUS_DESCRIPTIONS: Dict[str, str] = {
    "ALLOCATION_PENDING": "Awaiting factory allocation",
    "VIN_ASSIGNED": "VIN assigned",
    "READY_FOR_DELIVERY": "Ready for delivery",
    "AWAITING_PAYMENT": "Awaiting payment",
    "DOCUMENTS_PENDING": "Paperwork pending",
}

MODEL_CODE_LABELS: Dict[str, str] = {
    "M3": "Model 3",
    "MY": "Model Y",
    "MS": "Model S",
    "MX": "Model X",
    "CT": "Cybertruck",
    "SR": "Roadster",
}

OPTION_CODE_SPLITTER = re.compile(r"[,;|\\s]+")

WINDOW_DATE_PATTERN = re.compile(
    r"(?:(?P<day_first>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month_first>[A-Za-z]{3,})|"
    r"(?P<month_second>[A-Za-z]{3,})\s+(?P<day_second>\d{1,2})(?:st|nd|rd|th)?)",
    re.IGNORECASE,
)

MONTH_ABBREVIATIONS = {
    "JAN": "Jan",
    "JANUARY": "Jan",
    "FEB": "Feb",
    "FEBRUARY": "Feb",
    "MAR": "Mar",
    "MARCH": "Mar",
    "APR": "Apr",
    "APRIL": "Apr",
    "MAY": "May",
    "JUN": "Jun",
    "JUNE": "Jun",
    "JUL": "Jul",
    "JULY": "Jul",
    "AUG": "Aug",
    "AUGUST": "Aug",
    "SEP": "Sep",
    "SEPT": "Sep",
    "SEPTEMBER": "Sep",
    "OCT": "Oct",
    "OCTOBER": "Oct",
    "NOV": "Nov",
    "NOVEMBER": "Nov",
    "DEC": "Dec",
    "DECEMBER": "Dec",
}

FINANCE_PRODUCT_TYPE_DESCRIPTIONS: Dict[str, str] = {
    "RETAIL_LOAN": "Retail loan",
    "LEASE": "Lease",
    "CASH": "Cash purchase",
    "BALLOON": "Balloon financing",
    "TESLA_FINANCE": "Tesla financing",
}

DELIVERY_GATE_DESCRIPTIONS: Dict[str, str] = {
    "BEFORE_DELIVERY": "Before-delivery readiness",
    "AT_DELIVERY": "Delivery-day handoff",
    "AFTER_DELIVERY": "Post-delivery follow-up",
    "BEFORE_DELIVERY_FINANCE": "Finance clearance before delivery",
    "BEFORE_DELIVERY_DOCUMENTS": "Paperwork before delivery",
    "BEFORE_DELIVERY_VEHICLE": "Vehicle prep before delivery",
}

DELIVERY_TIMING_DESCRIPTIONS: Dict[str, str] = {
    "BEFORE_DELIVERY": "Before delivery",
    "AT_DELIVERY": "During delivery",
    "AFTER_DELIVERY": "After delivery",
    "POST_DELIVERY": "Post-delivery",
    "PRIOR_TO_APPOINTMENT": "Prior to appointment",
}


def _decode_token_bundle(value: Optional[str]) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    try:
        decoded = base64.b64decode(value.encode("utf-8"))
        return json.loads(decoded.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Invalid token header: %s", exc)
        return None


def _encode_token_bundle(bundle: Dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(bundle).encode("utf-8")).decode("utf-8")


def _extract_tokens(request: Request) -> Optional[Dict[str, Any]]:
    return _decode_token_bundle(request.headers.get(TOKEN_HEADER))


def _finalize_response(
    response: ResponseT,
    token_bundle: Optional[Dict[str, Any]] = None,
    *,
    clear: bool = False,
) -> ResponseT:
    response.headers["Cache-Control"] = "no-store"
    if clear:
        response.headers[CLEAR_HEADER] = "1"
    elif token_bundle:
        response.headers[TOKEN_HEADER] = _encode_token_bundle(token_bundle)
    return response


def _redirect_to_login(clear: bool = False) -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    return _finalize_response(response, clear=clear)


def _ensure_request_tokens(
    request: Request,
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    token_bundle = _extract_tokens(request)
    if not token_bundle:
        return None, None
    access_token, updated_bundle = monitor.ensure_authenticated(token_bundle)
    return access_token, updated_bundle


def _collect_order_entries(access_token: str) -> List[Dict[str, Any]]:
    basic_orders = monitor.retrieve_orders(access_token)
    detailed_orders: List[Dict[str, Any]] = []
    for order in basic_orders:
        order_id = order.get("referenceNumber")
        if not order_id:
            continue
        details = monitor.get_order_details(order_id, access_token)
        detailed_orders.append({"order": order, "details": details})
    return detailed_orders


def _format_orders(order_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formatted_orders: List[Dict[str, Any]] = []
    for order_data in order_entries:
        order = order_data["order"]
        details = order_data["details"]

        tasks = details.get("tasks", {}) or {}
        scheduling = tasks.get("scheduling", {}) or {}
        registration_task = tasks.get("registration", {}) or {}
        delivery_details_task = tasks.get("deliveryDetails", {}) or {}
        delivery_reg_data = delivery_details_task.get("regData", {}) or {}
        order_info = registration_task.get("orderDetails", {}) or {}
        final_payment_task = tasks.get("finalPayment", {}) or {}
        final_payment_data = (
            final_payment_task.get("data", {})
            if isinstance(final_payment_task, dict)
            else {}
        )
        currency_format = (
            (final_payment_task.get("currencyFormat") or {})
            if isinstance(final_payment_task, dict)
            else {}
        )
        currency_code = currency_format.get("currencyCode") or final_payment_data.get(
            "currencyCode"
        )

        image_assets = monitor.get_vehicle_image_urls(
            order["modelCode"], order.get("mktOptions", "")
        )
        tasks_list = monitor.parse_tasks(tasks)

        vin = order.get("vin")
        vin_details = vin_decoder.decode(vin) if vin else None

        mileage_unit = (
            order_info.get("vehicleOdometerType")
            or order_info.get("vehicleMileageUnit")
            or order_info.get("vehicleOdometerUnit")
            or order_info.get("odometerUnit")
        )
        mileage_value = (
            order_info.get("vehicleOdometer")
            or order_info.get("vehicleMileage")
            or order_info.get("odometer")
        )
        mileage_display = (
            _format_vehicle_mileage(mileage_value, mileage_unit) or "Unknown"
        )

        eta_delivery_raw = final_payment_data.get("etaToDeliveryCenter") or order.get(
            "eta"
        )
        license_plate_value = (
            delivery_reg_data.get("reggieLicensePlate")
            or registration_task.get("reggieLicensePlate")
            or order_info.get("licensePlateNumber")
        )
        summary_pairs = [
            ("License Plate", license_plate_value),
            ("Vehicle Odometer", mileage_display),
            (
                "ETA to Delivery Center",
                _format_date_only(eta_delivery_raw) if eta_delivery_raw else None,
            ),
            (
                "Delivery Type",
                _describe_delivery_type(
                    scheduling.get("deliveryType")
                    or final_payment_data.get("deliveryType")
                ),
            ),
            (
                "Delivery Window",
                scheduling.get("deliveryWindowDisplay")
                or scheduling.get("apptDateTimeAddressStr"),
            ),
            (
                "Pickup Address",
                scheduling.get("deliveryAddressTitle")
                or (final_payment_data.get("deliveryAddress") or {}).get("address1")
                or final_payment_data.get("pickupLocation"),
            ),
            (
                "Payment Status",
                _describe_payment_status(
                    final_payment_task.get("status")
                    if isinstance(final_payment_task, dict)
                    else None
                ),
            ),
            (
                "Customer Amount Due",
                _format_currency(
                    (
                        final_payment_task.get("amountDue")
                        if isinstance(final_payment_task, dict)
                        else None
                    ),
                    currency_code,
                ),
            ),
            ("Order Placed", _format_timestamp(order_info.get("orderPlacedDate"))),
            ("Order Booked", _format_timestamp(order_info.get("orderBookedDate"))),
        ]
        summary_items = _build_items(summary_pairs)

        model_code = (order.get("modelCode") or order.get("model") or "").upper()
        model_name, model_full_name = _derive_model_labels(order, details)

        formatted_orders.append(
            {
                "rn": order["referenceNumber"],
                "model": model_code or "M",
                "model_name": model_name,
                "model_full_name": model_full_name,
                "vin": vin or "N/A",
                "vin_details": vin_details,
                "status": order.get("orderStatus", "unknown"),
                "delivery_date": scheduling.get(
                    "apptDateTimeAddressStr", "Not Scheduled"
                ),
                "eta": final_payment_data.get("etaToDeliveryCenter", "Unknown"),
                "image_urls": image_assets,
                "tasks": tasks_list,
                "summary_items": summary_items,
                "vehicle_odometer": mileage_display,
                "progress": build_order_progress(order_data),
                "insights": build_order_insights(order_data),
                "raw_payload": order_data,
            }
        )
    return formatted_orders


def _format_vehicle_mileage(value: Any, unit: Optional[Any]) -> Optional[str]:
    if value in (None, "", [], {}):
        return None

    text = str(value).strip()
    if not text:
        return None

    token = text.replace(",", " ").split()[0]
    try:
        numeric = float(token)
        if not math.isfinite(numeric):
            raise ValueError
    except (ValueError, TypeError):
        return text

    if abs(numeric - round(numeric)) < 0.01:
        numeric = round(numeric)
        formatted_number = f"{numeric:,d}"
    else:
        formatted_number = f"{numeric:,.2f}"
        
    unit_token = str(unit or "mi").strip().lower()
    if unit_token in {"km", "kilometer", "kilometers", "kilometre", "kilometres"}:
        suffix = "km"
    elif unit_token in {"mi", "mile", "miles"}:
        suffix = "mi"
    else:
        suffix = unit.strip() if isinstance(unit, str) and unit.strip() else "mi"
    return f"{formatted_number} {suffix}"


def _format_currency(amount: Any, currency: Optional[str]) -> Optional[str]:
    if amount in (None, ""):
        return None
    try:
        numeric = float(str(amount))
        formatted = f"{numeric:,.2f}"
    except (ValueError, TypeError):
        formatted = str(amount)
    return f"{currency} {formatted}".strip() if currency else formatted


def _format_timestamp(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        raw = str(value)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw).strftime("%d %b %Y %H:%M")
    except Exception:  # pragma: no cover - fallback
        return str(value)


def _format_date_only(value: Any) -> Optional[str]:
    formatted = _format_timestamp(value)
    if not formatted:
        return None
    tokens = formatted.split()
    if len(tokens) >= 3:
        return " ".join(tokens[:3])
    return formatted


def _abbreviate_month_token(token: str) -> Optional[str]:
    cleaned = re.sub(r"[^A-Z]", "", token.upper()) if token else ""
    if not cleaned:
        return None
    if cleaned in MONTH_ABBREVIATIONS:
        return MONTH_ABBREVIATIONS[cleaned]
    prefix = cleaned[:3]
    if prefix in MONTH_ABBREVIATIONS:
        return MONTH_ABBREVIATIONS[prefix]
    return cleaned.title()[:3]


def _shorten_delivery_window_display(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    matches: List[tuple[str, str]] = []
    for match in WINDOW_DATE_PATTERN.finditer(text):
        if match.group("day_first"):
            day = match.group("day_first")
            month = match.group("month_first")
        else:
            day = match.group("day_second")
            month = match.group("month_second")
        month_abbrev = _abbreviate_month_token(month)
        if not month_abbrev:
            continue
        try:
            day_value = int(day)
        except ValueError:
            continue
        matches.append((month_abbrev, day_value))
        if len(matches) >= 2:
            break
    if len(matches) < 2:
        return None
    (start_month, start_day), (end_month, end_day) = matches[:2]

    def format_day_month(month: str, day: int) -> str:
        return f"{day:02d} {month}"

    start_display = format_day_month(start_month, start_day)
    end_display = format_day_month(end_month, end_day)
    if start_display == end_display:
        return start_display
    return f"{start_display} - {end_display}"


def _build_items(pairs: List[tuple[str, Any]]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for label, value in pairs:
        if value in (None, "", []):
            continue
        if isinstance(value, bool):
            display = "Yes" if value else "No"
        else:
            display = str(value)
        items.append({"label": label, "value": _format_rich_value(display)})
    return items


def _format_rich_value(value: str) -> str:
    text = value.strip()
    if text.startswith(("http://", "https://")):
        return (
            f'<a href="{text}" target="_blank" rel="noopener" '
            'class="text-zinc-100 underline decoration-zinc-500/60 underline-offset-2 hover:text-white">'
            f"{text}</a>"
        )
    return text


def _normalize_option_code(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text.startswith("$"):
        text = text[1:]
    return text or None


def _split_option_codes(blob: Any) -> List[str]:
    if not blob:
        return []
    if isinstance(blob, str):
        candidates = OPTION_CODE_SPLITTER.split(blob)
    elif isinstance(blob, (list, tuple, set)):
        candidates = list(blob)
    elif isinstance(blob, dict):
        candidates = list(blob.values())
    else:
        return []
    codes: List[str] = []
    for candidate in candidates:
        normalized = _normalize_option_code(candidate)
        if normalized:
            codes.append(normalized)
    return codes


def _lookup_trim_label(order: Dict[str, Any], details: Dict[str, Any]) -> Optional[str]:
    order_details = details.get("orderDetails", {}) or {}
    for candidate in (
        order_details.get("trimName"),
        order_details.get("modelDescription"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    trim_code = _normalize_option_code(
        order_details.get("trimCode") or order.get("trimCode")
    )
    if trim_code:
        catalog_entry = MARKET_OPTION_CATALOG.get(trim_code)
        if catalog_entry:
            return catalog_entry["name"]

    option_codes = _split_option_codes(order.get("mktOptions"))
    for code in option_codes:
        catalog_entry = MARKET_OPTION_CATALOG.get(code)
        if not catalog_entry:
            continue
        if catalog_entry.get("category") == "Manufacturing" and code.startswith("MT"):
            return catalog_entry["name"]
    for code in option_codes:
        catalog_entry = MARKET_OPTION_CATALOG.get(code)
        if catalog_entry and catalog_entry.get("category") in {
            "Manufacturing",
            "Vehicle",
        }:
            return catalog_entry["name"]
    return None


def _describe_model_code(value: Any) -> str:
    token = str(value or "").strip().upper()
    if not token:
        return "Tesla"
    if token in MODEL_CODE_LABELS:
        return MODEL_CODE_LABELS[token]
    if token.startswith("MODEL"):
        return token.title()
    if token.startswith("M") and len(token) > 1:
        suffix = token[1:].strip()
        if suffix:
            return f"Model {suffix}".strip()
    return token.title()


def _derive_model_labels(
    order: Dict[str, Any], details: Dict[str, Any]
) -> tuple[str, str]:
    model_code = (order.get("modelCode") or order.get("model") or "").upper()
    base_label = _describe_model_code(model_code)
    trim_label = _lookup_trim_label(order, details)
    if trim_label:
        if trim_label.lower().startswith(base_label.lower()):
            full_label = trim_label
        else:
            full_label = f"{base_label} {trim_label}".strip()
    else:
        full_label = base_label
    return base_label, full_label


def describe_market_options(option_blob: Any) -> List[Dict[str, str]]:
    if not option_blob:
        return []

    codes: List[str] = []
    if isinstance(option_blob, str):
        codes = [
            code.strip().upper()
            for code in re.split(r"[,;|\s]+", option_blob)
            if code.strip()
        ]
    elif isinstance(option_blob, (list, tuple, set)):
        codes = [str(code).strip().upper() for code in option_blob if code]
    elif isinstance(option_blob, dict):
        possible = (
            option_blob.get("optionCodes")
            or option_blob.get("options")
            or option_blob.get("codes")
        )
        if isinstance(possible, (list, tuple, set)):
            codes = [str(code).strip().upper() for code in possible if code]
        else:
            codes = [
                str(value).strip().upper()
                for value in option_blob.values()
                if isinstance(value, str)
            ]

    if not codes:
        return []

    grouped: Dict[str, List[str]] = defaultdict(list)
    unknown: List[str] = []
    for code in codes:
        info = MARKET_OPTION_CATALOG.get(code)
        if info:
            entry = info["name"]
            if code not in entry:
                entry = f"{entry} ({code})"
            grouped[info["category"]].append(entry)
        else:
            unknown.append(code)

    items: List[Dict[str, str]] = []
    for category, values in sorted(grouped.items()):
        if not values:
            continue
        items.append(
            {"label": f"{category} Options", "value": ", ".join(dict.fromkeys(values))}
        )

    for code in dict.fromkeys(sorted(unknown)):
        label, description = _infer_option_hint(code)
        items.append({"label": label, "value": f"{description} ({code})"})

    return items


def _describe_code(value: Any, mapping: Dict[str, str]) -> Optional[str]:
    if not value:
        return value
    key = str(value).upper()
    if key in mapping:
        return mapping[key]
    return key.replace("_", " ").title()


def _describe_delivery_type(value: Any) -> Optional[str]:
    return _describe_code(value, DELIVERY_TYPE_DESCRIPTIONS)


def _describe_payment_status(value: Any) -> Optional[str]:
    return _describe_code(value, PAYMENT_STATUS_DESCRIPTIONS)


def _describe_appointment_status(value: Any) -> Optional[str]:
    return _describe_code(value, APPOINTMENT_STATUS_DESCRIPTIONS)


def _describe_registration_status(value: Any) -> Optional[str]:
    return _describe_code(value, REGISTRATION_STATUS_DESCRIPTIONS)


def _describe_registrant_type(value: Any) -> Optional[str]:
    return _describe_code(value, REGISTRANT_TYPE_DESCRIPTIONS)


def _describe_locale(value: Any) -> Optional[str]:
    return _describe_code(value, LOCALE_DESCRIPTIONS)


def _describe_order_status(value: Any) -> Optional[str]:
    return _describe_code(value, ORDER_STATUS_DESCRIPTIONS)


def _describe_order_substatus(value: Any) -> Optional[str]:
    return _describe_code(value, ORDER_SUBSTATUS_DESCRIPTIONS)


def _describe_finance_product(value: Any) -> Optional[str]:
    return _describe_code(value, FINANCE_PRODUCT_TYPE_DESCRIPTIONS)


def _describe_delivery_gate(value: Any) -> Optional[str]:
    return _describe_code(value, DELIVERY_GATE_DESCRIPTIONS)


def _describe_delivery_timing(value: Any) -> Optional[str]:
    return _describe_code(value, DELIVERY_TIMING_DESCRIPTIONS)


def _infer_option_hint(code: str) -> tuple[str, str]:
    if not code:
        return "Option", "Unrecognized option"
    for pattern, (label, description) in OPTION_HINT_RULES:
        if pattern.match(code):
            return label, description
    return "Option", "Custom configuration"


def _format_blocker_time(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    key = str(value).upper()
    if key in DELIVERY_TIMING_DESCRIPTIONS:
        return DELIVERY_TIMING_DESCRIPTIONS[key]
    timestamp = _format_timestamp(value)
    if timestamp and timestamp != str(value):
        return timestamp
    described = _describe_delivery_timing(value)
    return described or str(value)


def _extract_delivery_blockers(readiness: Dict[str, Any]) -> List[Dict[str, str]]:
    gates = readiness.get("gates") or []
    gate_iterable = gates.values() if isinstance(gates, dict) else gates

    blockers: List[Dict[str, str]] = []
    for gate in gate_iterable:
        if not isinstance(gate, dict) or not gate.get("isBlocker"):
            continue
        gate_label = _describe_delivery_gate(gate.get("gate", "UNKNOWN")) or "Unknown"
        owner_label = (
            _describe_code(gate.get("actionOwner", "Unknown"), {}) or "Unknown"
        )
        blockers.append(
            {
                "gate": gate_label,
                "owner": owner_label,
                "action_time": _format_blocker_time(gate.get("actionTime")),
            }
        )
    return blockers


def build_order_insights(order_entry: Dict[str, Any]) -> Dict[str, Any]:
    order = order_entry.get("order", {}) or {}
    details = order_entry.get("details", {}) or {}
    tasks = details.get("tasks", {}) or {}

    scheduling = tasks.get("scheduling", {}) or {}
    registration = tasks.get("registration", {}) or {}
    final_payment = tasks.get("finalPayment", {}) or {}
    final_payment_data = (
        final_payment.get("data", {}) if isinstance(final_payment, dict) else {}
    )

    financing_details = (
        (final_payment_data.get("financingDetails") or {}).get("teslaFinanceDetails")
    ) or {}
    currency_code = (final_payment.get("currencyFormat") or {}).get(
        "currencyCode"
    ) or final_payment_data.get("currencyCode")

    interest_rate = financing_details.get("interestRate")
    interest_display = f"{interest_rate}%" if interest_rate not in (None, "") else None
    term_months = financing_details.get("termsInMonths")
    term_display = f"{term_months} months" if term_months not in (None, "") else None

    finance_items = _build_items(
        [
            ("Payment Status", _describe_payment_status(final_payment.get("status"))),
            ("Finance Partner", financing_details.get("financePartnerName")),
            (
                "Product Type",
                _describe_finance_product(
                    financing_details.get("financePartnerType")
                    or final_payment.get("orderType")
                ),
            ),
            ("Interest Rate", interest_display),
            (
                "Monthly Payment",
                _format_currency(
                    financing_details.get("monthlyPayment"), currency_code
                ),
            ),
            ("Term", term_display),
            (
                "Down Payment",
                _format_currency(
                    financing_details.get("downpaymentToLessor"), currency_code
                ),
            ),
            (
                "Customer Amount Due",
                _format_currency(final_payment.get("amountDue"), currency_code),
            ),
            (
                "Amount Sent",
                _format_currency(final_payment.get("amountSent"), currency_code),
            ),
            (
                "Lender Amount Due",
                _format_currency(
                    final_payment_data.get("amountDueFromLender"), currency_code
                ),
            ),
        ]
    )

    readiness = (
        final_payment_data.get("deliveryReadinessDetail")
        or final_payment_data.get("deliveryReadiness")
        or {}
    )

    delivery_items = _build_items(
        [
            (
                "Delivery Type",
                _describe_delivery_type(
                    scheduling.get("deliveryType")
                    or final_payment_data.get("deliveryType")
                ),
            ),
            (
                "Pickup Location",
                scheduling.get("deliveryAddressTitle")
                or (final_payment_data.get("deliveryAddress") or {}).get("address1")
                or final_payment_data.get("pickupLocation"),
            ),
            ("Ready To Accept", scheduling.get("readyToAccept")),
            ("Self-Scheduling", scheduling.get("selfSchedulingUrl")),
            (
                "Appointment Status",
                _describe_appointment_status(scheduling.get("appointmentStatusName")),
            ),
            ("Tesla Actions Pending", readiness.get("hasTeslaAction")),
            ("Customer Actions Pending", readiness.get("hasCustomerAction")),
            ("Has Blocker", readiness.get("hasBlocker")),
        ]
    )

    registration_details = registration.get("orderDetails", {}) or {}
    registration_items = _build_items(
        [
            (
                "Registration Status",
                _describe_registration_status(
                    registration_details.get("registrationStatus")
                    or registration.get("status")
                ),
            ),
            (
                "Registrant Type",
                _describe_registrant_type(
                    registration_details.get("registrantType")
                    or registration.get("registrantType")
                ),
            ),
            (
                "Order Placed",
                _format_timestamp(registration_details.get("orderPlacedDate")),
            ),
            (
                "Order Booked",
                _format_timestamp(registration_details.get("orderBookedDate")),
            ),
            (
                "Primary Registrant",
                registration.get("strings", {}).get("messageBody")
                or registration_details.get("primaryRegistrantType"),
            ),
            (
                "Country",
                registration_details.get("countryCode") or order.get("countryCode"),
            ),
            (
                "Delivery Alerts",
                registration.get("alertStatuses", {}).get("regDelivery"),
            ),
        ]
    )

    metadata_items = _build_items(
        [
            ("Order Status", _describe_order_status(order.get("orderStatus"))),
            ("Order Substatus", _describe_order_substatus(order.get("orderSubstatus"))),
            ("Vehicle Map ID", order.get("vehicleMapId")),
            ("Locale", _describe_locale(order.get("locale"))),
            ("B2B Order", order.get("isB2b")),
            ("Used Vehicle", order.get("isUsed")),
        ]
    )

    metadata_items.extend(describe_market_options(order.get("mktOptions")))

    blockers = _extract_delivery_blockers(readiness)

    return {
        "finance": finance_items,
        "delivery": delivery_items,
        "registration": registration_items,
        "metadata": metadata_items,
        "blockers": blockers,
    }


def build_order_progress(order_entry: Dict[str, Any]) -> Dict[str, Any]:
    order = order_entry.get("order", {}) or {}
    details = order_entry.get("details", {}) or {}
    tasks = details.get("tasks", {}) or {}
    scheduling = tasks.get("scheduling", {}) or {}
    registration = tasks.get("registration", {}) or {}
    registration_details = registration.get("orderDetails", {}) or {}
    delivery_details = tasks.get("deliveryDetails", {}) or {}
    delivery_reg_data = delivery_details.get("regData", {}) or {}
    final_payment = tasks.get("finalPayment", {}) or {}
    final_payment_data = (
        final_payment.get("data", {}) if isinstance(final_payment, dict) else {}
    )

    order_status = str(order.get("orderStatus") or "").upper()
    today = datetime.utcnow().date()

    def format_timestamp(value: Any) -> Optional[str]:
        return _format_timestamp(value) if value not in (None, "") else None

    def format_date_only(value: Any) -> Optional[str]:
        return _format_date_only(value) if value not in (None, "") else None

    def scrub_text(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        text = str(value).strip()
        return text or None

    def parse_numeric(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            try:
                numeric = float(value)
            except (ValueError, TypeError):
                return None
            return numeric if math.isfinite(numeric) else None
        text = str(value).strip()
        if not text:
            return None
        cleaned = text.replace(",", "")
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        try:
            numeric = float(match.group(0))
            return numeric if math.isfinite(numeric) else None
        except ValueError:
            return None

    def parse_iso_datetime(value: Any) -> Optional[datetime]:
        if value in (None, ""):
            return None
        try:
            raw = str(value).strip()
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            return datetime.fromisoformat(raw)
        except Exception:  # pragma: no cover - defensive parse
            return None

    def normalize_code_token(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        token = re.sub(r"[^A-Z0-9]+", "_", str(value).strip().upper())
        token = token.strip("_")
        return token or None

    odometer_raw = (
        registration_details.get("vehicleOdometer")
        or details.get("vehicleOdometer")
        or order.get("vehicleOdometer")
    )
    odometer_unit = (
        registration_details.get("vehicleOdometerType")
        or details.get("vehicleOdometerType")
        or order.get("vehicleOdometerType")
    )
    odometer_numeric = parse_numeric(odometer_raw)
    odometer_display = _format_vehicle_mileage(odometer_raw, odometer_unit)

    order_placed_raw = registration_details.get("orderPlacedDate") or order.get(
        "orderPlacedDate"
    )
    vin_value = scrub_text(order.get("vin"))
    vin_assigned_raw = (
        order.get("vinAssignmentDate")
        or order.get("vinMatchedDate")
        or registration_details.get("vinAssignmentDate")
    )
    production_timestamp = (
        order.get("vehicleProductionDate")
        or order.get("vehicleBuildDate")
        or order.get("buildCompletionDate")
    )

    eta_raw = final_payment_data.get("etaToDeliveryCenter") or order.get("eta")
    eta_display = format_date_only(eta_raw)
    eta_datetime = parse_iso_datetime(eta_raw)
    eta_date = eta_datetime.date() if eta_datetime else None
    in_transit_completed = eta_date is not None and eta_date <= today
    in_transit_has_eta = bool(eta_display)
    eta_labeled = f"ETA: {eta_display}" if eta_display else None
    eta_timestamp = eta_labeled if eta_display else None
    ready_window_primary = scrub_text(scheduling.get("apptDateTimeAddressStr"))
    ready_datetime = parse_iso_datetime(ready_window_primary)
    ready_window_fallback = scrub_text(
        scheduling.get("deliveryWindowDisplay") or scheduling.get("deliveryWindow")
    )
    ready_window_display = _shorten_delivery_window_display(ready_window_fallback)
    if ready_window_primary:
        ready_meta_label = "Appointment"
        ready_meta_value = ready_window_primary
    elif ready_window_fallback:
        ready_meta_label = "Window"
        ready_meta_value = ready_window_display or ready_window_fallback
    else:
        ready_meta_label = None
        ready_meta_value = None
    ready_timestamp = (ready_datetime.isoformat() if ready_datetime else None) or (
        scheduling.get("appointmentDateUtc")
        or scheduling.get("appointmentDate")
        or scheduling.get("apptDateTime")
    )
    delivered_flag = "DELIVERED" in order_status
    delivered_timestamp = (
        order.get("deliveryDate")
        or order.get("deliveredOn")
        or order.get("deliveredDate")
    )

    production_complete = (
        odometer_numeric is not None and abs(odometer_numeric - 30) > 1e-6
    )
    ready_flag = ready_datetime is not None
    registration_status_raw = registration_details.get(
        "registrationStatus"
    ) or registration.get("status")
    registration_status_normalized = normalize_code_token(registration_status_raw)
    registration_status_label = (
        _describe_registration_status(registration_status_raw)
        or scrub_text(registration_status_raw)
        or "Unknown"
    )
    reggie_license_plate = scrub_text(
        delivery_reg_data.get("reggieLicensePlate")
        or registration.get("reggieLicensePlate")
        or registration_details.get("reggieLicensePlate")
    )
    registration_completion_codes = {
        "COMPLETED",
        "COMPLETE",
        "APPROVED",
        "SUBMITTED",
    }
    registration_complete = (
        registration_status_normalized in registration_completion_codes
    )
    registration_timestamp_raw = (
        registration_details.get("registrationCompletionDate")
        or registration_details.get("registrationStartDate")
        or registration.get("startedOn")
    )

    stages: List[Dict[str, Any]] = [
        {
            "key": "order_placed",
            "label": "Order Placed",
            "description": "Reservation submitted and RN assigned.",
            "completed": bool(order_placed_raw),
            "timestamp": format_timestamp(order_placed_raw),
        },
        {
            "key": "vin_assigned",
            "label": "VIN Assigned",
            "description": "Tesla matched a specific vehicle to your RN.",
            "completed": bool(vin_value),
            "timestamp": format_timestamp(vin_assigned_raw),
            "meta_label": "VIN",
            "meta_value": vin_value,
        },
        {
            "key": "production",
            "label": "In Production",
            "description": "Factory scheduling or build in progress.",
            "completed": production_complete,
            "timestamp": format_timestamp(production_timestamp),
            "meta_label": "Odometer",
            "meta_value": odometer_display or "Awaiting update",
        },
        {
            "key": "in_transit",
            "label": "In Transit",
            "description": "Vehicle departed the factory toward your delivery hub.",
            "completed": in_transit_completed,
            "timestamp": eta_timestamp,
            "meta_label": "ETA",
            "meta_value": eta_labeled,
            "has_eta": in_transit_has_eta,
        },
        {
            "key": "registration",
            "label": "Registration",
            "description": "Paperwork with your DMV or agency to secure plates.",
            "completed": registration_complete,
            "timestamp": format_timestamp(registration_timestamp_raw),
            "meta_label": "Plate" if reggie_license_plate else "Status",
            "meta_value": reggie_license_plate or registration_status_label,
        },
        {
            "key": "ready",
            "label": "Ready For Delivery",
            "description": "Delivery center appointment or pickup window confirmed.",
            "completed": ready_flag,
            "timestamp": format_timestamp(ready_timestamp),
            "meta_label": ready_meta_label,
            "meta_value": ready_meta_value,
        },
        {
            "key": "delivered",
            "label": "Delivered",
            "description": "Vehicle handed off and paperwork closed.",
            "completed": delivered_flag,
            "timestamp": format_timestamp(delivered_timestamp),
        },
    ]

    first_incomplete = next(
        (idx for idx, stage in enumerate(stages) if not stage["completed"]),
        len(stages),
    )
    for idx, stage in enumerate(stages):
        if stage["completed"]:
            stage["state"] = "complete"
            stage["state_label"] = "Complete"
        elif idx == first_incomplete:
            stage["state"] = "active"
            stage["state_label"] = "In Progress"
        else:
            stage["state"] = "upcoming"
            stage["state_label"] = "Pending"
        if stage["key"] == "in_transit" and not stage["completed"]:
            if not stage.get("has_eta"):
                stage["state"] = "upcoming"
                stage["state_label"] = "Pending"

    completed_count = sum(1 for stage in stages if stage["completed"])
    total = len(stages)
    percent = int(round((completed_count / total) * 100)) if total else 0

    return {
        "stages": stages,
        "completed": completed_count,
        "total": total,
        "percent": percent,
        "active_index": min(first_incomplete, total - 1) if total else 0,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    access_token, token_bundle = _ensure_request_tokens(request)
    if not access_token or not token_bundle:
        return _redirect_to_login(clear=True)

    try:
        detailed_orders = _collect_order_entries(access_token)
    except Exception as exc:
        logger.error("Failed to fetch Tesla orders: %s", exc)
        response = HTMLResponse(
            content=f"Failed to load orders: {exc}", status_code=500
        )
        return _finalize_response(response, token_bundle)

    formatted_orders = _format_orders(detailed_orders)
    context = {
        "request": request,
        "orders": formatted_orders,
        "orders_json": formatted_orders,
        "refreshed": request.query_params.get("refreshed") == "1",
    }
    response = templates.TemplateResponse("index.html", context)
    return _finalize_response(response, token_bundle)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    login_params = monitor.generate_login_params()
    auth_url = login_params["auth_url"]
    response = templates.TemplateResponse(
        "login.html", {"request": request, "auth_url": auth_url}
    )
    response.set_cookie(
        key="tesla_code_verifier",
        value=login_params["code_verifier"],
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return _finalize_response(response, clear=True)


@app.get("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    response = templates.TemplateResponse("logout.html", {"request": request})
    return _finalize_response(response, clear=True)


@app.post("/callback")
async def callback(request: Request, url: str = Form(...)):
    code_verifier = request.cookies.get("tesla_code_verifier")
    if not code_verifier:
        logger.error("Login failed: Missing code_verifier cookie")
        return HTMLResponse(
            content="Login failed: Missing session data (code_verifier). Please try logging in again.",
            status_code=400,
        )

    try:
        code = monitor.parse_redirect_url(url)
        tokens = monitor.exchange_code_for_tokens(code, code_verifier)
    except Exception as exc:
        logger.error("Login failed: %s", exc)
        return HTMLResponse(content=f"Login failed: {exc}", status_code=400)

    context = {"request": request, "tokens": tokens}
    response = templates.TemplateResponse("callback_success.html", context)
    response.delete_cookie("tesla_code_verifier")
    return _finalize_response(response, tokens)


@app.get("/refresh")
async def refresh_redirect(request: Request):
    access_token, token_bundle = _ensure_request_tokens(request)
    if not access_token or not token_bundle:
        return _redirect_to_login(clear=True)
    response = RedirectResponse(url="/?refreshed=1", status_code=303)
    return _finalize_response(response, token_bundle)


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    response = templates.TemplateResponse("history.html", {"request": request})
    return _finalize_response(response)


@app.get("/sw.js")
async def service_worker() -> FileResponse:
    response = FileResponse(SW_FILE, media_type="application/javascript")
    # Ensure Cloudflare/browser never cache the worker so updates propagate immediately
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
