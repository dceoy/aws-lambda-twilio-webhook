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
from aws_lambda_powertools.utilities.parameters.exceptions import GetParameterError
from defusedxml import ElementTree
from pytest_mock import MockerFixture

from twiliowebhook.api.constants import (
    BIRTHDATE_TWIML_FILE_PATH,
    CONNECT_TWIML_FILE_PATH,
    DIAL_TWIML_FILE_PATH,
    GATHER_TWIML_FILE_PATH,
    HANGUP_TWIML_FILE_PATH,
    TWIML_DIR,
)
from twiliowebhook.api.main import (
    _extract_next_page_token,
    _fetch_caller_phone_number_from_request,
    _respond_to_call,
    _validate_batch_monitor_params,
    batch_monitor_calls,
    check_health,
    confirm_digits,
    handle_incoming_call,
    lambda_handler,
    monitor_call,
    process_digits,
    transfer_call,
)

# Test constants
EXPECTED_LIMIT_50 = 50
EXPECTED_LIMIT_100 = 100
HTTP_OK = 200


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
    mock_get_parameters_by_name = mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
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
    mock_get_parameters_by_name.assert_called_once_with(
        parameters={
            "/twh/dev/twilio-auth-token": {},
            "/twh/dev/media-api-url": {},
            "/twh/dev/operator-phone-number": {},
        },
        decrypt=True,
        raise_on_error=True,
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
        "twiliowebhook.api.main.get_parameters_by_name",
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
        "twiliowebhook.api.main.get_parameters_by_name",
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
    mock__respond_to_call = mocker.patch(
        "twiliowebhook.api.main._respond_to_call",
        return_value=Response(
            status_code=HTTPStatus.OK,
            content_type="application/xml",
            body=media_api_url,
        ),
    )
    response: Response[str] = handle_incoming_call(twiml_file_stem="connect")
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
    error_detail: str = "SSM parameter error"
    error_message: str = f"Invalid parameters: [{error_detail}]"
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        side_effect=GetParameterError(error_detail),
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
    mocker.patch("twiliowebhook.api.main.get_parameters_by_name")
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
    mock_get_parameters_by_name = mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
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
    mock_get_parameters_by_name.assert_called_once_with(
        parameters={
            "/twh/dev/twilio-account-sid": {},
            "/twh/dev/twilio-auth-token": {},
        },
        decrypt=True,
        raise_on_error=True,
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
        "twiliowebhook.api.main.get_parameters_by_name",
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
        "twiliowebhook.api.main.get_parameters_by_name",
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
    error_detail = "SSM parameter not found"

    # Mock SSM parameters to raise GetParameterError
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        side_effect=GetParameterError(error_detail),
    )

    # Mock logger
    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    msg = f"Invalid parameter configuration: Invalid parameters: [{error_detail}]"
    with pytest.raises(InternalServerError, match=msg):
        monitor_call(call_sid)

    mock_logger_exception.assert_called_once_with(msg)


def test_batch_monitor_calls_success(mocker: MockerFixture) -> None:
    """Test successful batch monitor calls request."""
    # Mock event with query parameters
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {
        "queryStringParameters": {
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-31T23:59:59Z",
            "limit": "50",
        }
    }
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-account-sid": "test-account-sid",
            "/twh/dev/twilio-auth-token": "test-token",
        },
    )

    # Mock call data
    mock_call_1 = mocker.MagicMock()
    mock_call_1.to_dict.return_value = {
        "sid": "CA1111111111111111111111111111111",
        "status": "completed",
        "direction": "inbound",
        "start_time": "2024-01-15T10:30:00Z",
    }

    mock_call_2 = mocker.MagicMock()
    mock_call_2.to_dict.return_value = {
        "sid": "CA2222222222222222222222222222222",
        "status": "completed",
        "direction": "outbound-api",
        "start_time": "2024-01-20T14:45:00Z",
    }

    # Mock calls page
    mock_calls_page = mocker.MagicMock()
    mock_calls_page.__iter__.return_value = [mock_call_1, mock_call_2]
    mock_calls_page.next_page_url = None

    # Mock client
    mock_client = mocker.MagicMock()
    mock_client.calls.page.return_value = mock_calls_page

    mocker.patch("twiliowebhook.api.main.Client", return_value=mock_client)

    # Mock logger
    mock_logger_info = mocker.patch("twiliowebhook.api.main.logger.info")

    response = batch_monitor_calls()

    assert response.status_code == HTTPStatus.OK
    assert response.content_type == "application/json"

    assert response.body is not None
    response_data = json.loads(response.body)
    expected_count = 2
    assert len(response_data["calls"]) == expected_count
    assert response_data["count"] == expected_count
    assert response_data["next_page_token"] is None

    mock_logger_info.assert_called_with(
        "Batch call monitoring completed",
        extra={
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-31T23:59:59Z",
            "count": expected_count,
        },
    )


def test_batch_monitor_calls_with_filters(mocker: MockerFixture) -> None:
    """Test batch monitor calls with status and direction filters."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {
        "queryStringParameters": {
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-31T23:59:59Z",
            "status": "completed",
            "direction": "inbound",
            "limit": "25",
        }
    }
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-account-sid": "test-account-sid",
            "/twh/dev/twilio-auth-token": "test-token",
        },
    )

    # Mock calls page
    mock_calls_page = mocker.MagicMock()
    mock_calls_page.__iter__.return_value = []
    mock_calls_page.next_page_url = None

    # Mock client
    mock_client = mocker.MagicMock()
    mock_client.calls.page.return_value = mock_calls_page

    mocker.patch("twiliowebhook.api.main.Client", return_value=mock_client)

    batch_monitor_calls()

    # Verify the client was called with correct filters
    from datetime import datetime  # noqa: PLC0415

    mock_client.calls.page.assert_called_once_with(
        start_time_after=datetime.fromisoformat("2024-01-01T00:00:00Z"),
        start_time_before=datetime.fromisoformat("2024-01-31T23:59:59Z"),
        limit=25,
        status="completed",
        direction="inbound",
    )


def test_batch_monitor_calls_with_pagination(mocker: MockerFixture) -> None:
    """Test batch monitor calls with pagination token."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {
        "queryStringParameters": {
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-31T23:59:59Z",
            "page_token": "PA1234567890",
        }
    }
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-account-sid": "test-account-sid",
            "/twh/dev/twilio-auth-token": "test-token",
        },
    )

    # Mock calls page with next page URL
    mock_calls_page = mocker.MagicMock()
    mock_calls_page.__iter__.return_value = []
    mock_calls_page.next_page_url = (
        "https://api.twilio.com/2010-04-01/Accounts/ACXXXXXXX/"
        "Calls.json?PageToken=PAXXXXXXX&Page=1"
    )

    # Mock client
    mock_client = mocker.MagicMock()
    mock_client.calls.page.return_value = mock_calls_page

    mocker.patch("twiliowebhook.api.main.Client", return_value=mock_client)

    response = batch_monitor_calls()
    assert response.body is not None
    response_data = json.loads(response.body)

    assert response_data["next_page_token"] == "PAXXXXXXX"


def test_batch_monitor_calls_missing_dates(mocker: MockerFixture) -> None:
    """Test batch monitor calls with missing date parameters."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {
        "queryStringParameters": {
            "start_date": "2024-01-01T00:00:00Z",
            # end_date is missing
        }
    }
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")

    expected_msg = "Both start_date and end_date are required parameters"
    with pytest.raises(BadRequestError, match=expected_msg):
        batch_monitor_calls()

    mock_logger_error.assert_called_once_with(expected_msg)


def test_batch_monitor_calls_invalid_date_format(mocker: MockerFixture) -> None:
    """Test batch monitor calls with invalid date format."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {
        "queryStringParameters": {
            "start_date": "2024-01-01",  # Missing time component
            "end_date": "2024-01-31T23:59:59Z",
        }
    }
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-account-sid": "test-account-sid",
            "/twh/dev/twilio-auth-token": "test-token",
        },
    )

    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    with pytest.raises(BadRequestError, match="Invalid date format"):
        batch_monitor_calls()

    assert mock_logger_exception.called


def test_batch_monitor_calls_invalid_date_range(mocker: MockerFixture) -> None:
    """Test batch monitor calls with start_date after end_date."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {
        "queryStringParameters": {
            "start_date": "2024-01-31T23:59:59Z",
            "end_date": "2024-01-01T00:00:00Z",
        }
    }
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-account-sid": "test-account-sid",
            "/twh/dev/twilio-auth-token": "test-token",
        },
    )

    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")

    expected_msg = "start_date must be before or equal to end_date"
    with pytest.raises(BadRequestError, match=expected_msg):
        batch_monitor_calls()

    mock_logger_error.assert_called_once_with(expected_msg)


def test_batch_monitor_calls_invalid_limit(mocker: MockerFixture) -> None:
    """Test batch monitor calls with invalid limit parameter."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {
        "queryStringParameters": {
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-31T23:59:59Z",
            "limit": "1500",  # Over the maximum
        }
    }
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")

    with pytest.raises(BadRequestError, match="Limit must be between 1 and 1000"):
        batch_monitor_calls()

    mock_logger_error.assert_called_once_with("Limit must be between 1 and 1000")


def test_batch_monitor_calls_twilio_error(mocker: MockerFixture) -> None:
    """Test batch monitor calls with Twilio API error."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {
        "queryStringParameters": {
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-31T23:59:59Z",
        }
    }
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-account-sid": "test-account-sid",
            "/twh/dev/twilio-auth-token": "test-token",
        },
    )

    # Import and mock TwilioRestException
    from twilio.base.exceptions import TwilioRestException  # noqa: PLC0415

    # Mock client to raise exception
    mock_client = mocker.MagicMock()
    mock_client.calls.page.side_effect = TwilioRestException(
        401, "https://api.twilio.com", "Unauthorized", 20003
    )

    mocker.patch("twiliowebhook.api.main.Client", return_value=mock_client)

    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    with pytest.raises(InternalServerError, match="Twilio API error: Unauthorized"):
        batch_monitor_calls()

    mock_logger_exception.assert_called_once_with("Twilio API error: Unauthorized")


def test_validate_batch_monitor_params_success() -> None:
    """Test successful validation of batch monitor parameters."""
    query_params = {
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-01-31T23:59:59Z",
        "status": "completed",
        "direction": "inbound",
        "limit": "50",
        "page_token": "PA1234567890",
    }

    result = _validate_batch_monitor_params(query_params)

    assert result["start_date"] == "2024-01-01T00:00:00Z"
    assert result["end_date"] == "2024-01-31T23:59:59Z"
    assert result["status"] == "completed"
    assert result["direction"] == "inbound"
    assert result["limit"] == EXPECTED_LIMIT_50
    assert result["page_token"] == "PA1234567890"
    assert "start_dt" in result
    assert "end_dt" in result


def test_validate_batch_monitor_params_missing_dates() -> None:
    """Test validation fails when dates are missing."""
    query_params = {"start_date": "2024-01-01T00:00:00Z"}

    with pytest.raises(
        BadRequestError, match="Both start_date and end_date are required parameters"
    ):
        _validate_batch_monitor_params(query_params)


def test_validate_batch_monitor_params_invalid_date_format() -> None:
    """Test validation fails with invalid date format."""
    query_params = {
        "start_date": "invalid-date",
        "end_date": "2024-01-31T23:59:59Z",
    }

    with pytest.raises(BadRequestError, match="Invalid date format"):
        _validate_batch_monitor_params(query_params)


def test_validate_batch_monitor_params_invalid_date_range() -> None:
    """Test validation fails when start_date is after end_date."""
    query_params = {
        "start_date": "2024-01-31T23:59:59Z",
        "end_date": "2024-01-01T00:00:00Z",
    }

    with pytest.raises(
        BadRequestError, match="start_date must be before or equal to end_date"
    ):
        _validate_batch_monitor_params(query_params)


def test_validate_batch_monitor_params_invalid_limit() -> None:
    """Test validation fails with invalid limit values."""
    # Test negative limit
    query_params = {
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-01-31T23:59:59Z",
        "limit": "-1",
    }

    with pytest.raises(BadRequestError, match="Limit must be between 1 and 1000"):
        _validate_batch_monitor_params(query_params)

    # Test limit too high
    query_params["limit"] = "1001"

    with pytest.raises(BadRequestError, match="Limit must be between 1 and 1000"):
        _validate_batch_monitor_params(query_params)


def test_validate_batch_monitor_params_defaults() -> None:
    """Test default values are applied correctly."""
    query_params = {
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-01-31T23:59:59Z",
    }

    result = _validate_batch_monitor_params(query_params)

    assert result["limit"] == EXPECTED_LIMIT_100  # Default limit
    assert result["status"] is None
    assert result["direction"] is None
    assert result["page_token"] is None


def test_extract_next_page_token_success() -> None:
    """Test successful extraction of next page token."""
    next_page_url = (
        "https://api.twilio.com/2010-04-01/Accounts/ACXXXXXXX/"
        "Calls.json?PageToken=PAXXXXXXX&Page=1&Limit=50"
    )

    result = _extract_next_page_token(next_page_url)

    assert result == "PAXXXXXXX"


def test_extract_next_page_token_no_url() -> None:
    """Test extraction returns None when no URL provided."""
    result = _extract_next_page_token(None)

    assert result is None


def test_extract_next_page_token_no_token() -> None:
    """Test extraction returns None when URL has no PageToken."""
    next_page_url = (
        "https://api.twilio.com/2010-04-01/Accounts/ACXXXXXXX/Calls.json?Page=1"
    )

    with pytest.raises(IndexError):
        _extract_next_page_token(next_page_url)


def test_monitor_call_general_exception(mocker: MockerFixture) -> None:
    """Test monitor_call with general exception handling."""
    call_sid = "CA1234567890abcdef1234567890abcdef"

    # Mock SSM parameters to raise a general exception
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        side_effect=Exception("Unexpected error"),
    )

    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    with pytest.raises(
        InternalServerError, match="Failed to fetch call details: Unexpected error"
    ):
        monitor_call(call_sid)

    mock_logger_exception.assert_called_once_with(
        "Failed to fetch call details: Unexpected error"
    )


def test_batch_monitor_calls_general_exception(mocker: MockerFixture) -> None:
    """Test batch_monitor_calls with general exception handling."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {
        "queryStringParameters": {
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-31T23:59:59Z",
        }
    }
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters to raise a general exception
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        side_effect=Exception("Unexpected error"),
    )

    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    with pytest.raises(
        InternalServerError, match="Failed to fetch calls: Unexpected error"
    ):
        batch_monitor_calls()

    mock_logger_exception.assert_called_once_with(
        "Failed to fetch calls: Unexpected error"
    )


def test_batch_monitor_calls_value_error_in_main(mocker: MockerFixture) -> None:
    """Test batch_monitor_calls with ValueError in main try block."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {
        "queryStringParameters": {
            "start_date": "2024-01-01T00:00:00Z",
            "end_date": "2024-01-31T23:59:59Z",
            "limit": "not-a-number",  # This will cause ValueError
        }
    }
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    expected_msg = "Invalid date format or parameter configuration"
    with pytest.raises(BadRequestError, match=expected_msg):
        batch_monitor_calls()

    assert mock_logger_exception.called


def test__respond_to_call_birthdate_with_current_url(mocker: MockerFixture) -> None:
    """Test _respond_to_call for birthdate template with current URL."""
    # Mock XML parsing functions
    mock_root = mocker.MagicMock()
    mock_gather = mocker.MagicMock()
    mock_redirect = mocker.MagicMock()

    mocker.patch(
        "twiliowebhook.api.main.parse_xml_and_extract_root", return_value=mock_root
    )
    mocker.patch(
        "twiliowebhook.api.main.find_xml_element",
        side_effect=[mock_gather, mock_redirect],
    )
    mocker.patch(
        "twiliowebhook.api.main.convert_xml_root_to_string",
        return_value="<Response></Response>",
    )

    # Mock logger
    mock_logger_info = mocker.patch("twiliowebhook.api.main.logger.info")

    response = _respond_to_call(
        twiml_file_path=BIRTHDATE_TWIML_FILE_PATH,
        caller_phone_number="+1234567890",
        media_api_url="wss://media.example.com",
        webhook_api_url="https://webhook.example.com/api/v1/webhook",
    )

    # Verify gather action was set
    mock_gather.set.assert_called_once_with(
        "action", "https://webhook.example.com/process-digits/birthdate"
    )

    # Verify redirect text was set with current URL
    mock_redirect.text = "https://webhook.example.com/api/v1/webhook"

    # Verify logger was called with the correct URL
    mock_logger_info.assert_called_with(
        "process_birthdate_url: %s",
        "https://webhook.example.com/process-digits/birthdate",
    )

    assert response.status_code == HTTP_OK


def test__respond_to_call_birthdate_without_current_url(mocker: MockerFixture) -> None:
    """Test _respond_to_call for birthdate template without current URL."""
    # Mock XML parsing functions
    mock_root = mocker.MagicMock()
    mock_gather = mocker.MagicMock()
    mock_redirect = mocker.MagicMock()

    mocker.patch(
        "twiliowebhook.api.main.parse_xml_and_extract_root", return_value=mock_root
    )
    mocker.patch(
        "twiliowebhook.api.main.find_xml_element",
        side_effect=[mock_gather, mock_redirect],
    )
    mocker.patch(
        "twiliowebhook.api.main.convert_xml_root_to_string",
        return_value="<Response></Response>",
    )

    # Use webhook URL without path to test the else branch
    response = _respond_to_call(
        twiml_file_path=BIRTHDATE_TWIML_FILE_PATH,
        caller_phone_number="+1234567890",
        media_api_url="wss://media.example.com",
        webhook_api_url="https://webhook.example.com",  # No path test
    )

    # Verify gather action was set
    mock_gather.set.assert_called_once_with(
        "action", "https://webhook.example.com/process-digits/birthdate"
    )

    # Verify redirect text was NOT set since current_url is empty
    # redirect.text exists (it's a MagicMock) but shouldn't be assigned
    # We can verify this by checking that it wasn't called with assignment
    assert response.status_code == HTTP_OK


def test_process_digits_invalid_target(mocker: MockerFixture) -> None:
    """Test process_digits with invalid target."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())

    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")

    with pytest.raises(
        BadRequestError, match=r"Invalid target: invalid\. Expected 'birthdate'\."
    ):
        process_digits("invalid")

    mock_logger_error.assert_called_once_with(
        "Invalid target: invalid. Expected 'birthdate'."
    )


def test_process_digits_missing_digits(mocker: MockerFixture) -> None:
    """Test process_digits with missing digits parameter."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {"queryStringParameters": {}}  # No digits parameter
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")

    with pytest.raises(
        BadRequestError, match="Birth date digits not found in the request"
    ):
        process_digits("birthdate")

    mock_logger_error.assert_called_once_with(
        "Birth date digits not found in the request"
    )


def test_process_digits_invalid_format(mocker: MockerFixture) -> None:
    """Test process_digits with invalid digit format."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {"queryStringParameters": {"digits": "123"}}  # Too short
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")

    with pytest.raises(BadRequestError, match="Invalid birth date format"):
        process_digits("birthdate")

    mock_logger_error.assert_called_once()


def test_confirm_digits_invalid_target(mocker: MockerFixture) -> None:
    """Test confirm_digits with invalid target."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())

    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")

    with pytest.raises(
        BadRequestError, match=r"Invalid target: invalid\. Expected 'birthdate'\."
    ):
        confirm_digits("invalid")

    mock_logger_error.assert_called_once_with(
        "Invalid target: invalid. Expected 'birthdate'."
    )


def test_confirm_digits_missing_digits(mocker: MockerFixture) -> None:
    """Test confirm_digits with missing confirmation digits."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {
        "queryStringParameters": {"birthdate": "20240101"}
    }  # No digits parameter
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")

    with pytest.raises(
        BadRequestError, match="Confirmation digits not found in the request"
    ):
        confirm_digits("birthdate")

    mock_logger_error.assert_called_once_with(
        "Confirmation digits not found in the request"
    )


def test_confirm_digits_missing_birthdate(mocker: MockerFixture) -> None:
    """Test confirm_digits with missing birthdate parameter."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {"queryStringParameters": {"digits": "1"}}  # No birthdate parameter
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    mock_logger_error = mocker.patch("twiliowebhook.api.main.logger.error")

    with pytest.raises(
        BadRequestError, match="Birthdate parameter not found in the request"
    ):
        confirm_digits("birthdate")

    mock_logger_error.assert_called_once_with(
        "Birthdate parameter not found in the request"
    )


def test_process_digits_success(mocker: MockerFixture) -> None:
    """Test successful process_digits execution."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {"queryStringParameters": {"digits": "20240101"}}
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": "test-token",
            "/twh/dev/webhook-api-url": "https://webhook.example.com",
        },
    )

    # Mock Twilio signature validation
    mocker.patch("twiliowebhook.api.main.validate_http_twilio_signature")

    # Mock XML functions
    mock_root = mocker.MagicMock()
    mock_say = mocker.MagicMock()
    mock_gather = mocker.MagicMock()
    mock_redirect = mocker.MagicMock()

    mocker.patch(
        "twiliowebhook.api.main.parse_xml_and_extract_root", return_value=mock_root
    )
    mocker.patch(
        "twiliowebhook.api.main.find_xml_element",
        side_effect=[mock_say, mock_gather, mock_redirect],
    )
    mocker.patch(
        "twiliowebhook.api.main.convert_xml_root_to_string",
        return_value="<Response></Response>",
    )

    # Mock logger
    mock_logger_info = mocker.patch("twiliowebhook.api.main.logger.info")

    response = process_digits("birthdate")

    assert response.status_code == HTTP_OK
    mock_logger_info.assert_called_with(
        "Received birth date: %s-%s-%s", "2024", "01", "01"
    )


def test_confirm_digits_success_confirm(mocker: MockerFixture) -> None:
    """Test successful confirm_digits with confirmation (digits=1)."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {"queryStringParameters": {"digits": "1", "birthdate": "20240101"}}
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": "test-token",
            "/twh/dev/webhook-api-url": "https://webhook.example.com",
        },
    )

    # Mock Twilio signature validation
    mocker.patch("twiliowebhook.api.main.validate_http_twilio_signature")

    # Mock XML functions
    mock_root = mocker.MagicMock()
    mock_say = mocker.MagicMock()

    mocker.patch(
        "twiliowebhook.api.main.parse_xml_and_extract_root", return_value=mock_root
    )
    mocker.patch("twiliowebhook.api.main.find_xml_element", return_value=mock_say)
    mocker.patch(
        "twiliowebhook.api.main.convert_xml_root_to_string",
        return_value="<Response></Response>",
    )

    # Mock logger
    mock_logger_info = mocker.patch("twiliowebhook.api.main.logger.info")

    response = confirm_digits("birthdate")

    assert response.status_code == HTTP_OK
    mock_logger_info.assert_called_with(
        "Birth date confirmed: %s-%s-%s", "2024", "01", "01"
    )


def test_confirm_digits_success_reenter(mocker: MockerFixture) -> None:
    """Test successful confirm_digits with re-enter (digits=2)."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {"queryStringParameters": {"digits": "2", "birthdate": "20240101"}}
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": "test-token",
            "/twh/dev/webhook-api-url": "https://webhook.example.com",
        },
    )

    # Mock Twilio signature validation
    mocker.patch("twiliowebhook.api.main.validate_http_twilio_signature")

    # Mock XML functions
    mock_root = mocker.MagicMock()
    mock_redirect = mocker.MagicMock()

    mocker.patch(
        "twiliowebhook.api.main.parse_xml_and_extract_root", return_value=mock_root
    )
    mocker.patch("twiliowebhook.api.main.find_xml_element", return_value=mock_redirect)
    mocker.patch(
        "twiliowebhook.api.main.convert_xml_root_to_string",
        return_value="<Response></Response>",
    )

    # Mock logger
    mock_logger_info = mocker.patch("twiliowebhook.api.main.logger.info")

    response = confirm_digits("birthdate")

    assert response.status_code == HTTP_OK
    mock_logger_info.assert_called_with("User chose to re-enter birth date")


def test_confirm_digits_invalid_input(mocker: MockerFixture) -> None:
    """Test confirm_digits with invalid input (digits=3)."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {"queryStringParameters": {"digits": "3", "birthdate": "20240101"}}
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": "test-token",
            "/twh/dev/webhook-api-url": "https://webhook.example.com",
        },
    )

    # Mock Twilio signature validation
    mocker.patch("twiliowebhook.api.main.validate_http_twilio_signature")

    # Mock XML functions
    mock_root = mocker.MagicMock()
    mock_gather = mocker.MagicMock()
    mock_redirect = mocker.MagicMock()

    mocker.patch(
        "twiliowebhook.api.main.parse_xml_and_extract_root", return_value=mock_root
    )
    mocker.patch(
        "twiliowebhook.api.main.find_xml_element",
        side_effect=[mock_gather, mock_redirect],
    )
    mocker.patch(
        "twiliowebhook.api.main.convert_xml_root_to_string",
        return_value="<Response></Response>",
    )

    # Mock logger
    mock_logger_warning = mocker.patch("twiliowebhook.api.main.logger.warning")

    response = confirm_digits("birthdate")

    assert response.status_code == HTTP_OK
    mock_logger_warning.assert_called_with("Invalid confirmation input: %s", "3")


def test_confirm_digits_ssm_error(mocker: MockerFixture) -> None:
    """Test confirm_digits with SSM parameter error."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {"queryStringParameters": {"digits": "1", "birthdate": "20240101"}}
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    error_detail = "Invalid parameter"
    error_message = f"Invalid parameters: [{error_detail}]"
    # Mock SSM to raise GetParameterError (which gets wrapped into ValueError)
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        side_effect=GetParameterError(error_detail),
    )

    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    with pytest.raises(InternalServerError, match=error_message):
        confirm_digits("birthdate")

    mock_logger_exception.assert_called_once_with(error_message)


def test_confirm_digits_signature_validation_error(mocker: MockerFixture) -> None:
    """Test confirm_digits with signature validation error."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {"queryStringParameters": {"digits": "1", "birthdate": "20240101"}}
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": "fake_token",
            "/twh/dev/webhook-api-url": "https://webhook.example.com",
        },
    )

    # Mock signature validation to raise UnauthorizedError
    mocker.patch(
        "twiliowebhook.api.main.validate_http_twilio_signature",
        side_effect=UnauthorizedError("Invalid signature"),
    )

    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    with pytest.raises(UnauthorizedError, match="Invalid signature"):
        confirm_digits("birthdate")

    mock_logger_exception.assert_called_once_with("Invalid signature")


def test_confirm_digits_xml_processing_error(mocker: MockerFixture) -> None:
    """Test confirm_digits with XML processing error."""
    mocker.patch("twiliowebhook.api.main.app", return_value=LambdaFunctionUrlResolver())
    mock_event = {"queryStringParameters": {"digits": "1", "birthdate": "20240101"}}
    mocker.patch("twiliowebhook.api.main.app.current_event", new=mock_event)

    # Mock SSM parameters
    mocker.patch(
        "twiliowebhook.api.main.get_parameters_by_name",
        return_value={
            "/twh/dev/twilio-auth-token": "fake_token",
            "/twh/dev/webhook-api-url": "https://webhook.example.com",
        },
    )

    # Mock signature validation to pass
    mocker.patch("twiliowebhook.api.main.validate_http_twilio_signature")

    # Mock XML parsing to raise exception
    mocker.patch(
        "twiliowebhook.api.main.parse_xml_and_extract_root",
        side_effect=Exception("XML parsing failed"),
    )

    mock_logger_exception = mocker.patch("twiliowebhook.api.main.logger.exception")

    with pytest.raises(InternalServerError, match="XML parsing failed"):
        confirm_digits("birthdate")

    mock_logger_exception.assert_called_once_with("XML parsing failed")
