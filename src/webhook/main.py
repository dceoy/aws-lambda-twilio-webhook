#!/usr/bin/env python
"""AWS Lambda function handler for incoming webhook from Twilio."""

import json
import os
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qsl

import boto3
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
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Connect, VoiceResponse

logger = Logger()
tracer = Tracer()
app = LambdaFunctionUrlResolver()


@app.get("/")
@tracer.capture_method
def index_page() -> Response[str]:
    """Index page for the Lambda function.

    Returns:
        Response[str]: A JSON response indicating the function is running.

    """
    return Response(
        status_code=HTTPStatus.OK,  # 200
        content_type=content_types.APPLICATION_JSON,  # application/json
        body=json.dumps({"message": "The function is running!"}),
    )


@app.post("/incoming-call")
@tracer.capture_method
def handle_incoming_call() -> Response[str]:
    """Handle incoming call and return TwiML response to connect to Media Stream.

    Returns:
        Response[str]: TwiML response to connect to Media Stream.

    Raises:
        InternalServerError: If the parameters are invalid.
        BadRequestError: If the request signature is missing.
        UnauthorizedError: If the request signature is invalid.

    """
    system_name = os.environ["SYSTEM_NAME"]
    env_type = os.environ["ENV_TYPE"]
    parameter_names = {
        k: f"/{system_name}/{env_type}/{k}"
        for k in ["twilio-auth-token", "media-api-url"]
    }
    try:
        parameters = _retrieve_ssm_parameters(*parameter_names.values())
        _validate_twilio_signature(
            token=parameters[parameter_names["twilio-auth-token"]],
            event=app.current_event,
        )
    except (BadRequestError, InternalServerError, UnauthorizedError) as e:
        logger.exception(e.msg)
        raise
    else:
        return _respond_to_call(
            media_api_url=parameters[parameter_names["media-api-url"]]
        )


def _retrieve_ssm_parameters(*names: str) -> dict[str, str]:
    """Retrieve parameters from AWS Systems Manager Parameter Store.

    Args:
        *names (str): Variable length argument list of parameter names.

    Returns:
        dict[str, str]: A dictionary containing parameter names and values.

    Raises:
        InternalServerError: If the parameters are invalid.

    """
    response = boto3.client("ssm").get_parameters(Names=names, WithDecryption=True)
    if response.get("InvalidParameters"):
        error_message = "Invalid parameters: {}".format(response["InvalidParameters"])
        raise InternalServerError(error_message)
    else:
        logger.info("Parameters are retrieved from Parameter Store: %s", names)
        return {p["Name"]: p["Value"] for p in response["Parameters"]}


def _respond_to_call(media_api_url: str) -> Response[str]:
    """Respond to incoming call with TwiML response.

    Args:
        media_api_url (str): Media API URL to connect to.

    Returns:
        Response[str]: TwiML response to connect to Media Stream.

    """
    response = VoiceResponse()
    # <Say> punctuation to improve text-to-speech flow
    response.say(
        "Please wait while we connect your call to the AI voice assistant,"
        " powered by Twilio and the OpenAI Realtime API"
    )
    response.pause(length=1)
    response.say("OK. you can start talking!")
    connect = Connect()
    logger.info("Connecting to Media Stream: %s", media_api_url)
    connect.stream(url=media_api_url)
    response.append(connect)
    body = str(response)
    logger.info("body: %s", body)
    return Response(
        status_code=HTTPStatus.OK,
        content_type="application/xml",
        body=body,
    )


def _validate_twilio_signature(token: str, event: LambdaFunctionUrlEvent) -> None:
    """Validate incoming Twilio request signature.

    Args:
        token (str): Twilio auth token.
        event (LambdaFunctionUrlEvent): The event data passed by AWS Lambda.

    Raises:
        BadRequestError: If the request signature is missing.
        UnauthorizedError: If the request signature is invalid.

    """
    validator = RequestValidator(token)
    uri = f"https://{event.request_context.domain_name}{event.path}"
    logger.info("uri: %s", uri)
    decoded_body = event.decoded_body
    logger.info("decoded_body: %s", decoded_body)
    params = dict(parse_qsl(decoded_body, keep_blank_values=True))
    logger.info("params: %s", params)
    signature = event.headers.get("X-Twilio-Signature")
    if not signature:
        error_message = "Missing X-Twilio-Signature header"
        raise BadRequestError(error_message)
    elif not validator.validate(uri=uri, params=params, signature=signature):
        error_message = "Invalid Twilio request signature"
        raise UnauthorizedError(error_message)
    else:
        logger.info("Twilio request signature is valid")


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
