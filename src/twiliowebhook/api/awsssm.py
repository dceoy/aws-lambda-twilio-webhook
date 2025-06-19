"""AWS Systems Manager Parameter Store module."""

import boto3
from aws_lambda_powertools import Logger

from .constants import AWS_SSM_SERVICE, ERROR_INVALID_PARAMETERS

logger = Logger()


def retrieve_ssm_parameters(*names: str) -> dict[str, str]:
    """Retrieve parameters from AWS Systems Manager Parameter Store.

    Args:
        *names (str): Variable length argument list of parameter names.

    Returns:
        dict[str, str]: A dictionary containing parameter names and values.

    Raises:
        ValueError: If any of the parameter names are invalid.
    """
    response = boto3.client(AWS_SSM_SERVICE).get_parameters(
        Names=names, WithDecryption=True
    )
    if response.get("InvalidParameters"):
        error_message = ERROR_INVALID_PARAMETERS.format(response["InvalidParameters"])
        raise ValueError(error_message)
    logger.info("Parameters are retrieved from Parameter Store: %s", names)
    return {p["Name"]: p["Value"] for p in response["Parameters"]}
