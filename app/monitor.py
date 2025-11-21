import base64
import hashlib
import json
import logging
import os
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from .tesla_stores import TeslaStore

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Define constants
CLIENT_ID = "ownerapi"
REDIRECT_URI = "https://auth.tesla.com/void/callback"
AUTH_URL = "https://auth.tesla.com/oauth2/v3/authorize"
TOKEN_URL = "https://auth.tesla.com/oauth2/v3/token"
SCOPE = "openid email offline_access"
CODE_CHALLENGE_METHOD = "S256"
APP_VERSION = "9.99.9-9999"


class TeslaOrderMonitor:
    def __init__(self):
        pass

    def generate_login_params(self) -> Dict[str, str]:
        state = os.urandom(16).hex()
        code_verifier = (
            base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("utf-8")
        )
        code_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("utf-8")).digest()
            )
            .rstrip(b"=")
            .decode("utf-8")
        )

        auth_params = {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": CODE_CHALLENGE_METHOD,
        }
        auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

        return {"state": state, "code_verifier": code_verifier, "auth_url": auth_url}

    def parse_redirect_url(self, redirected_url: str) -> str:
        parsed_url = urllib.parse.urlparse(redirected_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        if "code" not in query_params:
            raise ValueError("Authorization code not found in the redirected URL.")
        return query_params["code"][0]

    def exchange_code_for_tokens(
        self, auth_code: str, code_verifier: str
    ) -> Dict[str, Any]:
        token_data = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        }
        response = requests.post(TOKEN_URL, data=token_data)
        response.raise_for_status()
        return response.json()

    def is_token_valid(self, access_token: str) -> bool:
        try:
            jwt_decoded = json.loads(
                base64.b64decode(access_token.split(".")[1] + "==").decode("utf-8")
            )
            return jwt_decoded["exp"] > time.time()
        except Exception:
            return False

    def refresh_tokens(self, refresh_token: str) -> Dict[str, Any]:
        token_data = {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        }
        response = requests.post(TOKEN_URL, data=token_data)
        response.raise_for_status()
        return response.json()

    def retrieve_orders(self, access_token: str) -> List[Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {access_token}"}
        api_url = "https://owner-api.teslamotors.com/api/1/users/orders"
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        return response.json()["response"]

    def get_order_details(self, order_id: str, access_token: str) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}"}
        api_url = "https://akamai-apigateway-vfx.tesla.com/tasks"
        query_params = {
            "deviceLanguage": "en",
            "deviceCountry": "DE",
            "referenceNumber": order_id,
            "appVersion": APP_VERSION,
        }
        response = requests.get(api_url, headers=headers, params=query_params)
        response.raise_for_status()
        return response.json()

    def compare_dicts(
        self, old_dict: Dict[str, Any], new_dict: Dict[str, Any], path: str = ""
    ) -> List[str]:
        differences = []
        for key in old_dict:
            if key not in new_dict:
                differences.append(f"- Removed key '{path + key}'")
            elif isinstance(old_dict[key], dict) and isinstance(new_dict[key], dict):
                differences.extend(
                    self.compare_dicts(old_dict[key], new_dict[key], path + key + ".")
                )
            elif old_dict[key] != new_dict[key]:
                differences.append(
                    f"CHANGE: {path + key}: {old_dict[key]} -> {new_dict[key]}"
                )

        for key in new_dict:
            if key not in old_dict:
                differences.append(f"+ Added key '{path + key}': {new_dict[key]}")

        return differences

    def compare_orders(
        self, old_orders: List[Dict[str, Any]], new_orders: List[Dict[str, Any]]
    ) -> List[str]:
        differences = []
        for i, old_order in enumerate(old_orders):
            if i < len(new_orders):
                differences.extend(
                    self.compare_dicts(old_order, new_orders[i], path=f"Order {i}.")
                )
            else:
                differences.append(f"- Removed order {i}")
        for i in range(len(old_orders), len(new_orders)):
            differences.append(f"+ Added order {i}")
        return differences

    def ensure_authenticated(
        self, token_bundle: Optional[Dict[str, Any]]
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Validate or refresh a token bundle.

        Returns the active access token plus an updated token bundle
        (which the caller should persist in its own storage)."""
        if not token_bundle:
            return None, None

        access_token = token_bundle.get("access_token")
        refresh_token = token_bundle.get("refresh_token")

        if not access_token or not refresh_token:
            return None, None

        if not self.is_token_valid(access_token):
            try:
                logger.info("Refreshing token...")
                token_response = self.refresh_tokens(refresh_token)
                access_token = token_response["access_token"]
                # Merge to keep any additional fields Tesla returns
                token_bundle.update(token_response)
            except Exception as e:
                logger.error(f"Failed to refresh token: {e}")
                return None, None

        return access_token, token_bundle

    def get_store_label(self, routing_loc: Any) -> str:
        try:
            store_id = int(routing_loc)
        except (TypeError, ValueError):
            return "Unknown Store"
        return TeslaStore.from_value(store_id).label

    def get_vehicle_image_urls(
        self, model_code: str, options: str, views: Optional[List[str]] = None
    ) -> List[str]:
        """Return a list of Tesla configurator image URLs covering multiple angles."""
        base_url = "https://static-assets.tesla.com/configurator/compositor"
        option_string = options or ""
        view_sequence = views or ["STUD_3QTR", "STUD_SIDE", "STUD_REAR"]

        image_urls = []
        for view in view_sequence:
            params = {
                "model": model_code,
                "view": view,
                "size": "1200",
                "options": option_string,
                "bkba_opt": "1",
                "crop": "0,0,0,0",
            }
            image_urls.append(f"{base_url}?{urllib.parse.urlencode(params)}")
        return image_urls

    def get_vehicle_image_url(self, model_code: str, options: str) -> str:
        """Backward compatible helper that returns the primary (front three-quarter) image."""
        images = self.get_vehicle_image_urls(model_code, options)
        return images[0] if images else ""

    def parse_tasks(self, tasks_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parses the tasks dictionary into a sorted list of steps."""
        # Define a logical order for tasks if possible, otherwise just list them
        # We can try to map keys to display names if 'strings.name' is missing,
        # but usually 'strings.name' is the best source.

        parsed_tasks = []

        # specific order we want to show
        priority_keys = [
            "deliveryDetails",
            "tradeIn",
            "financing",
            "registration",
            "insurance",
            "scheduling",
            "finalPayment",
            "deliveryAcceptance",
        ]

        # First add priority tasks
        for key in priority_keys:
            if key in tasks_data:
                task = tasks_data[key]
                parsed_tasks.append(self._format_task(task, key))

        # Add any others not in priority list
        for key, task in tasks_data.items():
            if (
                key not in priority_keys
                and isinstance(task, dict)
                and "complete" in task
            ):
                parsed_tasks.append(self._format_task(task, key))

        return parsed_tasks

    def _humanize_status(self, value: Any) -> str:
        if not value:
            return "Pending"
        text = str(value)
        if text.isupper():
            text = text.replace("_", " ").title()
        return text

    def _format_task(
        self, task: Dict[str, Any], task_key: Optional[str] = None
    ) -> Dict[str, Any]:
        raw_strings = task.get("strings")
        strings: Dict[str, Any] = raw_strings if isinstance(raw_strings, dict) else {}
        raw_card = task.get("card")
        card: Dict[str, Any] = raw_card if isinstance(raw_card, dict) else {}
        name = strings.get("name") or card.get("title") or task.get("id", "Task")
        if name:
            name = str(name)
        else:
            name = "Task"
        if name == "Task":
            name = task.get("id", "Unknown").replace("Task", "")

        status_raw = task.get("status") or card.get("title") or ""
        status_label = self._humanize_status(status_raw)
        status_token = str(status_raw).upper()

        detail_candidates = [
            card.get("subtitle"),
            card.get("messageBody"),
            card.get("messageTitle"),
            strings.get("subtitle"),
            strings.get("messageBody"),
            strings.get("messageTitle"),
            (
                strings.get("checkBackLater")
                if isinstance(strings.get("checkBackLater"), str)
                else None
            ),
        ]
        detail_text = next(
            (str(text).strip() for text in detail_candidates if text), None
        )

        waiting_titles = {
            "check back later",
            "we'll notify you",
            "we will notify you",
            "wait",
            "waiting",
        }
        waiting_statuses = {
            "CHECK_BACK_LATER",
            "WAIT",
            "WAITING",
            "PENDING",
            "NOT_AVAILABLE",
            "IN_REVIEW",
        }
        card_title = (card.get("title") or "").strip().lower()
        enabled = task.get("enabled", True)
        complete = task.get("complete", False)

        waiting = (
            (not enabled and not complete)
            or (status_token in waiting_statuses)
            or (card_title in waiting_titles)
        )
        actionable = (not complete) and (not waiting)

        wait_reason = None
        if waiting and not complete:
            wait_reason = detail_text or "Tesla is still preparing this step."

        cta_url = None
        target_candidate = card.get("target")
        card_target = target_candidate if isinstance(target_candidate, str) else None
        if task_key == "scheduling":
            cta_url = task.get("selfSchedulingUrl")
        elif task_key == "finalPayment":
            if card_target and card_target.startswith("http"):
                cta_url = card_target
        elif card_target and card_target.startswith("http"):
            cta_url = card_target

        cta_label = (
            strings.get("ctaLabel")
            or strings.get("actionButtonLabel")
            or card.get("ctaLabel")
            or card.get("buttonText")
            or card.get("ctaText")
            or "Open task"
        )

        metadata = self._compile_task_metadata(
            task,
            task_key=task_key,
            status_token=status_token,
            status_label=status_label,
            enabled=enabled,
            actionable=actionable,
            complete=complete,
        )

        return {
            "name": name,
            "complete": complete,
            "status": status_label,
            "details": detail_text,
            "actionable": actionable,
            "waiting_reason": wait_reason,
            "cta_url": cta_url,
            "cta_label": cta_label,
            "metadata": metadata,
        }

    def _compile_task_metadata(
        self,
        task: Dict[str, Any],
        *,
        task_key: Optional[str],
        status_token: str,
        status_label: str,
        enabled: bool,
        actionable: bool,
        complete: bool,
    ) -> List[Dict[str, str]]:
        metadata: List[Dict[str, str]] = []

        def add(label: str, value: Any) -> None:
            if value in (None, "", []):
                return
            metadata.append({"label": label, "value": str(value)})

        add("Tesla status", status_label)
        add("Status code", status_token)
        add("Enabled", "Yes" if enabled else "No")
        add("Actionable", "Yes" if actionable else "No")
        add("Complete", "Yes" if complete else "No")

        raw_data = task.get("data")
        data_section = raw_data if isinstance(raw_data, dict) else {}

        timestamp_fields = [
            ("availableAt", "Available since"),
            ("dueDate", "Due date"),
            ("statusDate", "Status updated"),
            ("completedDate", "Completed at"),
            ("statusTimestamp", "Status timestamp"),
        ]

        for field, label in timestamp_fields:
            value = task.get(field) or data_section.get(field)
            if value:
                add(label, self._format_task_timestamp(value))

        return metadata

    def _format_task_timestamp(self, value: Any) -> str:
        try:
            raw = str(value)
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            return datetime.fromisoformat(raw).strftime("%d %b %Y %H:%M")
        except Exception:
            return str(value)
