"""Unit tests for birth date collection functionality."""

# pyright: reportPrivateUsage=false

import re
from http import HTTPStatus
from typing import Any

import pytest
from aws_lambda_powertools.event_handler import (
    LambdaFunctionUrlResolver,
    Response,
)
from aws_lambda_powertools.event_handler.exceptions import (
    BadRequestError,
    InternalServerError,
    UnauthorizedError,
)
from aws_lambda_powertools.utilities.data_classes import LambdaFunctionUrlEvent
from defusedxml import ElementTree
from pytest_mock import MockerFixture

from twiliowebhook.api.constants import HANGUP_TWIML_FILE_PATH
from twiliowebhook.api.main import (
    confirm_digits,
    handle_incoming_call,
    process_digits,
)


def test_handle_incoming_call_birthdate(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event", new=LambdaFunctionUrlEvent({})
    )
    caller_phone_number = "+1234567890"
    mocker.patch(
        "twiliowebhook.api.main._fetch_caller_phone_number_from_request",
        return_value=caller_phone_number,
    )
    twilio_auth_token = "test-token"
    media_api_url = "wss://api.example.com"
    webhook_api_url = "https://api.example.com"
    mock_get_parameters_by_name = mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": twilio_auth_token,
            "/twh/dev/media-api-url": media_api_url,
            "/twh/dev/webhook-api-url": webhook_api_url,
        },
    )
    mock_validate_http_twilio_signature = mocker.patch(
        "twiliowebhook.api.main.validate_http_twilio_signature",
        return_value=None,
    )
    response: Response[str] = handle_incoming_call(twiml_file_stem="birthdate")
    mock_get_parameters_by_name.assert_called_once_with(
        parameters={
            "/twh/dev/twilio-auth-token": {},
            "/twh/dev/media-api-url": {},
            "/twh/dev/webhook-api-url": {},
        },
        decrypt=True,
        raise_on_error=True,
    )
    mock_validate_http_twilio_signature.assert_called_once_with(
        token=twilio_auth_token,
        event=mocker.ANY,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == "application/xml"
    assert response.body is not None
    assert "process-digits/birthdate" in response.body
    assert "Enter the year, month, and day" in response.body


@pytest.mark.parametrize(
    ("digits", "expected_year", "expected_month", "expected_day"),
    [
        ("19900115", "1990", "01", "15"),
        ("20001231", "2000", "12", "31"),
        ("19850705", "1985", "07", "05"),
    ],
)
def test_process_digits_valid(
    digits: str,
    expected_year: str,
    expected_month: str,
    expected_day: str,
    mocker: MockerFixture,
) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = LambdaFunctionUrlEvent({
        "queryStringParameters": {"digits": digits},
        "headers": {"X-Twilio-Signature": "test-signature"},
    })
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)
    twilio_auth_token = "test-token"
    webhook_api_url = "https://api.example.com"
    mock_get_parameters_by_name = mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": twilio_auth_token,
            "/twh/dev/webhook-api-url": webhook_api_url,
        },
    )
    mock_validate_http_twilio_signature = mocker.patch(
        "twiliowebhook.api.main.validate_http_twilio_signature"
    )
    mock_logger_info = mocker.patch("twiliowebhook.api.main.logger.info")

    response = process_digits("birthdate")

    mock_get_parameters_by_name.assert_called_once_with(
        parameters={
            "/twh/dev/twilio-auth-token": {},
            "/twh/dev/webhook-api-url": {},
        },
        decrypt=True,
        raise_on_error=True,
    )
    mock_validate_http_twilio_signature.assert_called_once_with(
        token=twilio_auth_token,
        event=mock_event,
    )
    mock_logger_info.assert_any_call(
        "Received birth date: %s-%s-%s", expected_year, expected_month, expected_day
    )
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == "application/xml"
    assert response.body is not None
    assert f"{expected_month} {expected_day}, {expected_year}" in response.body
    assert "Press 1 to confirm, or press 2 to re-enter" in response.body
    assert "confirm-digits/birthdate" in response.body


def test_process_digits_no_digits(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event",
        new=LambdaFunctionUrlEvent({"queryStringParameters": {}}),
    )
    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")
    with pytest.raises(
        BadRequestError, match="Birth date digits not found in the request"
    ):
        process_digits("birthdate")
    mock_logger_error.assert_called_once_with(
        "Birth date digits not found in the request"
    )


@pytest.mark.parametrize(
    ("digits", "error_pattern"),
    [
        ("1234567", "Invalid birth date format.*Expected YYYYMMDD"),
        ("123456789", "Invalid birth date format.*Expected YYYYMMDD"),
        ("abcd1234", "Invalid birth date format.*Expected YYYYMMDD"),
        ("1990/01/15", "Invalid birth date format.*Expected YYYYMMDD"),
    ],
)
def test_process_digits_invalid_format(
    digits: str, error_pattern: str, mocker: MockerFixture
) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event",
        new=LambdaFunctionUrlEvent({"queryStringParameters": {"digits": digits}}),
    )
    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")
    with pytest.raises(BadRequestError, match=error_pattern):
        process_digits("birthdate")
    assert mock_logger_error.called


def test_process_digits_ssm_error(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event",
        new=LambdaFunctionUrlEvent({"queryStringParameters": {"digits": "19900115"}}),
    )
    error_message = "SSM error"
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        side_effect=Exception(error_message),
    )
    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")
    with pytest.raises(InternalServerError, match=error_message):
        process_digits("birthdate")
    mock_logger_exception.assert_called_once_with(error_message)


@pytest.mark.parametrize(
    ("exception", "error_message"),
    [
        (BadRequestError, "Request signature is missing"),
        (UnauthorizedError, "Invalid signature"),
    ],
)
def test_process_digits_invalid_signature(
    exception: Any, error_message: str, mocker: MockerFixture
) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event",
        new=LambdaFunctionUrlEvent({
            "queryStringParameters": {"digits": "19900115"},
            "headers": {"X-Twilio-Signature": "invalid-signature"},
        }),
    )
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": "token",
            "/twh/dev/webhook-api-url": "https://api.example.com",
        },
    )
    mocker.patch(
        "twiliowebhook.api.main.validate_http_twilio_signature",
        side_effect=exception(error_message),
    )
    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")
    with pytest.raises(exception, match=error_message):
        process_digits("birthdate")
    mock_logger_exception.assert_called_once_with(error_message)


def test_confirm_digits_confirm(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = LambdaFunctionUrlEvent({
        "queryStringParameters": {"digits": "1", "birthdate": "19900115"},
        "headers": {"X-Twilio-Signature": "test-signature"},
    })
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)
    twilio_auth_token = "test-token"
    webhook_api_url = "https://api.example.com"
    mock_get_parameters_by_name = mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": twilio_auth_token,
            "/twh/dev/webhook-api-url": webhook_api_url,
        },
    )
    mock_validate_http_twilio_signature = mocker.patch(
        "twiliowebhook.api.main.validate_http_twilio_signature"
    )
    mocker.patch(
        "twiliowebhook.api.main.parse_xml_and_extract_root",
        return_value=ElementTree.parse(HANGUP_TWIML_FILE_PATH).getroot(),
    )
    mock_logger_info = mocker.patch("twiliowebhook.api.main.logger.info")

    response = confirm_digits("birthdate")

    mock_get_parameters_by_name.assert_called_once_with(
        parameters={
            "/twh/dev/twilio-auth-token": {},
            "/twh/dev/webhook-api-url": {},
        },
        decrypt=True,
        raise_on_error=True,
    )
    mock_validate_http_twilio_signature.assert_called_once_with(
        token=twilio_auth_token,
        event=mock_event,
    )
    mock_logger_info.assert_any_call(
        "Birth date confirmed: %s-%s-%s", "1990", "01", "15"
    )
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == "application/xml"
    assert response.body is not None
    assert "Thank you. We have recorded your birth date as 01 15, 1990" in response.body


def test_confirm_digits_re_enter(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = LambdaFunctionUrlEvent({
        "queryStringParameters": {"digits": "2", "birthdate": "19900115"},
        "headers": {"X-Twilio-Signature": "test-signature"},
    })
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)
    twilio_auth_token = "test-token"
    webhook_api_url = "https://api.example.com"
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": twilio_auth_token,
            "/twh/dev/webhook-api-url": webhook_api_url,
        },
    )
    mocker.patch("twiliowebhook.api.main.validate_http_twilio_signature")
    mock_logger_info = mocker.patch("twiliowebhook.api.main.logger.info")

    response = confirm_digits("birthdate")

    mock_logger_info.assert_any_call("User chose to re-enter birth date")
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == "application/xml"
    assert response.body is not None
    assert "Let's try again" in response.body
    assert "/handle-incoming-call/birthdate" in response.body


def test_confirm_digits_invalid_input(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = LambdaFunctionUrlEvent({
        "queryStringParameters": {"digits": "9", "birthdate": "19900115"},
        "headers": {"X-Twilio-Signature": "test-signature"},
    })
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)
    twilio_auth_token = "test-token"
    webhook_api_url = "https://api.example.com"
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": twilio_auth_token,
            "/twh/dev/webhook-api-url": webhook_api_url,
        },
    )
    mocker.patch("twiliowebhook.api.main.validate_http_twilio_signature")
    mock_logger_warning = mocker.patch("twiliowebhook.api.main.logger.warning")

    response = confirm_digits("birthdate")

    mock_logger_warning.assert_any_call("Invalid confirmation input: %s", "9")
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == "application/xml"
    assert response.body is not None
    assert (
        "Invalid selection. Please press 1 to confirm or 2 to re-enter" in response.body
    )
    assert "confirm-digits/birthdate" in response.body


def test_confirm_digits_no_digits(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event",
        new=LambdaFunctionUrlEvent({
            "queryStringParameters": {"birthdate": "19900115"}
        }),
    )
    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")
    with pytest.raises(
        BadRequestError, match="Confirmation digits not found in the request"
    ):
        confirm_digits("birthdate")
    mock_logger_error.assert_called_once_with(
        "Confirmation digits not found in the request"
    )


def test_confirm_digits_no_birthdate(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event",
        new=LambdaFunctionUrlEvent({"queryStringParameters": {"digits": "1"}}),
    )
    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")
    with pytest.raises(
        BadRequestError, match="Birthdate parameter not found in the request"
    ):
        confirm_digits("birthdate")
    mock_logger_error.assert_called_once_with(
        "Birthdate parameter not found in the request"
    )


def test_process_digits_invalid_target(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event",
        new=LambdaFunctionUrlEvent({"queryStringParameters": {"digits": "19900115"}}),
    )
    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")
    with pytest.raises(
        BadRequestError,
        match=re.escape("Invalid target: invalid_target. Expected 'birthdate'."),
    ):
        process_digits("invalid_target")
    mock_logger_error.assert_called_once_with(
        "Invalid target: invalid_target. Expected 'birthdate'."
    )


def test_confirm_digits_invalid_target(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event",
        new=LambdaFunctionUrlEvent({
            "queryStringParameters": {"digits": "1", "birthdate": "19900115"}
        }),
    )
    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")
    with pytest.raises(
        BadRequestError,
        match=re.escape("Invalid target: invalid_target. Expected 'birthdate'."),
    ):
        confirm_digits("invalid_target")
    mock_logger_error.assert_called_once_with(
        "Invalid target: invalid_target. Expected 'birthdate'."
    )
