"""AWS Lambda function handler for incoming webhook from Twilio."""

import json
from http import HTTPStatus
from typing import Any
from urllib.parse import unquote, urlparse
from xml.etree.ElementTree import Element  # noqa: S405

import phonenumbers
from aws_lambda_powertools import Logger, Tracer
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
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.utilities.data_classes import LambdaFunctionUrlEvent
from aws_lambda_powertools.utilities.typing import LambdaContext

from .awsssm import retrieve_ssm_parameters
from .constants import (
    BIRTHDATE_DIGIT_LENGTH,
    BIRTHDATE_TWIML_FILE_PATH,
    CONNECT_TWIML_FILE_PATH,
    CONTENT_TYPE_XML,
    DIAL_TWIML_FILE_PATH,
    DTMF_OPERATOR_TRANSFER,
    DTMF_VOICE_ASSISTANT,
    ENV_TYPE,
    ERROR_BIRTHDATE_DIGITS_NOT_FOUND,
    ERROR_CALL_NUMBER_NOT_FOUND,
    ERROR_DIGITS_NOT_FOUND,
    FORM_PARAM_FROM,
    GATHER_TWIML_FILE_PATH,
    HANGUP_TWIML_FILE_PATH,
    HTTPS_SCHEME,
    PROCESS_BIRTHDATE_PATH,
    SSM_MEDIA_API_URL,
    SSM_OPERATOR_PHONE_NUMBER,
    SSM_TWILIO_AUTH_TOKEN,
    SSM_WEBHOOK_API_URL,
    SYSTEM_NAME,
    TRANSFER_CALL_ENDPOINT,
    TWIML_DIR,
)
from .twilio import validate_http_twilio_signature
from .xml import (
    convert_xml_root_to_string,
    find_xml_element,
    parse_xml_and_extract_root,
)

logger = Logger()
tracer = Tracer()
app = LambdaFunctionUrlResolver()


@app.get("/health")
@tracer.capture_method
def check_health() -> Response[str]:
    """Check the health of the API.

    Returns:
        Response[str]: A JSON response indicating the function is running.

    """
    return Response(
        status_code=HTTPStatus.OK,  # 200
        content_type=content_types.APPLICATION_JSON,  # application/json
        body=json.dumps({"message": "The function is running!"}),
    )


@app.post("/transfer-call")
@tracer.capture_method
def transfer_call(country_code: str = "US") -> Response[str]:
    """Handle call transfer request and return TwiML response.

    Args:
        country_code (str): The country code for the phone number.

    Returns:
        Response[str]: TwiML response to connect to Media Stream.

    Raises:
        InternalServerError: If the parameters are invalid.
        BadRequestError: If the request signature is missing.
        UnauthorizedError: If the request signature is invalid.

    """
    digits = app.current_event["queryStringParameters"].get("digits")
    if not digits:
        error_message = ERROR_DIGITS_NOT_FOUND
        logger.error(error_message)
        raise BadRequestError(error_message)
    parameter_names = {
        k: f"/{SYSTEM_NAME}/{ENV_TYPE}/{k}"
        for k in [
            SSM_TWILIO_AUTH_TOKEN,
            SSM_MEDIA_API_URL,
            SSM_OPERATOR_PHONE_NUMBER,
        ]
    }
    try:
        parameters = retrieve_ssm_parameters(*parameter_names.values())
        validate_http_twilio_signature(
            token=parameters[parameter_names[SSM_TWILIO_AUTH_TOKEN]],
            event=app.current_event,
        )
        logger.info("Call transfer")
        if digits == DTMF_VOICE_ASSISTANT:
            root = parse_xml_and_extract_root(xml_file_path=CONNECT_TWIML_FILE_PATH)
            caller_phone_number = _fetch_caller_phone_number_from_request(
                event=app.current_event
            )
            stream = find_xml_element(root=root, namespaces="./Connect/Stream")
            stream.set("url", parameters[parameter_names[SSM_MEDIA_API_URL]])
            parameter_from = find_xml_element(
                root=stream, namespaces=f"./Parameter[@name='{FORM_PARAM_FROM}']"
            )
            parameter_from.set("value", caller_phone_number)
        elif digits == DTMF_OPERATOR_TRANSFER:
            root = parse_xml_and_extract_root(xml_file_path=DIAL_TWIML_FILE_PATH)
            dial = find_xml_element(root=root, namespaces="./Dial")
            dial.text = phonenumbers.format_number(
                phonenumbers.parse(
                    parameters[parameter_names[SSM_OPERATOR_PHONE_NUMBER]],
                    country_code,
                ),
                phonenumbers.PhoneNumberFormat.E164,
            )
        else:
            root = parse_xml_and_extract_root(xml_file_path=HANGUP_TWIML_FILE_PATH)
        twiml = convert_xml_root_to_string(root=root, logger=logger)
    except (BadRequestError, UnauthorizedError) as e:
        logger.exception(e.msg)
        raise
    except Exception as e:
        error_message = str(e)
        logger.exception(error_message)
        raise InternalServerError(error_message) from e
    else:
        return Response(
            status_code=HTTPStatus.OK,
            content_type=CONTENT_TYPE_XML,
            body=twiml,
        )


@app.post("/incoming-call/<twiml_file_stem>")
@tracer.capture_method
def handle_incoming_call(twiml_file_stem: str) -> Response[str]:
    """Handle incoming call and return TwiML response.

    Args:
        twiml_file_stem (str): The stem of the TwiML file to use for the response.

    Returns:
        Response[str]: TwiML response to connect to Media Stream.

    Raises:
        InternalServerError: If the parameters are invalid.
        BadRequestError: If the request signature is missing.
        UnauthorizedError: If the request signature is invalid.

    """
    twiml_file = TWIML_DIR / f"{twiml_file_stem}.twiml.xml"
    if not twiml_file.exists():
        error_message = f"Invalid TwiML file: {twiml_file}"
        logger.error(error_message)
        raise BadRequestError(error_message)
    caller_phone_number = _fetch_caller_phone_number_from_request(
        event=app.current_event
    )
    parameter_names = {
        k: f"/{SYSTEM_NAME}/{ENV_TYPE}/{k}"
        for k in [
            SSM_TWILIO_AUTH_TOKEN,
            SSM_MEDIA_API_URL,
            SSM_WEBHOOK_API_URL,
        ]
    }
    try:
        parameters = retrieve_ssm_parameters(*parameter_names.values())
        validate_http_twilio_signature(
            token=parameters[parameter_names[SSM_TWILIO_AUTH_TOKEN]],
            event=app.current_event,
        )
    except (BadRequestError, UnauthorizedError) as e:
        logger.exception(e.msg)
        raise
    except Exception as e:
        error_message = str(e)
        logger.exception(error_message)
        raise InternalServerError(error_message) from e
    else:
        return _respond_to_call(
            twiml_file_path=str(twiml_file),
            caller_phone_number=caller_phone_number,
            media_api_url=parameters[parameter_names[SSM_MEDIA_API_URL]],
            webhook_api_url=parameters[parameter_names[SSM_WEBHOOK_API_URL]],
        )


def _respond_to_call(
    twiml_file_path: str,
    caller_phone_number: str,
    media_api_url: str,
    webhook_api_url: str,
) -> Response[str]:
    """Respond to incoming call with TwiML response.

    Args:
        twiml_file_path (str): Path to the TwiML template file.
        caller_phone_number (str): Phone number of the caller.
        media_api_url (str): Media API URL to connect to.
        webhook_api_url (str): Webhook API URL to connect to.

    Returns:
        Response[str]: TwiML response to connect to Media Stream.

    """
    logger.info("Responding to call")
    root = parse_xml_and_extract_root(xml_file_path=twiml_file_path)
    if twiml_file_path == CONNECT_TWIML_FILE_PATH:
        stream = find_xml_element(root=root, namespaces="./Connect/Stream")
        stream.set("url", media_api_url)
        parameter_from = find_xml_element(
            root=root,
            namespaces=f"./Connect/Stream/Parameter[@name='{FORM_PARAM_FROM}']",
        )
        parameter_from.set("value", caller_phone_number)
    elif twiml_file_path == GATHER_TWIML_FILE_PATH:
        gather = find_xml_element(root=root, namespaces="./Gather")
        webhook_api_fqdn = urlparse(webhook_api_url).netloc
        transfer_api_url = f"{HTTPS_SCHEME}{webhook_api_fqdn}{TRANSFER_CALL_ENDPOINT}"
        logger.info("transfer_api_url: %s", transfer_api_url)
        gather.set("action", transfer_api_url)
    elif twiml_file_path == BIRTHDATE_TWIML_FILE_PATH:
        gather = find_xml_element(root=root, namespaces="./Gather")
        webhook_api_fqdn = urlparse(webhook_api_url).netloc
        process_birthdate_url = (
            f"{HTTPS_SCHEME}{webhook_api_fqdn}{PROCESS_BIRTHDATE_PATH}"
        )
        logger.info("process_birthdate_url: %s", process_birthdate_url)
        gather.set("action", process_birthdate_url)
        # Set the redirect URL for retry
        redirect = find_xml_element(root=root, namespaces="./Redirect")
        current_url = urlparse(webhook_api_url).path
        if current_url:
            redirect.text = f"{HTTPS_SCHEME}{webhook_api_fqdn}{current_url}"
    return Response(
        status_code=HTTPStatus.OK,
        content_type="application/xml",
        body=convert_xml_root_to_string(root=root, logger=logger),
    )


def _fetch_caller_phone_number_from_request(event: LambdaFunctionUrlEvent) -> str:
    """Fetch the caller phone number from the request body.

    Args:
        event (LambdaFunctionUrlEvent): The event data passed by AWS Lambda.

    Returns:
        str: The caller phone number.

    Raises:
        BadRequestError: If the call number is not found in the request body.

    """
    caller_phone_number: str | None = None
    if event.decoded_body:
        for kv in event.decoded_body.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                if unquote(k) == FORM_PARAM_FROM:
                    caller_phone_number = unquote(v)
                    break
    logger.info("caller_phone_number: %s", caller_phone_number)
    if not caller_phone_number:
        error_message = ERROR_CALL_NUMBER_NOT_FOUND
        raise BadRequestError(error_message)
    return caller_phone_number


@logger.inject_lambda_context(
    correlation_id_path=correlation_paths.LAMBDA_FUNCTION_URL,
    log_event=True,
)
@tracer.capture_lambda_handler
def lambda_handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    """AWS Lambda function handler.

    This function uses LambdaFunctionUrlResolver to handle incoming HTTP events
    and route requests to the appropriate endpoints.

    Args:
        event (dict[str, Any]): The event data passed by AWS Lambda.
        context (LambdaContext): The runtime information provided by AWS Lambda.

    Returns:
        dict[str, Any]: A dictionary representing the HTTP response.

    """
    logger.info("Event received")
    return app.resolve(event=event, context=context)


@app.post("/process-birthdate")
@tracer.capture_method
def process_birthdate() -> Response[str]:
    """Process birth date input and return TwiML response.

    Returns:
        Response[str]: TwiML response after processing birth date.

    Raises:
        BadRequestError: If the birth date is missing or invalid.
        UnauthorizedError: If the request signature is invalid.
        InternalServerError: If there's an error processing the request.

    """
    digits = app.current_event["queryStringParameters"].get("digits")
    if not digits:
        error_message = ERROR_BIRTHDATE_DIGITS_NOT_FOUND
        logger.error(error_message)
        raise BadRequestError(error_message)

    if len(digits) != BIRTHDATE_DIGIT_LENGTH or not digits.isdigit():
        error_message = (
            f"Invalid birth date format: {digits}. "
            f"Expected YYYYMMDD ({BIRTHDATE_DIGIT_LENGTH} digits)."
        )
        logger.error(error_message)
        raise BadRequestError(error_message)

    parameter_names = {
        k: f"/{SYSTEM_NAME}/{ENV_TYPE}/{k}" for k in [SSM_TWILIO_AUTH_TOKEN]
    }

    try:
        parameters = retrieve_ssm_parameters(*parameter_names.values())
        validate_http_twilio_signature(
            token=parameters[parameter_names[SSM_TWILIO_AUTH_TOKEN]],
            event=app.current_event,
        )

        year = digits[:4]
        month = digits[4:6]
        day = digits[6:8]
        logger.info("Received birth date: %s-%s-%s", year, month, day)

        # Create a simple confirmation response
        root = parse_xml_and_extract_root(xml_file_path=HANGUP_TWIML_FILE_PATH)
        # Add a Say element before Hangup
        say = Element("Say", attrib={"language": "en-US", "voice": "Polly.Joanna"})
        say.text = (
            f"Thank you. We have recorded your birth date as "
            f"{month} {day}, {year}. Goodbye!"
        )
        root.insert(0, say)

        twiml = convert_xml_root_to_string(root=root, logger=logger)
    except (BadRequestError, UnauthorizedError) as e:
        logger.exception(e.msg)
        raise
    except Exception as e:
        error_message = str(e)
        logger.exception(error_message)
        raise InternalServerError(error_message) from e
    else:
        return Response(
            status_code=HTTPStatus.OK,
            content_type=CONTENT_TYPE_XML,
            body=twiml,
        )
