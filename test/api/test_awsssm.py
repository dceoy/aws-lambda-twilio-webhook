"""Tests for twiliowebhook.api.awsssm module."""

import re

import boto3
import pytest
from moto import mock_aws
from pytest_mock import MockFixture

from twiliowebhook.api.awsssm import retrieve_ssm_parameters


@mock_aws
def test_retrieve_ssm_parameters(mocker: MockFixture) -> None:
    test_parameters: dict[str, str] = {
        "/test/mock/twilio-auth-token": "test-token",
        "/test/mock/media-api-url": "wss://api.example.com",
    }
    ssm = boto3.client("ssm", region_name="us-west-2")
    mocker.patch("twiliowebhook.api.awsssm.boto3.client", return_value=ssm)
    for k, v in test_parameters.items():
        ssm.put_parameter(
            Name=k, Value=v, Type=("SecureString" if "auth" in k else "String")
        )
    mocker.patch(
        "twiliowebhook.api.awsssm.boto3.client.get_parameters",
        return_value=ssm.get_parameters(
            Names=list(test_parameters.keys()),
            WithDecryption=True,
        ),
    )
    params: dict[str, str] = retrieve_ssm_parameters(*test_parameters.keys())
    assert params == {
        "/test/mock/twilio-auth-token": "test-token",
        "/test/mock/media-api-url": "wss://api.example.com",
    }


@mock_aws
def test_retrieve_ssm_parameters_invalid(mocker: MockFixture) -> None:
    invalid_parameter_name: str = "/invalid-parameter"
    ssm = boto3.client("ssm", region_name="us-west-2")
    mocker.patch("twiliowebhook.api.awsssm.boto3.client", return_value=ssm)
    mocker.patch(
        "twiliowebhook.api.awsssm.boto3.client.get_parameters",
        return_value=ssm.get_parameters(
            Names=[invalid_parameter_name],
            WithDecryption=True,
        ),
    )
    error_message: str = f"Invalid parameters: {[invalid_parameter_name]}"
    with pytest.raises(ValueError, match=re.escape(error_message)):
        retrieve_ssm_parameters(invalid_parameter_name)
