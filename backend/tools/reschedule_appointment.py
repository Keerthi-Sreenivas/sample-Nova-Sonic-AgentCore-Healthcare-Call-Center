"""Reschedule Appointment Tool.

Single entry point for rescheduling. Works in two steps:
1. Called with ``preferred_date`` -> returns available slots for that day.
2. Called with ``slot_id`` -> books the selected slot.
"""

import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

from strands import tool

from clients.dynamodb_client import DynamoDBClient

logger = logging.getLogger(__name__)

# Singleton client instance
_db_client: Optional[DynamoDBClient] = None

# Statuses from which an appointment may be rescheduled
RESCHEDULABLE_STATUSES = ["Scheduled", "Confirmed", "Rescheduled"]


def get_db_client() -> DynamoDBClient:
    """Get or create DynamoDB client singleton."""
    global _db_client
    if _db_client is None:
        _db_client = DynamoDBClient()
    return _db_client


@dataclass
class RescheduleResult:
    """Result of a reschedule step."""

    success: bool
    message: str
    slots: Optional[list] = None
    new_appointment_details: Optional[dict] = None


@tool
def reschedule_appointment(
    appointment_id: str,
    preferred_date: Optional[str] = None,
    slot_id: Optional[str] = None,
) -> dict:
    """Reschedule a patient's existing appointment to a new date and time.

    This is a two-step tool:
    - Step 1: call with appointment_id and preferred_date to get available slots
      with the same provider. Present the options and let the patient choose.
    - Step 2: once the patient picks a time, call again with appointment_id and
      the chosen slot_id to book it.

    Provide exactly one of preferred_date or slot_id.

    Args:
        appointment_id: ID of the appointment to reschedule
        preferred_date: Date in YYYY-MM-DD format (step 1). Convert the patient's
            natural language date (e.g., "next Friday") yourself.
            NEVER ask the patient for a specific date format on a voice call.
        slot_id: ID of the slot the patient selected (step 2)

    Returns:
        Dictionary with available slots (step 1) or new appointment details (step 2)
    """
    if bool(preferred_date) == bool(slot_id):
        return asdict(
            RescheduleResult(
                success=False,
                message="Provide either a preferred date to search for slots, or a slot ID to book.",
            )
        )

    db = get_db_client()
    appointment = db.get_appointment(appointment_id)

    if not appointment:
        logger.warning("Appointment not found for reschedule")
        return asdict(
            RescheduleResult(
                success=False,
                message="Appointment not found. Please verify the appointment ID.",
            )
        )

    status = appointment.get("Status")
    if status not in RESCHEDULABLE_STATUSES:
        return asdict(
            RescheduleResult(
                success=False,
                message=f"Cannot reschedule an appointment with status '{status}'.",
            )
        )

    # Step 2: book the selected slot
    if slot_id:
        booking = db.book_slot(slot_id, appointment_id)
        if not booking.get("success"):
            return asdict(
                RescheduleResult(
                    success=False,
                    message=booking.get(
                        "message", "Failed to book the selected slot. Please try again."
                    ),
                )
            )

        details = booking.get("appointment_details", {})
        new_details = {
            "date": details.get("date"),
            "time": details.get("time"),
            "provider": details.get("provider_name"),
            "status": "Rescheduled",
        }
        logger.info("Appointment rescheduled successfully")
        return asdict(
            RescheduleResult(
                success=True,
                message=f"Your appointment has been rescheduled to {new_details['date']} at {new_details['time']} with {new_details['provider']}.",
                new_appointment_details=new_details,
            )
        )

    # Step 1: search slots
    try:
        datetime.strptime(preferred_date, "%Y-%m-%d")
    except ValueError:
        return asdict(
            RescheduleResult(
                success=False,
                message="The date could not be understood. Please ask the patient for the date again.",
            )
        )

    provider_name = appointment.get("ProviderName")
    result = db.query_available_slots(
        provider_id=appointment.get("ProviderId"), date=preferred_date
    )

    if not result.get("success"):
        return asdict(
            RescheduleResult(
                success=False,
                message=result.get("message", "Error searching for available slots."),
            )
        )

    slots = [
        {
            "slot_id": s.get("SlotId"),
            "date": s.get("SlotDate"),
            "time": s.get("SlotTime"),
            "provider_name": s.get("ProviderName", provider_name),
        }
        for s in result.get("slots", [])
    ]

    if not slots:
        return asdict(
            RescheduleResult(
                success=True,
                message=f"No available slots found with {provider_name} on {preferred_date}. Would you like to try a different date?",
                slots=[],
            )
        )

    times = ", ".join(f"{s['time']} on {s['date']}" for s in slots)
    return asdict(
        RescheduleResult(
            success=True,
            message=f"I found {len(slots)} available slots with {provider_name}: {times}. Which time works best for you?",
            slots=slots,
        )
    )
