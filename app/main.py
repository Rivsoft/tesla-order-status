from __future__ import annotations

import base64
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .metrics import build_metrics_from_env
from .monitor import TeslaOrderMonitor
from .vin_decoder import VinDecoder
from .i18n import i18n, LANG_COOKIE_NAME

# Dummy translation function for extraction
def _(s: str) -> str:
    return s

# Mapping of category names to their translated labels
CATEGORY_LABELS = {
    "Vehicle": _("Vehicle Options"),
    "Drive": _("Drive Options"),
    "Performance": _("Performance Options"),
    "Manufacturing": _("Manufacturing Options"),
    "Towing": _("Towing Options"),
    "Battery": _("Battery Options"),
    "Paint": _("Paint Options"),
    "Wheels": _("Wheels Options"),
    "Suspension": _("Suspension Options"),
    "Interior": _("Interior Options"),
    "Seating": _("Seating Options"),
    "Software": _("Software Options"),
    "Connectivity": _("Connectivity Options"),
    "Charging": _("Charging Options"),
    "Hardware": _("Hardware Options"),
    "Protection": _("Protection Options"),
}

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
    "MDL3": {"category": "Vehicle", "name": _("Model 3 platform")},
    "MDLY": {"category": "Vehicle", "name": _("Model Y platform")},
    "MDLS": {"category": "Vehicle", "name": _("Model S platform")},
    "MDLX": {"category": "Vehicle", "name": _("Model X platform")},
    "ADPX0": {"category": "Drive", "name": _("Rear-wheel drive single motor")},
    "ADPX1": {"category": "Drive", "name": _("Long Range dual motor")},
    "ADPX2": {"category": "Drive", "name": _("Performance dual motor")},
    "DUALMOTOR": {"category": "Drive", "name": _("Dual Motor AWD badging")},
    "DV4W": {"category": "Drive", "name": _("Dual motor all-wheel drive")},
    "P3WS": {"category": "Performance", "name": _("Performance Upgrade Package")},
    "MT322": {"category": "Manufacturing", "name": _("Model year 2022 Q2 build")},
    "MT337": {"category": "Manufacturing", "name": _("Model year 2023 Q4 build")},
    "MTY62": {"category": "Manufacturing", "name": _("Model Y Long Range AWD")},
    "TM00": {"category": "Towing", "name": _("Towing package deleted")},
    "TOW1": {"category": "Towing", "name": _("Factory tow package")},
    # Batteries / powertrain
    "BT37": {"category": "Battery", "name": _("Long Range battery pack")},
    "BT38": {"category": "Battery", "name": _("Standard Range battery pack")},
    "BT42": {"category": "Battery", "name": _("4680 structural battery pack")},
    "BP00": {"category": "Battery", "name": _("No Ludicrous upgrade")},
    # Paint options
    "PPSW": {"category": "Paint", "name": _("Pearl White Multi-Coat paint")},
    "PPMR": {"category": "Paint", "name": _("Red Multi-Coat paint")},
    "PMNG": {"category": "Paint", "name": _("Midnight Silver Metallic paint")},
    "PPSB": {"category": "Paint", "name": _("Deep Blue Metallic paint")},
    "PMBL": {"category": "Paint", "name": _("Obsidian Black Metallic paint")},
    "PMTL": {"category": "Paint", "name": _("Titanium Metallic paint")},
    "PBCW": {"category": "Paint", "name": _("Solid Black paint")},
    "PB02": {"category": "Paint", "name": _("Marine Blue")},
    # Wheels / tires / suspension
    "WTAS": {"category": "Wheels", "name": _('19" Sport Wheels')},
    "W38B": {"category": "Wheels", "name": _('18" Aero Wheels')},
    "W39B": {"category": "Wheels", "name": _('19" Sport Wheels')},
    "W40B": {"category": "Wheels", "name": _('20" Induction Wheels')},
    "W41B": {"category": "Wheels", "name": _('20" Gemini Wheels')},
    "WTUR": {"category": "Wheels", "name": _('21" Überturbine Wheels')},
    "WY19P": {"category": "Wheels", "name": _('19" Crossflow Wheels')},
    "ST33": {"category": "Suspension", "name": _("All-season tires")},
    "SU3C": {"category": "Suspension", "name": _("Coil suspension setup")},
    # Interior
    "IN3PB": {"category": "Interior", "name": _("Premium all-black interior")},
    "IN3PW": {"category": "Interior", "name": _("Premium black & white interior")},
    "INYPB": {"category": "Interior", "name": _("Model Y black interior")},
    "INYPW": {"category": "Interior", "name": _("Model Y black & white interior")},
    "IPB8": {"category": "Interior", "name": _("Premium all-black interior")},
    "IL31": {"category": "Interior", "name": _("Interior ambient lighting")},
    "AU3P": {"category": "Interior", "name": _("Premium audio system")},
    "AF02": {"category": "Interior", "name": _("Subzero weather / heated components")},
    # Comfort / seating
    "ST01": {"category": "Seating", "name": _("Front heated seats")},
    "RSF1": {"category": "Seating", "name": _("Rear heated seats")},
    "RSF2": {"category": "Seating", "name": _("Second row seat heaters")},
    "STY5S": {"category": "Seating", "name": _("MY 5 Seat Interior")},
    # Autopilot / software / connectivity
    "APBS": {"category": "Software", "name": _("Basic Autopilot")},
    "APF0": {"category": "Software", "name": _("Autopilot hardware with no features")},
    "APF1": {"category": "Software", "name": _("Autopilot convenience features")},
    "APF2": {"category": "Software", "name": _("Enhanced Autopilot")},
    "APF3": {"category": "Software", "name": _("Full Self-Driving computer (HW3)")},
    "APPB": {"category": "Software", "name": _("Full Self-Driving capability")},
    "ACC1": {"category": "Connectivity", "name": _("Premium connectivity")},
    "CPF0": {"category": "Connectivity", "name": _("Premium connectivity (trial)")},
    "CPF1": {
        "category": "Connectivity",
        "name": _("Premium connectivity (1 year included)"),
    },
    "SC04": {"category": "Charging", "name": _("Pay-as-you-go Supercharging")},
    "SC05": {"category": "Charging", "name": _("Free unlimited Supercharging")},
    # Safety / hardware
    "FR04": {"category": "Hardware", "name": _("HEPA filter & Bioweapon Defense Mode")},
    "HM31": {"category": "Hardware", "name": _("Power folding, heated side mirrors")},
    "HL32": {"category": "Hardware", "name": _("Matrix LED headlights")},
    "PI01": {"category": "Hardware", "name": _("Premium audio amplifier")},
    "DRLH": {"category": "Hardware", "name": _("Left-hand drive configuration")},
    "DRRH": {"category": "Hardware", "name": _("Right-hand drive configuration")},
    "OPPF": {"category": "Protection", "name": _("Factory paint protection film")},
    "BC3R": {"category": "Hardware", "name": _("Performance red brake calipers")},
}

OPTION_HINT_RULES: List[tuple[re.Pattern[str], tuple[str, str]]] = [
    (re.compile(r"^(PP|PM|PBC|PRS|PBS)"), ("Paint", _("Exterior paint option"))),
    (re.compile(r"^W\d+"), ("Wheels", _("Wheel package"))),
    (re.compile(r"^IN"), ("Interior", _("Interior trim or material"))),
    (re.compile(r"^AP|^FS|^FSD|^EAP"), ("Software", _("Autopilot or software package"))),
    (re.compile(r"^SC"), ("Charging", _("Supercharging config"))),
    (re.compile(r"^MDL|^MDY|^MDX"), ("Vehicle", _("Model designation"))),
    (re.compile(r"^BT"), ("Battery", _("Battery configuration"))),
    (re.compile(r"^ST|^RS"), ("Seating", _("Seat or interior comfort"))),
    (re.compile(r"^HP|^DU|^MT"), ("Performance", _("Drive-unit or performance upgrade"))),
    (re.compile(r"^PK|^PRM"), ("Package", _("Equipment package"))),
    (re.compile(r"^HM|^FR|^HL|^FG"), ("Hardware", _("Hardware feature"))),
]

DELIVERY_TYPE_DESCRIPTIONS: Dict[str, str] = {
    "PICKUP_SERVICE_CENTER": _("Pickup at service/delivery center"),
    "PICKUP_HOME": _("Home delivery"),
    "PICKUP_EXPRESS": _("Express pickup"),
    "PICKUP_DC": _("Delivery center appointment"),
    "PICKUP_STORE": _("Retail store pickup"),
    "PICKUP_DIRECT": _("Direct-to-customer handoff"),
}

PAYMENT_STATUS_DESCRIPTIONS: Dict[str, str] = {
    "MAKE_YOUR_FINAL_PAYMENT": _("Final payment required"),
    "PAYMENT_SUCCESS": _("Payment received"),
    "FUNDS_IN_TRANSIT": _("Funds in transit"),
    "PAYMENT_SCHEDULED": _("Payment scheduled"),
    "PAYMENT_PENDING": _("Payment pending"),
    "PAYMENT_NOT_REQUIRED": _("No payment required"),
    "PAYMENT_VERIFICATION": _("Payment under verification"),
}

APPOINTMENT_STATUS_DESCRIPTIONS: Dict[str, str] = {
    "NOT_SCHEDULED": _("Not scheduled"),
    "SCHEDULED": _("Appointment scheduled"),
    "CONFIRMED": _("Appointment confirmed"),
    "RESCHEDULED": _("Appointment rescheduled"),
    "AWAITING_CUSTOMER": _("Waiting for customer to schedule"),
    "AWAITING_TESLA": _("Tesla scheduling in progress"),
    "COMPLETED": _("Appointment completed"),
    "CANCELLED": _("Appointment cancelled"),
}

REGISTRATION_STATUS_DESCRIPTIONS: Dict[str, str] = {
    "NOT_STARTED": _("Registration not started"),
    "IN_PROGRESS": _("Registration in progress"),
    "SUBMITTED": _("Registration submitted"),
    "APPROVED": _("Registration approved"),
    "COMPLETED": _("Registration completed"),
    "PENDING": _("Registration pending review"),
}

REGISTRANT_TYPE_DESCRIPTIONS: Dict[str, str] = {
    "INDIVIDUAL": _("Individual registrant"),
    "BUSINESS": _("Business registrant"),
    "LEASE": _("Leased vehicle"),
    "COMPANY": _("Company-owned"),
    "GOVERNMENT": _("Government fleet"),
}

LOCALE_DESCRIPTIONS: Dict[str, str] = {
    "EN_US": _("English (United States)"),
    "EN_CA": _("English (Canada)"),
    "EN_GB": _("English (United Kingdom)"),
    "FR_FR": _("French (France)"),
    "FR_CA": _("French (Canada)"),
    "DE_DE": _("German (Germany)"),
    "NL_NL": _("Dutch (Netherlands)"),
    "ES_ES": _("Spanish (Spain)"),
    "ES_MX": _("Spanish (Mexico)"),
    "SV_SE": _("Swedish (Sweden)"),
}

ORDER_STATUS_DESCRIPTIONS: Dict[str, str] = {
    "NEW": _("Order placed"),
    "ORDERED": _("Order confirmed"),
    "BUILDING": _("Vehicle in production"),
    "BUILT": _("Vehicle built"),
    "IN_TRANSIT": _("Vehicle in transit"),
    "DELIVERED": _("Vehicle delivered"),
    "CANCELLED": _("Order cancelled"),
    "HOLD": _("Order on hold"),
}

ORDER_SUBSTATUS_DESCRIPTIONS: Dict[str, str] = {
    "ALLOCATION_PENDING": _("Awaiting factory allocation"),
    "VIN_ASSIGNED": _("VIN assigned"),
    "READY_FOR_DELIVERY": _("Ready for delivery"),
    "AWAITING_PAYMENT": _("Awaiting payment"),
    "DOCUMENTS_PENDING": _("Paperwork pending"),
}

FINANCE_PRODUCT_TYPE_DESCRIPTIONS: Dict[str, str] = {
    "RETAIL_LOAN": _("Retail loan"),
    "LEASE": _("Lease"),
    "CASH": _("Cash purchase"),
    "BALLOON": _("Balloon financing"),
    "TESLA_FINANCE": _("Tesla financing"),
}

DELIVERY_GATE_DESCRIPTIONS: Dict[str, str] = {
    "BEFORE_DELIVERY": _("Before-delivery readiness"),
    "AT_DELIVERY": _("Delivery-day handoff"),
    "AFTER_DELIVERY": _("Post-delivery follow-up"),
    "BEFORE_DELIVERY_FINANCE": _("Finance clearance before delivery"),
    "BEFORE_DELIVERY_DOCUMENTS": _("Paperwork before delivery"),
    "BEFORE_DELIVERY_VEHICLE": _("Vehicle prep before delivery"),
}

ACTION_OWNER_DESCRIPTIONS: Dict[str, str] = {
    "TESLA": _("Tesla"),
    "CUSTOMER": _("Customer"),
}

DELIVERY_TIMING_DESCRIPTIONS: Dict[str, str] = {
    "BEFORE_DELIVERY": _("Before delivery"),
    "AT_DELIVERY": _("During delivery"),
    "AFTER_DELIVERY": _("After delivery"),
    "POST_DELIVERY": _("Post-delivery"),
    "PRIOR_TO_APPOINTMENT": _("Prior to appointment"),
}

tr = lambda s: _(s) if s else s


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


def _collect_order_entries(
    access_token: str, force_refresh: bool = False
) -> List[Dict[str, Any]]:
    basic_orders = monitor.retrieve_orders(access_token, force_refresh=force_refresh)
    detailed_orders: List[Dict[str, Any]] = []
    for order in basic_orders:
        order_id = order.get("referenceNumber")
        if not order_id:
            continue
        details = monitor.get_order_details(
            order_id, access_token, force_refresh=force_refresh
        )
        detailed_orders.append({"order": order, "details": details})
    return detailed_orders


def _format_orders(
    order_entries: List[Dict[str, Any]], _: Callable[[str], str] = _
) -> List[Dict[str, Any]]:
    formatted_orders: List[Dict[str, Any]] = []
    for order_data in order_entries:
        order = order_data["order"]
        details = order_data["details"]

        tasks = details.get("tasks", {}) or {}
        scheduling = tasks.get("scheduling", {}) or {}
        registration_task = tasks.get("registration", {}) or {}
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

        summary_items = _build_items(
            [
                (
                    _("ETA to Delivery Center"),
                    final_payment_data.get("etaToDeliveryCenter") or order.get("eta"),
                ),
                (
                    _("Delivery Type"),
                    tr(
                        _describe_delivery_type(
                            scheduling.get("deliveryType")
                            or final_payment_data.get("deliveryType")
                        )
                    ),
                ),
                (
                    _("Pickup Address"),
                    scheduling.get("deliveryAddressTitle")
                    or (final_payment_data.get("deliveryAddress") or {}).get("address1")
                    or final_payment_data.get("pickupLocation"),
                ),
                (
                    _("Payment Status"),
                    tr(
                        _describe_payment_status(
                            final_payment_task.get("status")
                            if isinstance(final_payment_task, dict)
                            else None
                        )
                    ),
                ),
                (
                    _("Customer Amount Due"),
                    _format_currency(
                        (
                            final_payment_task.get("amountDue")
                            if isinstance(final_payment_task, dict)
                            else None
                        ),
                        currency_code,
                    ),
                ),
                (_("Order Placed"), _format_timestamp(order_info.get("orderPlacedDate"))),
                (_("Order Booked"), _format_timestamp(order_info.get("orderBookedDate"))),
            ],
            _,
        )

        image_urls = monitor.get_vehicle_image_urls(
            order["modelCode"], order.get("mktOptions", "")
        )
        tasks_list = monitor.parse_tasks(tasks)

        vin = order.get("vin")
        vin_details = vin_decoder.decode(vin) if vin else None

        formatted_orders.append(
            {
                "rn": order["referenceNumber"],
                "model": order["modelCode"].upper(),
                "vin": vin or _("N/A"),
                "vin_details": vin_details,
                "status": order.get("orderStatus", _("unknown")),
                "delivery_date": scheduling.get(
                    "apptDateTimeAddressStr", _("Not Scheduled")
                ),
                "delivery_window": scheduling.get("deliveryWindowDisplay", _("TBD")),
                "location": _(
                    monitor.get_store_label(order_info.get("vehicleRoutingLocation", 0))
                ),
                "eta": final_payment_data.get("etaToDeliveryCenter", _("Unknown")),
                "image_urls": image_urls,
                "tasks": tasks_list,
                "summary_items": summary_items,
                "insights": build_order_insights(order_data),
                "raw_payload": order_data,
            }
        )
    return formatted_orders


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


def _build_items(
    pairs: List[tuple[str, Any]], _: Callable[[str], str] = _
) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for label, value in pairs:
        if value in (None, "", []):
            continue
        if isinstance(value, bool):
            display = _("Yes") if value else _("No")
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


def describe_market_options(
    option_blob: Any, _: Callable[[str], str] = _
) -> List[Dict[str, str]]:
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
            entry = _(info["name"])
            if code not in entry:
                entry = f"{entry} ({code})"
            grouped[info["category"]].append(entry)
        else:
            unknown.append(code)

    items: List[Dict[str, str]] = []
    for category, values in sorted(grouped.items()):
        if not values:
            continue
        label = _(CATEGORY_LABELS.get(category, f"{category} Options"))
        items.append(
            {"label": label, "value": ", ".join(dict.fromkeys(values))}
        )

    for code in dict.fromkeys(sorted(unknown)):
        label, description = _infer_option_hint(code)
        items.append({"label": _(label), "value": f"{_(description)} ({code})"})

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
        return _("Option"), _("Unrecognized option")
    for pattern, (label, description) in OPTION_HINT_RULES:
        if pattern.match(code):
            return label, description
    return _("Option"), _("Custom configuration")


def _format_blocker_time(value: Any, _: Callable[[str], str] = _) -> str:
    if value in (None, ""):
        return _("N/A")
    key = str(value).upper()
    if key in DELIVERY_TIMING_DESCRIPTIONS:
        return _(DELIVERY_TIMING_DESCRIPTIONS[key])
    timestamp = _format_timestamp(value)
    if timestamp and timestamp != str(value):
        return timestamp
    described = _describe_delivery_timing(value)
    return _(described) if described else str(value)


def _extract_delivery_blockers(
    readiness: Dict[str, Any], _: Callable[[str], str] = _
) -> List[Dict[str, str]]:
    gates = readiness.get("gates") or []
    gate_iterable = gates.values() if isinstance(gates, dict) else gates

    blockers: List[Dict[str, str]] = []
    for gate in gate_iterable:
        if not isinstance(gate, dict) or not gate.get("isBlocker"):
            continue
        gate_val = _describe_delivery_gate(gate.get("gate", "UNKNOWN"))
        gate_label = _(gate_val) if gate_val else _("Unknown")

        owner_val = _describe_code(
            gate.get("actionOwner", "Unknown"), ACTION_OWNER_DESCRIPTIONS
        )
        owner_label = _(owner_val) if owner_val else _("Unknown")

        blockers.append(
            {
                "gate": gate_label,
                "owner": owner_label,
                "action_time": _format_blocker_time(gate.get("actionTime"), _),
            }
        )
    return blockers


def build_order_insights(
    order_entry: Dict[str, Any], _: Callable[[str], str] = _
) -> Dict[str, Any]:
    tr = lambda s: _(s) if s else s
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
    term_display = (
        f"{term_months} {_('months')}" if term_months not in (None, "") else None
    )

    finance_items = _build_items(
        [
            (
                _("Payment Status"),
                tr(_describe_payment_status(final_payment.get("status"))),
            ),
            (_("Finance Partner"), financing_details.get("financePartnerName")),
            (
                _("Product Type"),
                tr(
                    _describe_finance_product(
                        financing_details.get("financePartnerType")
                        or final_payment.get("orderType")
                    )
                ),
            ),
            (_("Interest Rate"), interest_display),
            (
                _("Monthly Payment"),
                _format_currency(
                    financing_details.get("monthlyPayment"), currency_code
                ),
            ),
            (_("Term"), term_display),
            (
                _("Down Payment"),
                _format_currency(
                    financing_details.get("downpaymentToLessor"), currency_code
                ),
            ),
            (
                _("Customer Amount Due"),
                _format_currency(final_payment.get("amountDue"), currency_code),
            ),
            (
                _("Amount Sent"),
                _format_currency(final_payment.get("amountSent"), currency_code),
            ),
            (
                _("Lender Amount Due"),
                _format_currency(
                    final_payment_data.get("amountDueFromLender"), currency_code
                ),
            ),
        ],
        _,
    )

    readiness = (
        final_payment_data.get("deliveryReadinessDetail")
        or final_payment_data.get("deliveryReadiness")
        or {}
    )

    delivery_items = _build_items(
        [
            (
                _("Delivery Type"),
                tr(
                    _describe_delivery_type(
                        scheduling.get("deliveryType")
                        or final_payment_data.get("deliveryType")
                    )
                ),
            ),
            (
                _("Pickup Location"),
                scheduling.get("deliveryAddressTitle")
                or (final_payment_data.get("deliveryAddress") or {}).get("address1")
                or final_payment_data.get("pickupLocation"),
            ),
            (_("Ready To Accept"), scheduling.get("readyToAccept")),
            (_("Self-Scheduling"), scheduling.get("selfSchedulingUrl")),
            (
                _("Appointment Status"),
                tr(
                    _describe_appointment_status(
                        scheduling.get("appointmentStatusName")
                    )
                ),
            ),
            (_("Tesla Actions Pending"), readiness.get("hasTeslaAction")),
            (_("Customer Actions Pending"), readiness.get("hasCustomerAction")),
            (_("Has Blocker"), readiness.get("hasBlocker")),
        ],
        _,
    )

    registration_details = registration.get("orderDetails", {}) or {}
    registration_items = _build_items(
        [
            (
                _("Registration Status"),
                tr(
                    _describe_registration_status(
                        registration_details.get("registrationStatus")
                        or registration.get("status")
                    )
                ),
            ),
            (
                _("Registrant Type"),
                tr(
                    _describe_registrant_type(
                        registration_details.get("registrantType")
                        or registration.get("registrantType")
                    )
                ),
            ),
            (
                _("Order Placed"),
                _format_timestamp(registration_details.get("orderPlacedDate")),
            ),
            (
                _("Order Booked"),
                _format_timestamp(registration_details.get("orderBookedDate")),
            ),
            (
                _("Primary Registrant"),
                registration.get("strings", {}).get("messageBody")
                or registration_details.get("primaryRegistrantType"),
            ),
            (
                _("Country"),
                registration_details.get("countryCode") or order.get("countryCode"),
            ),
            (
                _("Delivery Alerts"),
                registration.get("alertStatuses", {}).get("regDelivery"),
            ),
        ],
        _,
    )

    metadata_items = _build_items(
        [
            (
                _("Order Status"),
                tr(_describe_order_status(order.get("orderStatus"))),
            ),
            (
                _("Order Substatus"),
                tr(_describe_order_substatus(order.get("orderSubstatus"))),
            ),
            (_("Vehicle Map ID"), order.get("vehicleMapId")),
            (_("Locale"), tr(_describe_locale(order.get("locale")))),
            (_("B2B Order"), order.get("isB2b")),
            (_("Used Vehicle"), order.get("isUsed")),
        ],
        _,
    )

    metadata_items.extend(describe_market_options(order.get("mktOptions"), _))

    blockers = _extract_delivery_blockers(readiness, _)

    return {
        "finance": finance_items,
        "delivery": delivery_items,
        "registration": registration_items,
        "metadata": metadata_items,
        "blockers": blockers,
    }


def get_template_context(request: Request, **kwargs):
    locale = i18n.get_locale(request)
    translations = i18n.get_translation(locale)

    context = {
        "request": request,
        "_": translations.gettext,
        "locale": locale,
        **kwargs
    }
    return context


@app.get("/set-language")
async def set_language(request: Request, lang: str, next_url: str = "/"):
    if lang not in i18n.supported_locales:
        lang = i18n.default_locale
    
    # Validate next_url to prevent open redirects (basic check)
    if not next_url.startswith("/"):
        next_url = "/"
        
    response = RedirectResponse(url=next_url, status_code=303)
    response.set_cookie(key=LANG_COOKIE_NAME, value=lang, max_age=365*24*60*60)
    return response


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    access_token, token_bundle = _ensure_request_tokens(request)
    if not access_token or not token_bundle:
        return _redirect_to_login(clear=True)

    force_refresh = request.query_params.get("refreshed") == "1"

    try:
        detailed_orders = _collect_order_entries(
            access_token, force_refresh=force_refresh
        )
    except Exception as exc:
        logger.error("Failed to fetch Tesla orders: %s", exc)
        response = HTMLResponse(
            content=f"Failed to load orders: {exc}", status_code=500
        )
        return _finalize_response(response, token_bundle)

    locale = i18n.get_locale(request)
    translations = i18n.get_translation(locale)
    _ = translations.gettext

    formatted_orders = _format_orders(detailed_orders, _)
    # Generate a language-neutral version for the history snapshot
    snapshot_orders = _format_orders(detailed_orders, lambda s: s)

    context = get_template_context(
        request,
        orders=formatted_orders,
        orders_json=snapshot_orders,
        refreshed=force_refresh,
    )
    response = templates.TemplateResponse("index.html", context)
    return _finalize_response(response, token_bundle)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    auth_url = monitor.get_auth_url()
    response = templates.TemplateResponse(
        "login.html", get_template_context(request, auth_url=auth_url)
    )
    return _finalize_response(response, clear=True)


@app.get("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    response = templates.TemplateResponse("logout.html", get_template_context(request))
    return _finalize_response(response, clear=True)


@app.post("/callback")
async def callback(request: Request, url: str = Form(...)):
    try:
        code = monitor.parse_redirect_url(url)
        tokens = monitor.exchange_code_for_tokens(code)
    except Exception as exc:
        logger.error("Login failed: %s", exc)
        return HTMLResponse(content=f"Login failed: {exc}", status_code=400)

    context = get_template_context(request, tokens=tokens)
    response = templates.TemplateResponse("callback_success.html", context)
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
    response = templates.TemplateResponse("history.html", get_template_context(request))
    return _finalize_response(response)


@app.get("/sw.js")
async def service_worker() -> FileResponse:
    return FileResponse(SW_FILE, media_type="application/javascript")
