from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .metrics import build_metrics_from_env
from .monitor import TeslaOrderMonitor
from .utils import (
    build_items,
    derive_model_labels,
    describe_appointment_status,
    describe_delivery_type,
    describe_finance_product,
    describe_locale,
    describe_market_options,
    describe_order_status,
    describe_order_substatus,
    describe_payment_status,
    describe_registrant_type,
    describe_registration_status,
    extract_delivery_blockers,
    format_currency,
    format_date_only,
    format_timestamp,
    format_vehicle_mileage,
    shorten_delivery_window_display,
    unpack_order_data,
)
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


@dataclass(frozen=True)
class OrderProgressContext:
    """Derived values used to compute order progress stages."""

    has_order_placed: bool
    order_placed_timestamp: Optional[str]
    vin_value: Optional[str]
    vin_assigned_timestamp: Optional[str]
    production_complete: bool
    production_timestamp: Optional[str]
    odometer_display: Optional[str]
    in_transit_completed: bool
    in_transit_timestamp: Optional[str]
    in_transit_eta_label: Optional[str]
    in_transit_has_eta: bool
    registration_status_label: str
    registration_complete: bool
    registration_timestamp: Optional[str]
    reggie_license_plate: Optional[str]
    registration_activity_signal: bool
    ready_flag: bool
    ready_timestamp: Optional[str]
    ready_meta_label: Optional[str]
    ready_meta_value: Optional[str]
    ready_activity_signal: bool
    delivered_flag: bool
    delivered_timestamp: Optional[str]


StageDict = Dict[str, Any]
StatePredicate = Callable[[OrderProgressContext, StageDict], bool]
ValueFactory = Callable[[OrderProgressContext], Optional[str]]
BoolFactory = Callable[[OrderProgressContext], bool]
ExtraFactory = Callable[[OrderProgressContext], Dict[str, Any]]


@dataclass(frozen=True)
class ProgressStageDefinition:
    """Declarative description of an order progress milestone."""

    key: str
    label: str
    description: str
    completion: BoolFactory
    timestamp: ValueFactory = lambda _: None
    meta_label: ValueFactory = lambda _: None
    meta_value: ValueFactory = lambda _: None
    extra: ExtraFactory = lambda _: {}
    force_active_when: Optional[StatePredicate] = None
    force_pending_when: Optional[StatePredicate] = None


def _build_stage_entry(
    definition: ProgressStageDefinition, context: OrderProgressContext
) -> StageDict:
    """Serialize a progress stage definition into template-friendly data."""

    stage: StageDict = {
        "key": definition.key,
        "label": definition.label,
        "description": definition.description,
        "completed": definition.completion(context),
        "timestamp": definition.timestamp(context),
        "meta_label": definition.meta_label(context),
        "meta_value": definition.meta_value(context),
    }
    extra = definition.extra(context)
    if extra:
        stage.update(extra)
    return stage


PROGRESS_STAGE_DEFINITIONS: tuple[ProgressStageDefinition, ...] = (
    ProgressStageDefinition(
        key="order_placed",
        label="Order Placed",
        description="Reservation submitted and RN assigned.",
        completion=lambda ctx: ctx.has_order_placed,
        timestamp=lambda ctx: ctx.order_placed_timestamp,
    ),
    ProgressStageDefinition(
        key="vin_assigned",
        label="VIN Assigned",
        description="Tesla matched a specific vehicle to your RN.",
        completion=lambda ctx: bool(ctx.vin_value),
        timestamp=lambda ctx: ctx.vin_assigned_timestamp,
        meta_label=lambda _: "VIN",
        meta_value=lambda ctx: ctx.vin_value,
    ),
    ProgressStageDefinition(
        key="production",
        label="In Production",
        description="Factory scheduling or build in progress.",
        completion=lambda ctx: ctx.production_complete,
        timestamp=lambda ctx: ctx.production_timestamp,
        meta_label=lambda _: "Odometer",
        meta_value=lambda ctx: ctx.odometer_display or "Awaiting update",
    ),
    ProgressStageDefinition(
        key="in_transit",
        label="In Transit",
        description="Vehicle departed the factory toward your delivery hub.",
        completion=lambda ctx: ctx.in_transit_completed,
        timestamp=lambda ctx: ctx.in_transit_timestamp,
        meta_label=lambda _: "ETA",
        meta_value=lambda ctx: ctx.in_transit_eta_label,
        extra=lambda ctx: {"has_eta": ctx.in_transit_has_eta},
        force_pending_when=lambda ctx, _: not ctx.in_transit_has_eta,
    ),
    ProgressStageDefinition(
        key="registration",
        label="Registration",
        description="Paperwork with your DMV or agency to secure plates.",
        completion=lambda ctx: ctx.registration_complete,
        timestamp=lambda ctx: ctx.registration_timestamp,
        meta_label=lambda ctx: "Plate" if ctx.reggie_license_plate else "Status",
        meta_value=lambda ctx: (
            ctx.reggie_license_plate or ctx.registration_status_label
        ),
        force_active_when=lambda ctx, _: ctx.registration_activity_signal,
    ),
    ProgressStageDefinition(
        key="ready",
        label="Ready For Delivery",
        description="Delivery center appointment or pickup window confirmed.",
        completion=lambda ctx: ctx.ready_flag,
        timestamp=lambda ctx: ctx.ready_timestamp,
        meta_label=lambda ctx: (
            "Delivery Date" if ctx.ready_timestamp else ctx.ready_meta_label
        ),
        meta_value=lambda ctx: ctx.ready_timestamp or ctx.ready_meta_value,
        force_active_when=lambda ctx, stage: bool(
            ctx.ready_activity_signal or stage.get("state") == "active"
        ),
    ),
    ProgressStageDefinition(
        key="delivered",
        label="Delivered",
        description="Vehicle handed off and paperwork closed.",
        completion=lambda ctx: ctx.delivered_flag,
        timestamp=lambda ctx: ctx.delivered_timestamp,
    ),
)


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
            format_vehicle_mileage(mileage_value, mileage_unit) or "Unknown"
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
                format_date_only(eta_delivery_raw) if eta_delivery_raw else None,
            ),
            (
                "Delivery Type",
                describe_delivery_type(
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
                describe_payment_status(
                    final_payment_task.get("status")
                    if isinstance(final_payment_task, dict)
                    else None
                ),
            ),
            (
                "Customer Amount Due",
                format_currency(
                    (
                        final_payment_task.get("amountDue")
                        if isinstance(final_payment_task, dict)
                        else None
                    ),
                    currency_code,
                ),
            ),
            ("Order Placed", format_timestamp(order_info.get("orderPlacedDate"))),
            ("Order Booked", format_timestamp(order_info.get("orderBookedDate"))),
        ]
        summary_items = build_items(summary_pairs)

        model_code = (order.get("modelCode") or order.get("model") or "").upper()
        model_name, model_full_name = derive_model_labels(order, details)

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


def build_order_insights(order_entry: Dict[str, Any]) -> Dict[str, Any]:
    data = unpack_order_data(order_entry)
    order = data["order"]
    scheduling = data["scheduling"]
    registration = data["registration"]
    final_payment = data["final_payment"]
    final_payment_data = data["final_payment_data"]

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

    finance_items = build_items(
        [
            ("Payment Status", describe_payment_status(final_payment.get("status"))),
            ("Finance Partner", financing_details.get("financePartnerName")),
            (
                "Product Type",
                describe_finance_product(
                    financing_details.get("financePartnerType")
                    or final_payment.get("orderType")
                ),
            ),
            ("Interest Rate", interest_display),
            (
                "Monthly Payment",
                format_currency(financing_details.get("monthlyPayment"), currency_code),
            ),
            ("Term", term_display),
            (
                "Down Payment",
                format_currency(
                    financing_details.get("downpaymentToLessor"), currency_code
                ),
            ),
            (
                "Customer Amount Due",
                format_currency(final_payment.get("amountDue"), currency_code),
            ),
            (
                "Amount Sent",
                format_currency(final_payment.get("amountSent"), currency_code),
            ),
            (
                "Lender Amount Due",
                format_currency(
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

    delivery_items = build_items(
        [
            (
                "Delivery Type",
                describe_delivery_type(
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
                describe_appointment_status(scheduling.get("appointmentStatusName")),
            ),
            ("Tesla Actions Pending", readiness.get("hasTeslaAction")),
            ("Customer Actions Pending", readiness.get("hasCustomerAction")),
            ("Has Blocker", readiness.get("hasBlocker")),
        ]
    )

    registration_details = registration.get("orderDetails", {}) or {}
    registration_items = build_items(
        [
            (
                "Registration Status",
                describe_registration_status(
                    registration_details.get("registrationStatus")
                    or registration.get("status")
                ),
            ),
            (
                "Registrant Type",
                describe_registrant_type(
                    registration_details.get("registrantType")
                    or registration.get("registrantType")
                ),
            ),
            (
                "Order Placed",
                format_timestamp(registration_details.get("orderPlacedDate")),
            ),
            (
                "Order Booked",
                format_timestamp(registration_details.get("orderBookedDate")),
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

    metadata_items = build_items(
        [
            ("Order Status", describe_order_status(order.get("orderStatus"))),
            ("Order Substatus", describe_order_substatus(order.get("orderSubstatus"))),
            ("Vehicle Map ID", order.get("vehicleMapId")),
            ("Locale", describe_locale(order.get("locale"))),
            ("B2B Order", order.get("isB2b")),
            ("Used Vehicle", order.get("isUsed")),
        ]
    )

    metadata_items.extend(describe_market_options(order.get("mktOptions")))

    blockers = extract_delivery_blockers(readiness)

    return {
        "finance": finance_items,
        "delivery": delivery_items,
        "registration": registration_items,
        "metadata": metadata_items,
        "blockers": blockers,
    }


def build_order_progress(order_entry: Dict[str, Any]) -> Dict[str, Any]:
    data = unpack_order_data(order_entry)
    order = data["order"]
    details = data["details"]
    tasks = data["tasks"]
    scheduling = data["scheduling"]
    registration = data["registration"]
    final_payment = data["final_payment"]
    final_payment_data = data["final_payment_data"]

    registration_details = registration.get("orderDetails", {}) or {}
    delivery_details = data["delivery_details"]
    delivery_reg_data = delivery_details.get("regData", {}) or {}
    delivery_acceptance_task = tasks.get("deliveryAcceptance", {}) or {}

    order_status = str(order.get("orderStatus") or "").upper()
    today = datetime.utcnow().date()

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

    def extract_ready_appointment_timestamp() -> Optional[Any]:
        timestamp_keys = (
            "appointmentDateUtc",
            "appointmentDate",
            "apptDateTimeUtc",
            "apptDateTime",
        )

        def include_candidate(value: Any) -> Optional[Dict[str, Any]]:
            return value if isinstance(value, dict) else None

        candidates: List[Dict[str, Any]] = []
        for candidate in (
            scheduling,
            include_candidate(scheduling.get("deliveryAppointment")),
            delivery_acceptance_task,
            delivery_reg_data.get("deliveryAppointment"),
            delivery_details.get("deliveryAppointment"),
            final_payment,
            final_payment_data,
            final_payment_data.get("deliveryAppointment"),
        ):
            if not isinstance(candidate, dict):
                continue
            candidates.append(candidate)
            nested = candidate.get("deliveryAppointment")
            if isinstance(nested, dict):
                candidates.append(nested)

        for candidate in candidates:
            for key in timestamp_keys:
                value = candidate.get(key)
                if value:
                    return value
        return None

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
    odometer_display = format_vehicle_mileage(odometer_raw, odometer_unit)

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
    ready_window_fallback = scrub_text(
        scheduling.get("deliveryWindowDisplay") or scheduling.get("deliveryWindow")
    )
    ready_window_display = shorten_delivery_window_display(ready_window_fallback)
    appointment_raw = extract_ready_appointment_timestamp()
    ready_timestamp_display = format_timestamp(appointment_raw)
    if not ready_timestamp_display and ready_window_primary:
        ready_timestamp_display = ready_window_primary
    if not ready_timestamp_display and ready_window_fallback:
        ready_timestamp_display = ready_window_display or ready_window_fallback

    if ready_timestamp_display:
        ready_meta_label = "Appointment"
        ready_meta_value = ready_timestamp_display
    elif ready_window_fallback:
        ready_meta_label = "Window"
        ready_meta_value = ready_window_display or ready_window_fallback
    else:
        ready_meta_label = None
        ready_meta_value = None

    ready_timestamp = ready_timestamp_display
    ready_activity_signal = bool(ready_timestamp_display)
    delivered_flag = "DELIVERED" in order_status
    delivered_timestamp = (
        order.get("deliveryDate")
        or order.get("deliveredOn")
        or order.get("deliveredDate")
    )

    production_complete = (
        odometer_numeric is not None and abs(odometer_numeric - 30) > 1e-6
    )
    registration_status_raw = registration_details.get(
        "registrationStatus"
    ) or registration.get("status")
    registration_status_normalized = normalize_code_token(registration_status_raw)
    registration_status_label = (
        describe_registration_status(registration_status_raw)
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
    registration_progress_codes = {
        # Tesla surfaces a variety of status strings that imply work-in-progress
        # even if the step is not yet complete. Normalize several known variants
        # so we can highlight the stage when meaningful updates exist.
        "READY_TO_SUBMIT",
        "READY_FOR_SUBMISSION",
        "READY",
        "IN_PROGRESS",
        "PROCESSING",
        "PENDING",
        "STARTED",
        "AWAITING_APPROVAL",
        "AWAITING_TESLA",
        "AWAITING_CUSTOMER",
    }
    registration_complete = (
        registration_status_normalized in registration_completion_codes
    )
    registration_timestamp_raw = (
        registration_details.get("registrationCompletionDate")
        or registration_details.get("registrationStartDate")
        or registration.get("startedOn")
    )
    registration_activity_signal = bool(
        not registration_complete
        and (
            reggie_license_plate
            or (
                registration_status_normalized
                and registration_status_normalized in registration_progress_codes
            )
        )
    )

    appointment_valid = bool(parse_iso_datetime(appointment_raw))
    ready_prereqs_complete = all(
        (
            bool(order_placed_raw),
            bool(vin_value),
            production_complete,
            in_transit_completed,
            registration_complete,
        )
    )
    ready_flag = bool(appointment_valid and ready_prereqs_complete)

    order_placed_timestamp = format_timestamp(order_placed_raw)
    vin_assigned_timestamp = format_timestamp(vin_assigned_raw)
    production_timestamp_formatted = format_timestamp(production_timestamp)
    registration_timestamp_formatted = format_timestamp(registration_timestamp_raw)
    ready_timestamp_formatted = ready_timestamp
    delivered_timestamp_formatted = format_timestamp(delivered_timestamp)

    progress_context = OrderProgressContext(
        has_order_placed=bool(order_placed_raw),
        order_placed_timestamp=order_placed_timestamp,
        vin_value=vin_value,
        vin_assigned_timestamp=vin_assigned_timestamp,
        production_complete=production_complete,
        production_timestamp=production_timestamp_formatted,
        odometer_display=odometer_display or "Awaiting update",
        in_transit_completed=in_transit_completed,
        in_transit_timestamp=eta_timestamp,
        in_transit_eta_label=eta_labeled,
        in_transit_has_eta=in_transit_has_eta,
        registration_status_label=registration_status_label,
        registration_complete=registration_complete,
        registration_timestamp=registration_timestamp_formatted,
        reggie_license_plate=reggie_license_plate,
        registration_activity_signal=registration_activity_signal,
        ready_flag=ready_flag,
        ready_timestamp=ready_timestamp_formatted,
        ready_meta_label=ready_meta_label,
        ready_meta_value=ready_meta_value,
        ready_activity_signal=ready_activity_signal,
        delivered_flag=delivered_flag,
        delivered_timestamp=delivered_timestamp_formatted,
    )

    stages: List[Dict[str, Any]] = [
        _build_stage_entry(definition, progress_context)
        for definition in PROGRESS_STAGE_DEFINITIONS
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

    for definition, stage in zip(PROGRESS_STAGE_DEFINITIONS, stages):
        if stage["completed"]:
            continue
        pending_forced = False
        if definition.force_pending_when and definition.force_pending_when(
            progress_context, stage
        ):
            stage["state"] = "upcoming"
            stage["state_label"] = "Pending"
            pending_forced = True
        if (
            not pending_forced
            and definition.force_active_when
            and definition.force_active_when(progress_context, stage)
        ):
            stage["state"] = "active"
            stage["state_label"] = "In Progress"

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
