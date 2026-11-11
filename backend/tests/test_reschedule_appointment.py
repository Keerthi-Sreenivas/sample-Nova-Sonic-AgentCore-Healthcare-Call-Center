from unittest.mock import MagicMock

import pytest

import importlib

mod = importlib.import_module("tools.reschedule_appointment")


@pytest.fixture
def db(monkeypatch):
    client = MagicMock()
    client.get_appointment.return_value = {
        "Status": "Scheduled",
        "ProviderId": "P1",
        "ProviderName": "Dr. Smith",
    }
    monkeypatch.setattr(mod, "get_db_client", lambda: client)
    return client


def call(**kw):
    return mod.reschedule_appointment(**kw)


def test_requires_exactly_one_of_date_or_slot(db):
    assert not call(appointment_id="A1")["success"]
    assert not call(appointment_id="A1", preferred_date="2030-01-01", slot_id="S1")["success"]
    db.get_appointment.assert_not_called()


def test_appointment_not_found(db):
    db.get_appointment.return_value = None
    r = call(appointment_id="A1", preferred_date="2030-01-01")
    assert not r["success"] and "not found" in r["message"]


@pytest.mark.parametrize("status", ["Cancelled", "Completed"])
def test_rejects_non_reschedulable_status(db, status):
    db.get_appointment.return_value = {"Status": status}
    r = call(appointment_id="A1", slot_id="S1")
    assert not r["success"]
    db.book_slot.assert_not_called()


def test_invalid_date_format(db):
    r = call(appointment_id="A1", preferred_date="next friday")
    assert not r["success"]
    db.query_available_slots.assert_not_called()


def test_search_returns_slots(db):
    db.query_available_slots.return_value = {
        "success": True,
        "slots": [{"SlotId": "S1", "SlotDate": "2030-01-01", "SlotTime": "09:00", "ProviderName": "Dr. Smith"}],
    }
    r = call(appointment_id="A1", preferred_date="2030-01-01")
    db.query_available_slots.assert_called_once_with(provider_id="P1", date="2030-01-01")
    assert r["success"] and r["slots"][0]["slot_id"] == "S1"


def test_search_no_slots(db):
    db.query_available_slots.return_value = {"success": True, "slots": []}
    r = call(appointment_id="A1", preferred_date="2030-01-01")
    assert r["success"] and r["slots"] == []


def test_search_error(db):
    db.query_available_slots.return_value = {"success": False, "message": "boom"}
    r = call(appointment_id="A1", preferred_date="2030-01-01")
    assert not r["success"] and r["message"] == "boom"


def test_book_success(db):
    db.book_slot.return_value = {
        "success": True,
        "appointment_details": {"date": "2030-01-01", "time": "09:00", "provider_name": "Dr. Smith"},
    }
    r = call(appointment_id="A1", slot_id="S1")
    db.book_slot.assert_called_once_with("S1", "A1")
    assert r["success"]
    assert r["new_appointment_details"]["status"] == "Rescheduled"


def test_book_failure(db):
    db.book_slot.return_value = {"success": False, "message": "Slot is no longer available"}
    r = call(appointment_id="A1", slot_id="S1")
    assert not r["success"] and "no longer" in r["message"]
