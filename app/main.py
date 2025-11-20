from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime
from typing import Any, Dict, List, Optional
from .monitor import TeslaOrderMonitor
from .vin_decoder import VinDecoder
import logging
import os

app = FastAPI(title="Tesla Order Status")
monitor = TeslaOrderMonitor()
vin_decoder = VinDecoder()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

logger = logging.getLogger(__name__)


def _format_currency(amount: Any, currency: Optional[str]) -> Optional[str]:
    if amount in (None, ""):
        return None
    try:
        numeric = float(str(amount))
        formatted = f"{numeric:,.2f}"
    except (ValueError, TypeError):
        formatted = str(amount)
    return f"{currency} {formatted}".strip() if currency else formatted


def _format_timestamp(value: Any) -> str | None:
    if not value:
        return None
    try:
        raw = str(value)
        if raw.endswith('Z'):
            raw = raw[:-1] + '+00:00'
        return datetime.fromisoformat(raw).strftime("%d %b %Y %H:%M")
    except Exception:
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
    if isinstance(gates, dict):
        gate_iterable = gates.values()
    else:
        gate_iterable = gates

    blockers: List[Dict[str, str]] = []
    for gate in gate_iterable:
        if not isinstance(gate, dict):
            continue
        if not gate.get('isBlocker'):
            continue
        blockers.append({
            "gate": str(gate.get('gate', 'UNKNOWN')),
            "owner": str(gate.get('actionOwner', 'Unknown')),
            "action_time": str(gate.get('actionTime', 'N/A'))
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
        ("Pickup Location", scheduling.get('deliveryAddressTitle') or (final_payment_data.get('deliveryAddress') or {}).get('address1') or final_payment_data.get('pickupLocation')),
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
        ("Primary Registrant", registration.get('strings', {}).get('messageBody') or registration_details.get('primaryRegistrantType')),
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
        "blockers": blockers
    }

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    access_token, _ = monitor.ensure_authenticated()
    if not access_token:
        return RedirectResponse(url="/login")

    # Load existing data first to show something immediately if available
    orders = monitor.load_orders_from_file()
    
    # If no orders, try to fetch (this might be slow for a page load, ideally async background task)
    # For simplicity, we'll just show what we have or empty state
    
    formatted_orders = []
    if orders:
        for order_data in orders:
            order = order_data['order']
            details = order_data['details']
            
            # Extract key info
            scheduling = details.get('tasks', {}).get('scheduling', {})
            order_info = details.get('tasks', {}).get('registration', {}).get('orderDetails', {})
            final_payment = details.get('tasks', {}).get('finalPayment', {}).get('data', {})
            
            # Images
            image_urls = monitor.get_vehicle_image_urls(order['modelCode'], order.get('mktOptions', ''))
            
            # Tasks
            tasks = monitor.parse_tasks(details.get('tasks', {}))
            
            # VIN Decode
            vin = order.get('vin')
            vin_details = vin_decoder.decode(vin) if vin else None

            formatted_orders.append({
                'rn': order['referenceNumber'],
                'model': order['modelCode'].upper(),
                'vin': vin or 'N/A',
                'vin_details': vin_details,
                'status': order['orderStatus'],
                'delivery_date': scheduling.get('apptDateTimeAddressStr', 'Not Scheduled'),
                'delivery_window': scheduling.get('deliveryWindowDisplay', 'TBD'),
                'location': monitor.get_store_label(order_info.get('vehicleRoutingLocation', 0)),
                'eta': final_payment.get('etaToDeliveryCenter', 'Unknown'),
                'image_urls': image_urls,
                'tasks': tasks,
                'insights': build_order_insights(order_data),
                'raw_payload': order_data
            })

    context = {
        "request": request,
        "orders": formatted_orders,
        "orders_json": formatted_orders,
        "refreshed": request.query_params.get("refreshed") == "1"
    }
    return templates.TemplateResponse("index.html", context)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    auth_url = monitor.get_auth_url()
    return templates.TemplateResponse("login.html", {"request": request, "auth_url": auth_url})

@app.get("/logout")
async def logout():
    try:
        if os.path.exists('tesla_tokens.json'):
            os.remove('tesla_tokens.json')
    except Exception as e:
        logger.error(f"Error during logout: {e}")
    return RedirectResponse(url="/login", status_code=303)

@app.post("/callback")
async def callback(url: str = Form(...)):
    try:
        code = monitor.parse_redirect_url(url)
        tokens = monitor.exchange_code_for_tokens(code)
        monitor.save_tokens_to_file(tokens)
        response = RedirectResponse(url="/?refreshed=1", status_code=303)
        return response
    except Exception as e:
        logger.error(f"Login failed: {e}")
        return HTMLResponse(content=f"Login failed: {e}", status_code=400)

@app.get("/refresh")
async def refresh_data():
    access_token, _ = monitor.ensure_authenticated()
    if not access_token:
        return RedirectResponse(url="/login")
    
    try:
        old_orders = monitor.load_orders_from_file()
        new_orders_basic = monitor.retrieve_orders(access_token)
        
        detailed_new_orders = []
        for order in new_orders_basic:
            order_id = order['referenceNumber']
            details = monitor.get_order_details(order_id, access_token)
            detailed_new_orders.append({'order': order, 'details': details})
            
        monitor.save_orders_to_file(detailed_new_orders)
        
        # Calculate diffs
        diffs = []
        if old_orders:
            diffs = monitor.compare_orders(old_orders, detailed_new_orders)
            
        return RedirectResponse(url="/", status_code=303)
    except Exception as e:
        logger.error(f"Refresh failed: {e}")
        return HTMLResponse(content=f"Refresh failed: {e}", status_code=500)

@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    # In a real app, we'd store history in a DB. 
    # Here we just compare current file with... itself? 
    # The current script only compares "Last Run" vs "Current Run".
    # We can't easily show history without a DB.
    # For now, we'll just show a placeholder or maybe the last diff if we stored it.
    return templates.TemplateResponse("history.html", {"request": request, "diffs": []})
