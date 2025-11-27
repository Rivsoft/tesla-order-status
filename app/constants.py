import re
from typing import Dict, List, Tuple

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

OPTION_HINT_RULES: List[Tuple[re.Pattern[str], Tuple[str, str]]] = [
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
