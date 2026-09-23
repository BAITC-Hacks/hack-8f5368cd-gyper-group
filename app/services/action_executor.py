from __future__ import annotations

from datetime import date
from typing import Any


class ActionExecutor:
    """Executes only facts and formulas defined in the supplied Saqta JSON data."""

    def __init__(self, assets: dict[str, Any]) -> None:
        self.backend = assets["mock_backend"]
        self.knowledge = assets["knowledge_base"]
        self.action_specs = {action["name"]: action for action in assets["actions"].get("actions", [])}
        self.as_of = date.fromisoformat(self.backend["meta"]["as_of_date"])

    def execute_many(
        self, action_names: list[str], slots: dict[str, Any], confirmed: bool = False
    ) -> list[dict[str, Any]]:
        results = []
        for name in action_names:
            spec = self.action_specs.get(name, {})
            if spec.get("irreversible") and not confirmed:
                results.append({"name": name, "status": "awaiting_confirmation"})
                continue
            try:
                results.append({"name": name, "status": "ok", "result": self._execute(name, slots)})
            except ValueError as error:
                results.append({"name": name, "status": "needs_slots", "missing": str(error).split(", ")})
            except LookupError as error:
                results.append({"name": name, "status": "error", "error": str(error)})
        return results

    def _execute(self, name: str, slots: dict[str, Any]) -> dict[str, Any]:
        if name == "find_client":
            client = self._client(slots)
            return {"client_id": client["client_id"], "full_name": client["full_name"]}
        if name == "get_policies":
            client_id = self._require(slots, "client_id")
            return {"policies": [policy for policy in self.backend["policies"] if policy["client_id"] == client_id]}
        if name == "get_policy":
            return self._policy(slots)
        if name == "get_bm_class":
            drivers = slots.get("drivers_iin") or [self._require(slots, "iin")]
            if isinstance(drivers, str):
                drivers = [drivers]
            return {"bm_class": {iin: self._bm_class(iin) for iin in drivers}}
        if name == "calc_ogpo_price":
            return {"price": self._ogpo_price(slots)}
        if name == "calc_casco_price":
            return {"price": self._casco_price(slots)}
        if name == "calc_property_price":
            product = self.knowledge["products"]["property"]
            value = str(self._require(slots, "sum_insured"))
            price = product["price_per_year_kzt"].get(value)
            if price is None:
                raise LookupError("not_eligible: сумма не поддерживается тарифом")
            if slots.get("property_type") == "house":
                price *= product["house_coef"]
            return {"price": int(price)}
        if name == "calc_accident_price":
            price = self.knowledge["products"]["accident"]["price_per_year_kzt"].get(str(self._require(slots, "sum_insured")))
            if price is None:
                raise LookupError("not_eligible: сумма не поддерживается тарифом")
            return {"price": price}
        if name == "get_claim":
            claim = self._claim(slots)
            return {key: claim[key] for key in ("claim_number", "status", "next_step")}
        if name == "list_clinics":
            city = self._require(slots, "city")
            clinics = [clinic for clinic in self.knowledge["clinics"] if clinic["city"].lower() == city.lower()]
            if not clinics:
                raise LookupError("not_found: клиники в этом городе не найдены")
            return {"clinics": clinics}
        if name == "get_offices":
            city = self._require(slots, "city")
            offices = [office for office in self.knowledge["offices"] if office["city"].lower() == city.lower()]
            if not offices:
                raise LookupError("not_found: офис в этом городе не найден")
            return {"offices": offices}
        if name == "check_payment":
            client_id = self._require(slots, "client_id")
            payment_date = self._require(slots, "payment_date")
            payment = next((item for item in self.backend["payments"] if item["client_id"] == client_id and item["date"] == payment_date), None)
            if not payment:
                raise LookupError("not_found: платёж не найден")
            return {"payment_status": payment["status"], "amount": payment["amount"], "note": payment.get("note")}
        if name == "check_coverage":
            policy = self._policy(slots)
            package = policy.get("details", {}).get("package")
            service = self._require(slots, "service_name")
            covered = service in self.knowledge["products"]["dms"]["packages"].get(package, {}).get("covered", [])
            return {"covered": covered, "note": "Покрытие определено по условиям ДМС из базы знаний."}
        if name in {"resend_documents", "request_document"}:
            policy = self._policy(slots)
            client = next(item for item in self.backend["clients"] if item["client_id"] == policy["client_id"])
            return {"sent_to": slots.get("email", client["email"])}
        if name in {"create_callback", "send_sms", "transfer_to_operator"}:
            return {"accepted": True}
        if name in {"create_complaint", "report_fraud"}:
            return {"ticket_id": f"T-{len(self.backend.get('claims', [])) + 1001}"}
        raise LookupError(f"not_supported: действие {name} пока не поддерживается мок-исполнителем")

    def _ogpo_price(self, slots: dict[str, Any]) -> int:
        region = self._require(slots, "region")
        vehicle_type = self._require(slots, "vehicle_type")
        drivers = slots.get("drivers_iin") or [self._require(slots, "iin")]
        if isinstance(drivers, str):
            drivers = [drivers]
        pricing = self.knowledge["products"]["ogpo"]["pricing"]
        coefficients = [pricing["bm_coef"][self._bm_class(iin)] for iin in drivers]
        return round(pricing["base_by_region_kzt"][region] * pricing["vehicle_type_coef"][vehicle_type] * max(coefficients))

    def _casco_price(self, slots: dict[str, Any]) -> int:
        value = int(self._require(slots, "car_value"))
        year = int(self._require(slots, "car_year"))
        franchise = str(self._require(slots, "franchise"))
        pricing = self.knowledge["products"]["casco"]["pricing"]
        age = self.as_of.year - year
        band = "0-3" if age <= 3 else "4-7" if age <= 7 else "8-10"
        if age > 10:
            raise LookupError("not_eligible: автомобиль старше 10 лет для Standard CASCO")
        return round(value * pricing["rate_by_car_age"][band] * pricing["franchise_coef"][franchise])

    def _client(self, slots: dict[str, Any]) -> dict[str, Any]:
        phone = slots.get("phone")
        iin = slots.get("iin")
        if not phone and not iin:
            raise ValueError("phone или iin")
        client = next((item for item in self.backend["clients"] if item["phone"] == phone or item["iin"] == iin), None)
        if not client:
            raise LookupError("not_found: клиент не найден")
        return client

    def _policy(self, slots: dict[str, Any]) -> dict[str, Any]:
        number = slots.get("policy_number")
        plate = slots.get("vehicle_plate")
        if not number and not plate:
            raise ValueError("policy_number или vehicle_plate")
        policy = next((item for item in self.backend["policies"] if item["policy_number"] == number or item.get("details", {}).get("vehicle_plate") == plate), None)
        if not policy:
            raise LookupError("not_found: полис не найден")
        return {**policy, "status": "active" if policy["end_date"] >= self.as_of.isoformat() else "expired"}

    def _claim(self, slots: dict[str, Any]) -> dict[str, Any]:
        number = slots.get("claim_number")
        client_id = slots.get("client_id")
        if not number and not client_id:
            raise ValueError("claim_number или client_id")
        claim = next((item for item in self.backend["claims"] if item["claim_number"] == number or item["client_id"] == client_id), None)
        if not claim:
            raise LookupError("not_found: страховой случай не найден")
        return claim

    def _bm_class(self, iin: str) -> str:
        client = next((item for item in self.backend["clients"] if item["iin"] == iin), None)
        return client["bm_class"] if client else self.backend["defaults"]["unknown_iin_bm_class"]

    @staticmethod
    def _require(slots: dict[str, Any], name: str) -> Any:
        value = slots.get(name)
        if value in (None, "", []):
            raise ValueError(name)
        return value