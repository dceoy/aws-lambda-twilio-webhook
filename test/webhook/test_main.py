#!/usr/bin/env python
# pyright: reportPrivateUsage=false

import base64
import json
import re
from http import HTTPStatus
from typing import Any

import boto3
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
from moto import mock_aws
from pytest_mock import MockFixture

from webhook.main import (
    _respond_to_call,
    _retrieve_ssm_parameters,
    _validate_twilio_signature,
    handle_incoming_call,
    index_page,
    lambda_handler,
)


def test_index_page() -> None:
    response: Response[str] = index_page()
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == content_types.APPLICATION_JSON
    assert response.body is not None
    assert json.loads(response.body) == {"message": "The function is running!"}


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSTEM_NAME", "test")
    monkeypatch.setenv("ENV_TYPE", "mock")


def test_handle_incoming_call(mock_env: None, mocker: MockFixture) -> None:
    app = LambdaFunctionUrlResolver()
    app.current_event = LambdaFunctionUrlEvent({})
    mocker.patch("webhook.main.app", return_value=app)
    mock__retrieve_ssm_parameters = mocker.patch(
        "webhook.main._retrieve_ssm_parameters",
        return_value={
            "/test/mock/twilio-auth-token": "test-token",
            "/test/mock/media-api-url": "wss://api.example.com",
        },
    )
    mock__validate_twilio_signature = mocker.patch(
        "webhook.main._validate_twilio_signature",
        return_value=None,
    )
    mock__respond_to_call = mocker.patch(
        "webhook.main._respond_to_call",
        return_value=Response(
            status_code=HTTPStatus.OK,
            content_type="application/xml",
            body="wss://api.example.com",
        ),
    )
    response: Response[str] = handle_incoming_call()
    mock__retrieve_ssm_parameters.assert_called_once_with(
        "/test/mock/twilio-auth-token",
        "/test/mock/media-api-url",
    )
    mock__validate_twilio_signature.assert_called_once_with(
        token="test-token",  # noqa: S106
        event=mocker.ANY,
    )
    mock__respond_to_call.assert_called_once_with(
        media_api_url="wss://api.example.com",
    )
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == "application/xml"
    assert response.body == "wss://api.example.com"


def test_handle_incoming_call_invalid_parameters(
    mock_env: None,
    mocker: MockFixture,
) -> None:
    error_message: str = "Invalid parameters"
    mocker.patch(
        "webhook.main._retrieve_ssm_parameters",
        side_effect=InternalServerError(error_message),
    )
    mock_logger_exception = mocker.patch("webhook.main.logger.exception")
    with pytest.raises(InternalServerError):
        handle_incoming_call()
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
    mock_env: None,
    mocker: MockFixture,
) -> None:
    app = LambdaFunctionUrlResolver()
    app.current_event = LambdaFunctionUrlEvent({})
    mocker.patch("webhook.main.app", return_value=app)
    mocker.patch("webhook.main._retrieve_ssm_parameters")
    mocker.patch(
        "webhook.main._validate_twilio_signature",
        side_effect=exception(error_message),
    )
    mock_logger_exception = mocker.patch("webhook.main.logger.exception")
    with pytest.raises(exception):
        handle_incoming_call()
    mock_logger_exception.assert_called_once_with(error_message)


@mock_aws
def test__retrieve_ssm_parameters(mocker: MockFixture) -> None:
    test_parameters: dict[str, str] = {
        "/test/mock/twilio-auth-token": "test-token",
        "/test/mock/media-api-url": "wss://api.example.com",
    }
    ssm = boto3.client("ssm", region_name="us-west-2")
    mocker.patch("webhook.main.boto3.client", return_value=ssm)
    for k, v in test_parameters.items():
        ssm.put_parameter(
            Name=k, Value=v, Type=("SecureString" if "auth" in k else "String")
        )
    mocker.patch(
        "webhook.main.boto3.client.get_parameters",
        return_value=ssm.get_parameters(
            Names=list(test_parameters.keys()),
            WithDecryption=True,
        ),
    )
    params: dict[str, str] = _retrieve_ssm_parameters(*test_parameters.keys())
    assert params == {
        "/test/mock/twilio-auth-token": "test-token",
        "/test/mock/media-api-url": "wss://api.example.com",
    }


@mock_aws
def test__retrieve_ssm_parameters_invalid(mocker: MockFixture) -> None:
    invalid_parameter_name: str = "/invalid-parameter"
    ssm = boto3.client("ssm", region_name="us-west-2")
    mocker.patch("webhook.main.boto3.client", return_value=ssm)
    mocker.patch(
        "webhook.main.boto3.client.get_parameters",
        return_value=ssm.get_parameters(
            Names=[invalid_parameter_name],
            WithDecryption=True,
        ),
    )
    error_message: str = f"Invalid parameters: {[invalid_parameter_name]}"
    with pytest.raises(InternalServerError, match=re.escape(error_message)):
        _retrieve_ssm_parameters(invalid_parameter_name)


def test__respond_to_call() -> None:
    media_api_url: str = "wss://api.example.com"
    response: Response[str] = _respond_to_call(media_api_url)
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == "application/xml"
    assert f' url="{media_api_url}" ' in (response.body or "")


def test__validate_twilio_signature(mocker: MockFixture) -> None:
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
    mocker.patch("webhook.main.RequestValidator", return_value=mock_validator)
    mock_validator_validate = mocker.patch.object(
        mock_validator, "validate", return_value=True
    )
    mock_logger_info = mocker.patch("webhook.main.logger.info")
    _validate_twilio_signature("test-token", event)
    mock_validator_validate.assert_called_once_with(
        uri="https://example.com/incoming-call",
        params={"From": " 1234567890", "To": ""},
        signature="valid",
    )
    mock_logger_info.assert_any_call("Twilio request signature is valid")


def test__validate_twilio_signature_missing_signature(mocker: MockFixture) -> None:
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
        "webhook.main.RequestValidator", return_value=mocker.MagicMock()
    )
    with pytest.raises(BadRequestError, match="Missing X-Twilio-Signature header"):
        _validate_twilio_signature("test-token", event)


def test__validate_twilio_signature_invalid(mocker: MockFixture) -> None:
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
    mocker.patch("webhook.main.RequestValidator", return_value=mock_validator)
    mocker.patch.object(mock_validator, "validate", return_value=False)
    with pytest.raises(UnauthorizedError, match="Invalid Twilio request signature"):
        _validate_twilio_signature("test-token", event)


def test_lambda_handler(mocker: MockFixture) -> None:
    event = mocker.MagicMock()
    context = mocker.MagicMock()
    mock_response = {"statusCode": 200, "body": "test"}
    mock_app_resolve = mocker.patch(
        "webhook.main.app.resolve", return_value=mock_response
    )
    assert lambda_handler(event, context) == mock_response
    mock_app_resolve.assert_called_once_with(event=event, context=context)
