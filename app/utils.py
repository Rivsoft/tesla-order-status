import math
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    APPOINTMENT_STATUS_DESCRIPTIONS,
    DELIVERY_GATE_DESCRIPTIONS,
    DELIVERY_TIMING_DESCRIPTIONS,
    DELIVERY_TYPE_DESCRIPTIONS,
    FINANCE_PRODUCT_TYPE_DESCRIPTIONS,
    LOCALE_DESCRIPTIONS,
    MARKET_OPTION_CATALOG,
    MODEL_CODE_LABELS,
    MONTH_ABBREVIATIONS,
    OPTION_CODE_SPLITTER,
    OPTION_HINT_RULES,
    ORDER_STATUS_DESCRIPTIONS,
    ORDER_SUBSTATUS_DESCRIPTIONS,
    PAYMENT_STATUS_DESCRIPTIONS,
    REGISTRANT_TYPE_DESCRIPTIONS,
    REGISTRATION_STATUS_DESCRIPTIONS,
    WINDOW_DATE_PATTERN,
)


def format_vehicle_mileage(value: Any, unit: Optional[Any]) -> Optional[str]:
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


def format_currency(amount: Any, currency: Optional[str]) -> Optional[str]:
    if amount in (None, ""):
        return None
    try:
        numeric = float(str(amount))
        formatted = f"{numeric:,.2f}"
    except (ValueError, TypeError):
        formatted = str(amount)
    return f"{currency} {formatted}".strip() if currency else formatted


def format_timestamp(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        raw = str(value)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw).strftime("%d %b %Y %H:%M")
    except Exception:  # pragma: no cover - fallback
        return str(value)


def format_date_only(value: Any) -> Optional[str]:
    formatted = format_timestamp(value)
    if not formatted:
        return None
    tokens = formatted.split()
    if len(tokens) >= 3:
        return " ".join(tokens[:3])
    return formatted


def abbreviate_month_token(token: str) -> Optional[str]:
    cleaned = re.sub(r"[^A-Z]", "", token.upper()) if token else ""
    if not cleaned:
        return None
    if cleaned in MONTH_ABBREVIATIONS:
        return MONTH_ABBREVIATIONS[cleaned]
    prefix = cleaned[:3]
    if prefix in MONTH_ABBREVIATIONS:
        return MONTH_ABBREVIATIONS[prefix]
    return cleaned.title()[:3]


def shorten_delivery_window_display(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    matches: List[Tuple[str, int]] = []
    for match in WINDOW_DATE_PATTERN.finditer(text):
        if match.group("day_first"):
            day = match.group("day_first")
            month = match.group("month_first")
        else:
            day = match.group("day_second")
            month = match.group("month_second")
        month_abbrev = abbreviate_month_token(month)
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


def format_rich_value(value: str) -> str:
    text = value.strip()
    if text.startswith(("http://", "https://")):
        return (
            f'<a href="{text}" target="_blank" rel="noopener" '
            'class="text-zinc-100 underline decoration-zinc-500/60 underline-offset-2 hover:text-white">'
            f"{text}</a>"
        )
    return text


def build_items(pairs: List[Tuple[str, Any]]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for label, value in pairs:
        if value in (None, "", []):
            continue
        if isinstance(value, bool):
            display = "Yes" if value else "No"
        else:
            display = str(value)
        items.append({"label": label, "value": format_rich_value(display)})
    return items


def normalize_option_code(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text.startswith("$"):
        text = text[1:]
    return text or None


def split_option_codes(blob: Any) -> List[str]:
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
        normalized = normalize_option_code(candidate)
        if normalized:
            codes.append(normalized)
    return codes


def lookup_trim_label(order: Dict[str, Any], details: Dict[str, Any]) -> Optional[str]:
    order_details = details.get("orderDetails", {}) or {}
    for candidate in (
        order_details.get("trimName"),
        order_details.get("modelDescription"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    trim_code = normalize_option_code(
        order_details.get("trimCode") or order.get("trimCode")
    )
    if trim_code:
        catalog_entry = MARKET_OPTION_CATALOG.get(trim_code)
        if catalog_entry:
            return catalog_entry["name"]

    option_codes = split_option_codes(order.get("mktOptions"))
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


def describe_model_code(value: Any) -> str:
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


def derive_model_labels(
    order: Dict[str, Any], details: Dict[str, Any]
) -> Tuple[str, str]:
    model_code = (order.get("modelCode") or order.get("model") or "").upper()
    base_label = describe_model_code(model_code)
    trim_label = lookup_trim_label(order, details)
    if trim_label:
        if trim_label.lower().startswith(base_label.lower()):
            full_label = trim_label
        else:
            full_label = f"{base_label} {trim_label}".strip()
    else:
        full_label = base_label
    return base_label, full_label


def infer_option_hint(code: str) -> Tuple[str, str]:
    if not code:
        return "Option", "Unrecognized option"
    for pattern, (label, description) in OPTION_HINT_RULES:
        if pattern.match(code):
            return label, description
    return "Option", "Custom configuration"


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
        label, description = infer_option_hint(code)
        items.append({"label": label, "value": f"{description} ({code})"})

    return items


def describe_code(value: Any, mapping: Dict[str, str]) -> Optional[str]:
    if not value:
        return value
    key = str(value).upper()
    if key in mapping:
        return mapping[key]
    return key.replace("_", " ").title()


def describe_delivery_type(value: Any) -> Optional[str]:
    return describe_code(value, DELIVERY_TYPE_DESCRIPTIONS)


def describe_payment_status(value: Any) -> Optional[str]:
    return describe_code(value, PAYMENT_STATUS_DESCRIPTIONS)


def describe_appointment_status(value: Any) -> Optional[str]:
    return describe_code(value, APPOINTMENT_STATUS_DESCRIPTIONS)


def describe_registration_status(value: Any) -> Optional[str]:
    return describe_code(value, REGISTRATION_STATUS_DESCRIPTIONS)


def describe_registrant_type(value: Any) -> Optional[str]:
    return describe_code(value, REGISTRANT_TYPE_DESCRIPTIONS)


def describe_locale(value: Any) -> Optional[str]:
    return describe_code(value, LOCALE_DESCRIPTIONS)


def describe_order_status(value: Any) -> Optional[str]:
    return describe_code(value, ORDER_STATUS_DESCRIPTIONS)


def describe_order_substatus(value: Any) -> Optional[str]:
    return describe_code(value, ORDER_SUBSTATUS_DESCRIPTIONS)


def describe_finance_product(value: Any) -> Optional[str]:
    return describe_code(value, FINANCE_PRODUCT_TYPE_DESCRIPTIONS)


def describe_delivery_gate(value: Any) -> Optional[str]:
    return describe_code(value, DELIVERY_GATE_DESCRIPTIONS)


def describe_delivery_timing(value: Any) -> Optional[str]:
    return describe_code(value, DELIVERY_TIMING_DESCRIPTIONS)


def format_blocker_time(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    key = str(value).upper()
    if key in DELIVERY_TIMING_DESCRIPTIONS:
        return DELIVERY_TIMING_DESCRIPTIONS[key]
    timestamp = format_timestamp(value)
    if timestamp and timestamp != str(value):
        return timestamp
    described = describe_delivery_timing(value)
    return described or str(value)


def extract_delivery_blockers(readiness: Dict[str, Any]) -> List[Dict[str, str]]:
    gates = readiness.get("gates") or []
    gate_iterable = gates.values() if isinstance(gates, dict) else gates

    blockers: List[Dict[str, str]] = []
    for gate in gate_iterable:
        if not isinstance(gate, dict) or not gate.get("isBlocker"):
            continue
        gate_label = describe_delivery_gate(gate.get("gate", "UNKNOWN")) or "Unknown"
        owner_label = describe_code(gate.get("actionOwner", "Unknown"), {}) or "Unknown"
        blockers.append(
            {
                "gate": gate_label,
                "owner": owner_label,
                "action_time": format_blocker_time(gate.get("actionTime")),
            }
        )
    return blockers


def unpack_order_data(order_entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract common fields from the order entry structure.
    Returns a dictionary with keys:
      - order
      - details
      - tasks
      - scheduling
      - registration
      - final_payment
      - final_payment_data
      - delivery_details
    """
    order = order_entry.get("order", {}) or {}
    details = order_entry.get("details", {}) or {}
    tasks = details.get("tasks", {}) or {}

    final_payment = tasks.get("finalPayment", {}) or {}
    final_payment_data = (
        final_payment.get("data", {}) if isinstance(final_payment, dict) else {}
    )

    return {
        "order": order,
        "details": details,
        "tasks": tasks,
        "scheduling": tasks.get("scheduling", {}) or {},
        "registration": tasks.get("registration", {}) or {},
        "final_payment": final_payment,
        "final_payment_data": final_payment_data,
        "delivery_details": tasks.get("deliveryDetails", {}) or {},
    }
