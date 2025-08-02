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
from defusedxml import ElementTree
from pytest_mock import MockerFixture

from twiliowebhook.api.constants import (
    CONNECT_TWIML_FILE_PATH,
    DIAL_TWIML_FILE_PATH,
    GATHER_TWIML_FILE_PATH,
    HANGUP_TWIML_FILE_PATH,
    TWIML_DIR,
)
from twiliowebhook.api.main import (
    _fetch_caller_phone_number_from_request,
    _respond_to_call,
    check_health,
    handle_incoming_call,
    lambda_handler,
    monitor_call,
    transfer_call,
)


def test_check_health() -> None:
    response: Response[str] = check_health()
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == content_types.APPLICATION_JSON
    assert response.body is not None
    assert json.loads(response.body) == {"message": "The function is running!"}


@pytest.mark.parametrize(
    ("digits", "twiml_file_path"),
    [
        ("1", CONNECT_TWIML_FILE_PATH),
        ("2", DIAL_TWIML_FILE_PATH),
        ("3", HANGUP_TWIML_FILE_PATH),
    ],
)
def test_transfer_call(
    digits: str, twiml_file_path: str, mocker: MockerFixture
) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = LambdaFunctionUrlEvent({
        "queryStringParameters": {"digits": digits},
        "body": "From=+1234567890",
        "headers": {"X-Twilio-Signature": "test-signature"},
    })
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)
    caller_phone_number = "+1234567890"
    mocker.patch(
        "twiliowebhook.api.main._fetch_caller_phone_number_from_request",
        return_value=caller_phone_number,
    )
    twilio_auth_token = "test-token"
    media_api_url = "wss://media.example.com"
    operator_phone_number = "+1112223333"
    mock_retrieve_ssm_parameters = mocker.patch(
        "twiliowebhook.api.main.retrieve_ssm_parameters",
        return_value={
            "/twh/dev/twilio-auth-token": twilio_auth_token,
            "/twh/dev/media-api-url": media_api_url,
            "/twh/dev/operator-phone-number": operator_phone_number,
        },
    )
    mock_validate_http_twilio_signature = mocker.patch(
        "twiliowebhook.api.main.validate_http_twilio_signature"
    )
    mock_parse_xml_and_extract_root = mocker.patch(
        "twiliowebhook.api.main.parse_xml_and_extract_root",
        return_value=ElementTree.parse(twiml_file_path).getroot(),
    )
    response = transfer_call()
    mock_retrieve_ssm_parameters.assert_called_once_with(
        "/twh/dev/twilio-auth-token",
        "/twh/dev/media-api-url",
        "/twh/dev/operator-phone-number",
    )
    mock_validate_http_twilio_signature.assert_called_once_with(
        token=twilio_auth_token,
        event=mock_event,
    )
    mock_parse_xml_and_extract_root.assert_called_once_with(
        xml_file_path=twiml_file_path
    )
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == "application/xml"
    assert response.body is not None
    if twiml_file_path == CONNECT_TWIML_FILE_PATH:
        assert caller_phone_number in response.body
        assert media_api_url in response.body
    elif twiml_file_path == DIAL_TWIML_FILE_PATH:
        assert operator_phone_number in response.body
    else:
        assert "<Hangup />" in response.body


def test_transfer_call_no_digits(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event",
        new=LambdaFunctionUrlEvent({"queryStringParameters": {}}),
    )
    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")
    with pytest.raises(BadRequestError, match="Digits not found in the request body"):
        transfer_call()
    mock_logger_error.assert_called_once_with("Digits not found in the request body")


def test_transfer_call_ssm_error(mocker: MockerFixture) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event",
        new=LambdaFunctionUrlEvent({"queryStringParameters": {"digits": "1"}}),
    )
    error_message = "SSM error"
    mocker.patch(
        "twiliowebhook.api.main.retrieve_ssm_parameters",
        side_effect=Exception(error_message),
    )
    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")
    with pytest.raises(InternalServerError, match=error_message):
        transfer_call()
    mock_logger_exception.assert_called_once_with(error_message)


@pytest.mark.parametrize(
    ("exception", "error_message"),
    [
        (BadRequestError, "Request signature is missing"),
        (UnauthorizedError, "Invalid signature"),
    ],
)
def test_transfer_call_invalid_signature(
    exception: Any, error_message: str, mocker: MockerFixture
) -> None:
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mocker.patch(
        "twiliowebhook.api.main.app.current_event",
        new=LambdaFunctionUrlEvent({
            "queryStringParameters": {"digits": "1"},
            "headers": {"X-Twilio-Signature": "invalid-signature"},
        }),
    )
    mocker.patch(
        "twiliowebhook.api.main.retrieve_ssm_parameters",
        return_value={"/twh/dev/twilio-auth-token": "token"},
    )
    mocker.patch(
        "twiliowebhook.api.main.validate_http_twilio_signature",
        side_effect=exception(error_message),
    )
    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")
    with pytest.raises(exception, match=error_message):
        transfer_call()
    mock_logger_exception.assert_called_once_with(error_message)


def test_handle_incoming_call(mocker: MockerFixture) -> None:
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
            "/twh/dev/twilio-auth-token": twilio_auth_token,
            "/twh/dev/media-api-url": media_api_url,
            "/twh/dev/webhook-api-url": webhook_api_url,
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
        "/twh/dev/twilio-auth-token",
        "/twh/dev/media-api-url",
        "/twh/dev/webhook-api-url",
    )
    mock_validate_http_twilio_signature.assert_called_once_with(
        token=twilio_auth_token,
        event=mocker.ANY,
    )
    mock__respond_to_call.assert_called_once_with(
        twiml_file_path=CONNECT_TWIML_FILE_PATH,
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
    twiml_file_path = {
        "connect": CONNECT_TWIML_FILE_PATH,
        "gather": GATHER_TWIML_FILE_PATH,
        "hangup": HANGUP_TWIML_FILE_PATH,
    }[twiml_file_stem]
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


@pytest.mark.parametrize(
    ("phone_number", "body"),
    [
        ("+1234567890", "From=+1234567890"),
        ("+1234567890", "To=+0987654321&CallSid=CA123&From=+1234567890"),
        ("+1111111111", "From=+1111111111&OtherParam=value&From=+2222222222"),
        ("+1234567890", "MalformedParameter&From=+1234567890&AnotherParam=value"),
    ],
)
def test__fetch_caller_phone_number_from_request(phone_number: str, body: str) -> None:
    event = LambdaFunctionUrlEvent({"body": body})
    assert _fetch_caller_phone_number_from_request(event=event) == phone_number


@pytest.mark.parametrize("body", ["To=+0987654321", "From=", ""])
def test__fetch_caller_phone_number_from_request_bad_request_error(body: str) -> None:
    event = LambdaFunctionUrlEvent({"body": body})
    with pytest.raises(
        BadRequestError, match="Call number not found in the request body"
    ):
        _fetch_caller_phone_number_from_request(event=event)


def test_handle_incoming_call_invalid_twiml_file_stem(mocker: MockerFixture) -> None:
    app_mock = LambdaFunctionUrlResolver()
    app_mock.current_event = LambdaFunctionUrlEvent({})
    mocker.patch("twiliowebhook.api.main.app", app_mock)
    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")
    invalid_stem = "non_existent_file"
    expected_error_message = f"Invalid TwiML file: {TWIML_DIR / invalid_stem}.twiml.xml"
    with pytest.raises(BadRequestError, match=expected_error_message):
        handle_incoming_call(twiml_file_stem=invalid_stem)
    mock_logger_error.assert_called_once_with(expected_error_message)
    with pytest.raises(
        BadRequestError, match="Call number not found in the request body"
    ):
        _fetch_caller_phone_number_from_request(event=LambdaFunctionUrlEvent({}))


def test_monitor_call_success(mocker: MockerFixture) -> None:
    call_sid = "CA1234567890abcdef1234567890abcdef"

    # Mock SSM parameters
    mock_retrieve_ssm_parameters = mocker.patch(
        "twiliowebhook.api.main.retrieve_ssm_parameters",
        return_value={
            "/twh/dev/twilio-account-sid": "test-account-sid",
            "/twh/dev/twilio-auth-token": "test-token",
        },
    )

    # Mock Twilio client and call object
    mock_call = mocker.MagicMock()
    mock_call.to_dict.return_value = {
        "sid": call_sid,
        "from": "+1234567890",
        "to": "+0987654321",
        "status": "completed",
        "direction": "inbound",
        "duration": "120",
        "price": "-0.02",
        "price_unit": "USD",
        "start_time": "2023-01-01T12:00:00Z",
        "end_time": "2023-01-01T12:02:00Z",
        "answered_by": "human",
        "forwarded_from": None,
        "caller_name": "Test Caller",
        "parent_call_sid": None,
        "queue_time": "0",
    }

    mock_calls = mocker.MagicMock()
    mock_calls.return_value.fetch.return_value = mock_call

    mock_client = mocker.MagicMock()
    mock_client.calls = mock_calls

    mock_client_class = mocker.patch(
        "twiliowebhook.api.main.Client", return_value=mock_client
    )

    response = monitor_call(call_sid)

    # Verify SSM parameters were retrieved
    mock_retrieve_ssm_parameters.assert_called_once_with(
        "/twh/dev/twilio-account-sid",
        "/twh/dev/twilio-auth-token",
    )

    # Verify Twilio client was initialized correctly
    mock_client_class.assert_called_once()
    call_args = mock_client_class.call_args
    assert call_args.kwargs["username"] == "test-account-sid"
    assert call_args.kwargs["password"] == "test-token"
    # Check that http_client is passed (we don't need to check the exact type in tests)
    assert "http_client" in call_args.kwargs

    # Verify call fetch was called
    mock_calls.assert_called_once_with(call_sid)
    mock_calls.return_value.fetch.assert_called_once()

    # Verify response
    assert response.status_code == HTTPStatus.OK
    assert response.content_type == content_types.APPLICATION_JSON
    assert response.body is not None

    body = json.loads(response.body)
    assert body["sid"] == call_sid
    assert body["from"] == "+1234567890"
    assert body["to"] == "+0987654321"
    assert body["status"] == "completed"
    assert body["start_time"] == "2023-01-01T12:00:00Z"


def test_monitor_call_not_found(mocker: MockerFixture) -> None:
    call_sid = "CA1234567890abcdef1234567890abcdef"

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.retrieve_ssm_parameters",
        return_value={
            "/twh/dev/twilio-account-sid": "test-account-sid",
            "/twh/dev/twilio-auth-token": "test-token",
        },
    )

    # Import the real exception class
    from twilio.base.exceptions import TwilioRestException  # noqa: PLC0415

    # Create a mock exception instance with the expected attributes
    mock_exception = TwilioRestException(
        404, "https://api.twilio.com", "Call not found", 20404
    )
    mock_exception.code = 20404
    mock_exception.msg = "Call not found"

    # Mock client to raise exception
    mock_client = mocker.MagicMock()
    mock_client.calls.return_value.fetch.side_effect = mock_exception

    mocker.patch("twiliowebhook.api.main.Client", return_value=mock_client)

    # Mock logger
    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    with pytest.raises(BadRequestError, match=f"Call not found: {call_sid}"):
        monitor_call(call_sid)

    mock_logger_exception.assert_called_once_with(f"Call not found: {call_sid}")


def test_monitor_call_twilio_error(mocker: MockerFixture) -> None:
    call_sid = "CA1234567890abcdef1234567890abcdef"

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.retrieve_ssm_parameters",
        return_value={
            "/twh/dev/twilio-account-sid": "test-account-sid",
            "/twh/dev/twilio-auth-token": "test-token",
        },
    )

    # Import and mock TwilioRestException for other errors
    from twilio.base.exceptions import TwilioRestException  # noqa: PLC0415

    # Mock client to raise exception
    mock_client = mocker.MagicMock()
    mock_client.calls.return_value.fetch.side_effect = TwilioRestException(
        500, "https://api.twilio.com", "Internal Server Error", 30001
    )

    mocker.patch("twiliowebhook.api.main.Client", return_value=mock_client)

    # Mock logger
    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    msg = "Twilio API error: Internal Server Error"
    with pytest.raises(InternalServerError, match=msg):
        monitor_call(call_sid)

    mock_logger_exception.assert_called_once_with(msg)


def test_monitor_call_ssm_error(mocker: MockerFixture) -> None:
    call_sid = "CA1234567890abcdef1234567890abcdef"
    error_message = "SSM parameter not found"

    # Mock SSM parameters to raise ValueError
    mocker.patch(
        "twiliowebhook.api.main.retrieve_ssm_parameters",
        side_effect=ValueError(error_message),
    )

    # Mock logger
    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    msg = f"Invalid parameter configuration: {error_message}"
    with pytest.raises(InternalServerError, match=msg):
        monitor_call(call_sid)

    mock_logger_exception.assert_called_once_with(msg)
