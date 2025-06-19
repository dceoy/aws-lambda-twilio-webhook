"""Module for Twilio webhook signature validation."""

from urllib.parse import parse_qsl

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler.exceptions import (
    BadRequestError,
    UnauthorizedError,
)
from aws_lambda_powertools.utilities.data_classes import LambdaFunctionUrlEvent
from twilio.request_validator import RequestValidator

from .constants import (
    ERROR_INVALID_TWILIO_SIGNATURE,
    ERROR_MISSING_TWILIO_SIGNATURE,
    HTTPS_SCHEME,
    TWILIO_SIGNATURE_HEADER,
    URL_QUERY_SEPARATOR,
)

logger = Logger()


def validate_http_twilio_signature(token: str, event: LambdaFunctionUrlEvent) -> None:
    """Validate Twilio signature for HTTP request.

    Args:
        token (str): Twilio auth token.
        event (LambdaFunctionUrlEvent): The event data passed by AWS Lambda.

    Raises:
        BadRequestError: If the request signature is missing.
        UnauthorizedError: If the request signature is invalid.

    """
    logger.info("Validating Twilio signature")
    validator = RequestValidator(token)
    query_parameters = event.get("queryStringParameters")
    query_string = (
        f"{URL_QUERY_SEPARATOR}{
            '&'.join([f'{k}={v}' for k, v in query_parameters.items()])
        }"
        if query_parameters
        else ""
    )
    uri = f"{HTTPS_SCHEME}{event.request_context.domain_name}{event.path}{query_string}"
    logger.info("uri: %s", uri)
    logger.info("event.decoded_body: %s", event.decoded_body)
    params = dict(parse_qsl(event.decoded_body, keep_blank_values=True))
    logger.info("params: %s", params)
    signature = event.headers.get(TWILIO_SIGNATURE_HEADER)
    if not signature:
        error_message = ERROR_MISSING_TWILIO_SIGNATURE
        raise BadRequestError(error_message)
    if not validator.validate(uri=uri, params=params, signature=signature):
        error_message = ERROR_INVALID_TWILIO_SIGNATURE
        raise UnauthorizedError(error_message)
    logger.info("Twilio request signature is valid")
