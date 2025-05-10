"""Unit tests for twiliowebhook.api.main module."""
# pyright: reportPrivateUsage=false

import json
from http import HTTPStatus
from typing import Any

import pytest
from aws_lambda_powertools.event_handler import (
    LambdaFunctionUrlResolver,
    Response,
    content_types,
)
from aws_lambda_powertools.event_handler.exceptions import (
    BadRequestError,
    InternalServerError,
    UnauthorizedError,
)
from aws_lambda_powertools.utilities.data_classes import LambdaFunctionUrlEvent
from pytest_mock import MockerFixture

from twiliowebhook.api.main import (
    _TWIML_DIR,
    _respond_to_call,
    check_health,
    handle_incoming_call,
    lambda_handler,
)


def test_check_health() -> None:
    response: Response[str] = check_health()
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == content_types.APPLICATION_JSON
    assert response.body is not None
    assert json.loads(response.body) == {"message": "The function is running!"}


def test_handle_incoming_call(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main._SYSTEM_NAME", new="test")
    mocker.patch("twiliowebhook.api.main._ENV_TYPE", new="mock")
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
    mock_retrieve_ssm_parameters = mocker.patch(
        "twiliowebhook.api.main.retrieve_ssm_parameters",
        return_value={
            "/test/mock/twilio-auth-token": twilio_auth_token,
            "/test/mock/media-api-url": media_api_url,
            "/test/mock/webhook-api-url": webhook_api_url,
        },
    )
    mock_validate_http_twilio_signature = mocker.patch(
        "twiliowebhook.api.main.validate_http_twilio_signature",
        return_value=None,
    )
    mock__respond_to_call = mocker.patch(
        "twiliowebhook.api.main._respond_to_call",
        return_value=Response(
            status_code=HTTPStatus.OK,
            content_type="application/xml",
            body=media_api_url,
        ),
    )
    response: Response[str] = handle_incoming_call(twiml_file_stem="connect")
    mock_retrieve_ssm_parameters.assert_called_once_with(
        "/test/mock/twilio-auth-token",
        "/test/mock/media-api-url",
        "/test/mock/webhook-api-url",
    )
    mock_validate_http_twilio_signature.assert_called_once_with(
        token=twilio_auth_token,
        event=mocker.ANY,
    )
    mock__respond_to_call.assert_called_once_with(
        twiml_file_path=str(_TWIML_DIR / "connect.twiml.xml"),
        caller_phone_number=caller_phone_number,
        media_api_url=media_api_url,
        webhook_api_url=webhook_api_url,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == "application/xml"
    assert response.body == "wss://api.example.com"


def test_handle_incoming_call_invalid_parameters(mocker: MockerFixture) -> None:
    app = LambdaFunctionUrlResolver()
    app.current_event = LambdaFunctionUrlEvent({})
    mocker.patch("twiliowebhook.api.main.app", return_value=app)
    mocker.patch("twiliowebhook.api.main.app.current_event", new=app.current_event)
    mocker.patch(
        "twiliowebhook.api.main._fetch_caller_phone_number_from_request",
        return_value="+1234567890",
    )
    error_message: str = "Invalid parameters"
    mocker.patch(
        "twiliowebhook.api.main.retrieve_ssm_parameters",
        side_effect=ValueError(error_message),
    )
    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")
    with pytest.raises(InternalServerError, match=error_message):
        handle_incoming_call(twiml_file_stem="connect")
    mock_logger_exception.assert_called_once_with(error_message)


@pytest.mark.parametrize(
    ("exception", "error_message"),
    [
        (BadRequestError, "Request signature is missing"),
        (UnauthorizedError, "Invalid signature"),
    ],
)
def test_handle_incoming_call_invalid_signature(
    exception: Any,
    error_message: str,
    mocker: MockerFixture,
) -> None:
    mocker.patch("twiliowebhook.api.main._SYSTEM_NAME", new="test")
    mocker.patch("twiliowebhook.api.main._ENV_TYPE", new="mock")
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event", new=LambdaFunctionUrlEvent({})
    )
    mocker.patch(
        "twiliowebhook.api.main._fetch_caller_phone_number_from_request",
        return_value="+1234567890",
    )
    mocker.patch("twiliowebhook.api.main.retrieve_ssm_parameters")
    mocker.patch(
        "twiliowebhook.api.main.validate_http_twilio_signature",
        side_effect=exception(error_message),
    )
    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")
    with pytest.raises(exception, match=error_message):
        handle_incoming_call(twiml_file_stem="connect")
    mock_logger_exception.assert_called_once_with(error_message)


@pytest.mark.parametrize("twiml_file_stem", ["connect", "gather", "hangup"])
def test__respond_to_call(twiml_file_stem: str) -> None:
    twiml_file_path = str(_TWIML_DIR / f"{twiml_file_stem}.twiml.xml")
    caller_phone_number: str = "+1234567890"
    media_api_url: str = "wss://api.example.com"
    webhook_api_url: str = "https://api.example.com"
    response: Response[str] = _respond_to_call(
        twiml_file_path=twiml_file_path,
        caller_phone_number=caller_phone_number,
        media_api_url=media_api_url,
        webhook_api_url=webhook_api_url,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == "application/xml"
    response_body = response.body or ""
    if twiml_file_stem == "connect":
        assert caller_phone_number in response_body
        assert media_api_url in response_body
    elif twiml_file_stem == "gather":
        assert webhook_api_url in response_body


def test_lambda_handler(mocker: MockerFixture) -> None:
    event = mocker.MagicMock()
    context = mocker.MagicMock()
    mock_response = {"statusCode": 200, "body": "test"}
    mock_app_resolve = mocker.patch(
        "twiliowebhook.api.main.app.resolve", return_value=mock_response
    )
    assert lambda_handler(event, context) == mock_response
    mock_app_resolve.assert_called_once_with(event=event, context=context)
