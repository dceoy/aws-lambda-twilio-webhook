"""Unit tests for twiliowebhook.api.twilio module."""

import base64

import pytest
from aws_lambda_powertools.event_handler.exceptions import (
    BadRequestError,
    UnauthorizedError,
)
from aws_lambda_powertools.utilities.data_classes import LambdaFunctionUrlEvent
from pytest_mock import MockerFixture

from twiliowebhook.api.twilio import validate_http_twilio_signature


def test_validate_http_twilio_signature(mocker: MockerFixture) -> None:
    event = LambdaFunctionUrlEvent({
        "headers": {"X-Twilio-Signature": "valid"},
        "requestContext": {
            "domainName": "example.com",
            "stage": "$default",
            "http": {"method": "POST", "path": "/incoming-call"},
        },
        "rawPath": "/incoming-call",
        "path": "/incoming-call",
        "body": base64.b64encode(b"From=+1234567890&To=").decode("utf-8"),
        "isBase64Encoded": True,
    })
    mock_validator = mocker.MagicMock()
    mocker.patch(
        "twiliowebhook.api.twilio.RequestValidator", return_value=mock_validator
    )
    mock_validator_validate = mocker.patch.object(
        mock_validator, "validate", return_value=True
    )
    mock_logger_info = mocker.patch("twiliowebhook.api.twilio.logger.info")
    validate_http_twilio_signature("test-token", event)
    mock_validator_validate.assert_called_once_with(
        uri="https://example.com/incoming-call",
        params={"From": " 1234567890", "To": ""},
        signature="valid",
    )
    mock_logger_info.assert_any_call("Twilio request signature is valid")


def test_validate_http_twilio_signature_missing_signature(
    mocker: MockerFixture,
) -> None:
    event = LambdaFunctionUrlEvent({
        "headers": {},
        "requestContext": {
            "domainName": "example.com",
            "stage": "$default",
            "http": {"method": "POST", "path": "/incoming-call"},
        },
        "rawPath": "/incoming-call",
        "path": "/incoming-call",
        "body": "From=+1234567890&To=",
    })
    mocker.patch(
        "twiliowebhook.api.twilio.RequestValidator", return_value=mocker.MagicMock()
    )
    with pytest.raises(BadRequestError, match="Missing X-Twilio-Signature header"):
        validate_http_twilio_signature("test-token", event)


def test_validate_http_twilio_signature_invalid(mocker: MockerFixture) -> None:
    event = LambdaFunctionUrlEvent({
        "headers": {"X-Twilio-Signature": "invalid"},
        "requestContext": {
            "domainName": "example.com",
            "stage": "$default",
            "http": {"method": "POST", "path": "/incoming-call"},
        },
        "rawPath": "/incoming-call",
        "path": "/incoming-call",
        "body": "From=+1234567890&To=",
    })
    mock_validator = mocker.MagicMock()
    mocker.patch(
        "twiliowebhook.api.twilio.RequestValidator", return_value=mock_validator
    )
    mocker.patch.object(mock_validator, "validate", return_value=False)
    with pytest.raises(UnauthorizedError, match="Invalid Twilio request signature"):
        validate_http_twilio_signature("test-token", event)
