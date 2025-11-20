from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .monitor import TeslaOrderMonitor
from .vin_decoder import VinDecoder

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SW_FILE = STATIC_DIR / "sw.js"

app = FastAPI(title="Tesla Order Status")
monitor = TeslaOrderMonitor()
vin_decoder = VinDecoder()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

logger = logging.getLogger(__name__)

TOKEN_HEADER = "x-tesla-bundle"
CLEAR_HEADER = "x-tesla-clear"


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
    response: HTMLResponse | RedirectResponse,
    token_bundle: Optional[Dict[str, Any]] = None,
    *,
    clear: bool = False,
) -> HTMLResponse | RedirectResponse:
    response.headers["Cache-Control"] = "no-store"
    if clear:
        response.headers[CLEAR_HEADER] = "1"
    elif token_bundle:
        response.headers[TOKEN_HEADER] = _encode_token_bundle(token_bundle)
    return response


def _redirect_to_login(clear: bool = False) -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    return _finalize_response(response, clear=clear)


def _ensure_request_tokens(request: Request) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    token_bundle = _extract_tokens(request)
    if not token_bundle:
        return None, None
    access_token, updated_bundle = monitor.ensure_authenticated(token_bundle)
    return access_token, updated_bundle


def _collect_order_entries(access_token: str) -> List[Dict[str, Any]]:
    basic_orders = monitor.retrieve_orders(access_token)
    detailed_orders: List[Dict[str, Any]] = []
    for order in basic_orders:
        order_id = order.get('referenceNumber')
        if not order_id:
            continue
        details = monitor.get_order_details(order_id, access_token)
        detailed_orders.append({'order': order, 'details': details})
    return detailed_orders


def _format_orders(order_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formatted_orders: List[Dict[str, Any]] = []
    for order_data in order_entries:
        order = order_data['order']
        details = order_data['details']

        scheduling = details.get('tasks', {}).get('scheduling', {})
        order_info = details.get('tasks', {}).get('registration', {}).get('orderDetails', {})
        final_payment = details.get('tasks', {}).get('finalPayment', {}).get('data', {})

        image_urls = monitor.get_vehicle_image_urls(order['modelCode'], order.get('mktOptions', ''))
        tasks = monitor.parse_tasks(details.get('tasks', {}))

        vin = order.get('vin')
        vin_details = vin_decoder.decode(vin) if vin else None

        formatted_orders.append({
            'rn': order['referenceNumber'],
            'model': order['modelCode'].upper(),
            'vin': vin or 'N/A',
            'vin_details': vin_details,
            'status': order.get('orderStatus', 'unknown'),
            'delivery_date': scheduling.get('apptDateTimeAddressStr', 'Not Scheduled'),
            'delivery_window': scheduling.get('deliveryWindowDisplay', 'TBD'),
            'location': monitor.get_store_label(order_info.get('vehicleRoutingLocation', 0)),
            'eta': final_payment.get('etaToDeliveryCenter', 'Unknown'),
            'image_urls': image_urls,
            'tasks': tasks,
            'insights': build_order_insights(order_data),
            'raw_payload': order_data
        })
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
        if raw.endswith('Z'):
            raw = raw[:-1] + '+00:00'
        return datetime.fromisoformat(raw).strftime("%d %b %Y %H:%M")
    except Exception:  # pragma: no cover - fallback
        return str(value)


def _build_items(pairs: List[tuple[str, Any]]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for label, value in pairs:
        if value in (None, "", []):
            continue
        if isinstance(value, bool):
            display = "Yes" if value else "No"
        else:
            display = str(value)
        items.append({"label": label, "value": display})
    return items


def _extract_delivery_blockers(readiness: Dict[str, Any]) -> List[Dict[str, str]]:
    gates = readiness.get('gates') or []
    gate_iterable = gates.values() if isinstance(gates, dict) else gates

    blockers: List[Dict[str, str]] = []
    for gate in gate_iterable:
        if not isinstance(gate, dict) or not gate.get('isBlocker'):
            continue
        blockers.append({
            "gate": str(gate.get('gate', 'UNKNOWN')),
            "owner": str(gate.get('actionOwner', 'Unknown')),
            "action_time": str(gate.get('actionTime', 'N/A')),
        })
    return blockers


def build_order_insights(order_entry: Dict[str, Any]) -> Dict[str, Any]:
    order = order_entry.get('order', {}) or {}
    details = order_entry.get('details', {}) or {}
    tasks = details.get('tasks', {}) or {}

    scheduling = tasks.get('scheduling', {}) or {}
    registration = tasks.get('registration', {}) or {}
    final_payment = tasks.get('finalPayment', {}) or {}
    final_payment_data = final_payment.get('data', {}) if isinstance(final_payment, dict) else {}

    financing_details = ((final_payment_data.get('financingDetails') or {}).get('teslaFinanceDetails')) or {}
    currency_code = (final_payment.get('currencyFormat') or {}).get('currencyCode') \
        or final_payment_data.get('currencyCode')

    interest_rate = financing_details.get('interestRate')
    interest_display = f"{interest_rate}%" if interest_rate not in (None, "") else None
    term_months = financing_details.get('termsInMonths')
    term_display = f"{term_months} months" if term_months not in (None, "") else None

    finance_items = _build_items([
        ("Payment Status", final_payment.get('status')),
        ("Finance Partner", financing_details.get('financePartnerName')),
        ("Product Type", financing_details.get('financePartnerType') or final_payment.get('orderType')),
        ("Interest Rate", interest_display),
        ("Monthly Payment", _format_currency(financing_details.get('monthlyPayment'), currency_code)),
        ("Term", term_display),
        ("Down Payment", _format_currency(financing_details.get('downpaymentToLessor'), currency_code)),
        ("Customer Amount Due", _format_currency(final_payment.get('amountDue'), currency_code)),
        ("Amount Sent", _format_currency(final_payment.get('amountSent'), currency_code)),
        ("Lender Amount Due", _format_currency(final_payment_data.get('amountDueFromLender'), currency_code)),
    ])

    readiness = final_payment_data.get('deliveryReadinessDetail') \
        or final_payment_data.get('deliveryReadiness') \
        or {}

    delivery_items = _build_items([
        ("Delivery Type", scheduling.get('deliveryType') or final_payment_data.get('deliveryType')),
        (
            "Pickup Location",
            scheduling.get('deliveryAddressTitle')
            or (final_payment_data.get('deliveryAddress') or {}).get('address1')
            or final_payment_data.get('pickupLocation'),
        ),
        ("Ready To Accept", scheduling.get('readyToAccept')),
        ("Self-Scheduling", scheduling.get('selfSchedulingUrl')),
        ("Appointment Status", scheduling.get('appointmentStatusName')),
        ("Tesla Actions Pending", readiness.get('hasTeslaAction')),
        ("Customer Actions Pending", readiness.get('hasCustomerAction')),
        ("Has Blocker", readiness.get('hasBlocker')),
    ])

    registration_details = registration.get('orderDetails', {}) or {}
    registration_items = _build_items([
        ("Registration Status", registration_details.get('registrationStatus') or registration.get('status')),
        ("Registrant Type", registration_details.get('registrantType') or registration.get('registrantType')),
        ("Order Placed", _format_timestamp(registration_details.get('orderPlacedDate'))),
        ("Order Booked", _format_timestamp(registration_details.get('orderBookedDate'))),
        (
            "Primary Registrant",
            registration.get('strings', {}).get('messageBody') or registration_details.get('primaryRegistrantType'),
        ),
        ("Country", registration_details.get('countryCode') or order.get('countryCode')),
        ("Delivery Alerts", registration.get('alertStatuses', {}).get('regDelivery')),
    ])

    metadata_items = _build_items([
        ("Order Status", order.get('orderStatus')),
        ("Order Substatus", order.get('orderSubstatus')),
        ("Vehicle Map ID", order.get('vehicleMapId')),
        ("Locale", order.get('locale')),
        ("Market Options", order.get('mktOptions')),
        ("B2B Order", order.get('isB2b')),
        ("Used Vehicle", order.get('isUsed')),
    ])

    blockers = _extract_delivery_blockers(readiness)

    return {
        "finance": finance_items,
        "delivery": delivery_items,
        "registration": registration_items,
        "metadata": metadata_items,
        "blockers": blockers,
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
        response = HTMLResponse(content=f"Failed to load orders: {exc}", status_code=500)
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
    auth_url = monitor.get_auth_url()
    response = templates.TemplateResponse("login.html", {"request": request, "auth_url": auth_url})
    return _finalize_response(response, clear=True)


@app.get("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    response = templates.TemplateResponse("logout.html", {"request": request})
    return _finalize_response(response, clear=True)


@app.post("/callback")
async def callback(request: Request, url: str = Form(...)):
    try:
        code = monitor.parse_redirect_url(url)
        tokens = monitor.exchange_code_for_tokens(code)
    except Exception as exc:
        logger.error("Login failed: %s", exc)
        return HTMLResponse(content=f"Login failed: {exc}", status_code=400)

    context = {"request": request, "tokens": tokens}
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
    response = templates.TemplateResponse("history.html", {"request": request})
    return _finalize_response(response)


@app.get("/sw.js")
async def service_worker() -> FileResponse:
    return FileResponse(SW_FILE, media_type="application/javascript")
