from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import User, app, calculate_days_until_birthday, get_db, init_db


@pytest.mark.parametrize(
    "dob, current_date, expected_days",
    [
        (date(1990, 5, 20), date(2026, 5, 20), 0),
        (date(1990, 5, 20), date(2026, 5, 19), 1),
        (date(1990, 8, 28), date(2026, 5, 20), 100),
        (date(1990, 1, 1), date(2026, 5, 20), 226),
        (date(2000, 2, 29), date(2026, 2, 28), 1),
        (date(2000, 2, 29), date(2028, 2, 28), 1),
        (date(2000, 2, 29), date(2025, 3, 10), 356),
    ],
)
def test_calculate_days_until_birthday(dob: date, current_date: date, expected_days: int):
    assert calculate_days_until_birthday(dob, current_date) == expected_days


def test_put_valid_user(client, mock_db):
    with patch("app.main.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 20)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        response = client.put("/hello/Alice", json={"dateOfBirth": "1995-10-15"})
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()


def test_put_payload_alias_handling(client, mock_db):
    with patch("app.main.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 20)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        response = client.put("/hello/Bob", json={"dateOfBrith": "1995-10-15"})
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_db.execute.assert_called_once()


@pytest.mark.parametrize(
    "invalid_username",
    ["alice123", "alice_smith", "alice-smith", "alice smith", "alice!", "1234", "Müller"],
)
def test_put_invalid_username_rejected(client, invalid_username: str):
    response = client.put(f"/hello/{invalid_username}", json={"dateOfBirth": "1990-05-15"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Username must contain letters only" in response.json()["detail"]


@pytest.mark.parametrize(
    "invalid_date_payload, expected_error_fragment",
    [
        ({"dateOfBirth": "2026-05-21"}, "must be a date before today"),
        ({"dateOfBirth": "2026-05-20"}, "must be a date before today"),
        ({"dateOfBirth": "invalid-format"}, "Input should be a valid date"),
        ({"dateOfBirth": "15-05-1990"}, "Input should be a valid date"),
        ({}, "Field required"),
    ],
)
def test_put_invalid_date_payloads(client, invalid_date_payload: dict, expected_error_fragment: str):
    with patch("app.main.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 20)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        response = client.put("/hello/Alice", json=invalid_date_payload)
        assert response.status_code == 422
        assert expected_error_fragment in str(response.json())


@pytest.mark.parametrize(
    "invalid_username",
    ["alice123", "alice_smith", "alice-smith", "alice smith", "alice!", "1234", "Müller"],
)
def test_get_invalid_username_rejected(client, invalid_username: str):
    response = client.get(f"/hello/{invalid_username}")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Username must contain letters only" in response.json()["detail"]


def test_get_user_not_found(client, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    response = client.get("/hello/NonExistentUser")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in response.json()["detail"]


def test_get_birthday_today(client, mock_db):
    mock_user = User(username="Alice", date_of_birth=date(1990, 5, 20))
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.main.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 20)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        response = client.get("/hello/Alice")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"message": "Hello, Alice! Happy birthday!"}


def test_get_birthday_in_one_day_singular(client, mock_db):
    mock_user = User(username="Bob", date_of_birth=date(1992, 5, 21))
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.main.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 20)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        response = client.get("/hello/Bob")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"message": "Hello, Bob! Your birthday is in 1 day"}


def test_get_birthday_in_multiple_days_plural(client, mock_db):
    mock_user = User(username="Charlie", date_of_birth=date(1992, 5, 25))
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.main.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 20)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

        response = client.get("/hello/Charlie")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"message": "Hello, Charlie! Your birthday is in 5 days"}


def test_healthz_endpoint(client):
    response = client.get("/healthz")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


def test_get_db_session_lifecycle():
    with patch("app.main.SessionLocal") as mock_session_local:
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        db_generator = get_db()
        yielded_db = next(db_generator)

        assert yielded_db == mock_session

        with pytest.raises(StopIteration):
            next(db_generator)

        mock_session.close.assert_called_once()


def test_lifespan_init_db_retry_success():
    with patch("app.main.Base.metadata.create_all", side_effect=[Exception("DB not ready"), None]), \
         patch("app.main.time.sleep") as mock_sleep:
        with TestClient(app) as test_client:
            response = test_client.get("/healthz")
            assert response.status_code == status.HTTP_200_OK
            mock_sleep.assert_called_once_with(2.0)


def test_init_db_retry_exhausted():
    with patch("app.main.Base.metadata.create_all", side_effect=Exception("DB connection failed")), \
         patch("app.main.time.sleep") as mock_sleep:
        with pytest.raises(Exception, match="DB connection failed"):
            init_db(max_retries=3, delay_seconds=0.1)
        assert mock_sleep.call_count == 2
