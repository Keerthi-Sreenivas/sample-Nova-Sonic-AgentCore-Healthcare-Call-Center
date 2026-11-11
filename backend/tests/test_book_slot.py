"""Unit tests for DynamoDBClient.book_slot slot release behavior."""

from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from clients.dynamodb_client import DynamoDBClient


def _error(code):
    e = ClientError({"Error": {"Code": code}}, "UpdateItem") if _real() else ClientError(code)
    if not hasattr(e, "response"):
        e.response = {"Error": {"Code": code}}
    return e


def _real():
    try:
        ClientError({"Error": {"Code": "x"}}, "Op")
        return True
    except TypeError:
        return False


def _client(old_slot_id=None, new_available=True):
    c = DynamoDBClient.__new__(DynamoDBClient)
    c.appointments_table = MagicMock()
    c.available_slots_table = MagicMock()
    appt = {"AppointmentId": "A1", "Status": "Scheduled"}
    if old_slot_id:
        appt["SlotId"] = old_slot_id
    c.appointments_table.get_item.return_value = {"Item": appt}
    c.available_slots_table.get_item.return_value = {
        "Item": {
            "SlotId": "NEW",
            "SlotDate": "2030-01-02",
            "SlotTime": "10:00",
            "ProviderName": "Dr. X",
            "Available": new_available,
        }
    }
    return c


def _slot_updates(c):
    return [call.kwargs for call in c.available_slots_table.update_item.call_args_list]


def test_first_booking_without_old_slot_stores_slot_id():
    c = _client()
    r = c.book_slot("NEW", "A1")
    assert r["success"]
    vals = c.appointments_table.update_item.call_args.kwargs["ExpressionAttributeValues"]
    assert vals[":slot_id"] == "NEW"
    assert len(_slot_updates(c)) == 1  # only the booking, nothing released


def test_reschedule_frees_old_slot():
    c = _client(old_slot_id="OLD")
    r = c.book_slot("NEW", "A1")
    assert r["success"]
    updates = _slot_updates(c)
    assert updates[0]["Key"] == {"SlotId": "NEW"}
    assert updates[1]["Key"] == {"SlotId": "OLD"}
    assert updates[1]["ExpressionAttributeValues"] == {":available": True}


def test_same_slot_not_released():
    c = _client(old_slot_id="NEW")
    assert c.book_slot("NEW", "A1")["success"]
    assert len(_slot_updates(c)) == 1


def test_new_slot_unavailable_leaves_old_untouched():
    c = _client(old_slot_id="OLD", new_available=False)
    r = c.book_slot("NEW", "A1")
    assert not r["success"]
    c.available_slots_table.update_item.assert_not_called()
    c.appointments_table.update_item.assert_not_called()


def test_appointment_update_failure_rolls_back_new_slot():
    c = _client(old_slot_id="OLD")
    c.appointments_table.update_item.side_effect = _error("InternalServerError")
    r = c.book_slot("NEW", "A1")
    assert not r["success"]
    updates = _slot_updates(c)
    assert [u["Key"]["SlotId"] for u in updates] == ["NEW", "NEW"]
    assert updates[1]["ExpressionAttributeValues"] == {":available": True}


def test_old_release_failure_still_succeeds():
    c = _client(old_slot_id="OLD")
    ok = MagicMock()
    c.available_slots_table.update_item.side_effect = [ok, _error("ConditionalCheckFailedException")]
    r = c.book_slot("NEW", "A1")
    assert r["success"]
