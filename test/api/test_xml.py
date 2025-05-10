"""Tests for twiliowebhook.api.xml module."""

from typing import Any
from xml.etree.ElementTree import Element, ParseError

import pytest
from aws_lambda_powertools import Logger
from pytest_mock import MockerFixture

from twiliowebhook.api.xml import (
    convert_xml_root_to_string,
    find_xml_element,
    parse_xml_and_extract_root,
)

_SAMPLE_XML_STRING = "<root><child>data</child></root>"
_SAMPLE_ROOT_TAG = "root"
_SAMPLE_CHILD_TAG = "child"
_SAMPLE_NON_EXISTENT_TAG = "nonexistent"
_DUMMY_FILE_PATH = "dummy/path/to/file.xml"


@pytest.fixture
def mock_element(mocker: MockerFixture) -> Any:  # Return type is Any or can be omitted
    el = mocker.MagicMock(spec=Element)
    el.tag = "mock_tag"
    return el


@pytest.fixture
def mock_root_element(mocker: MockerFixture, mock_element: Any) -> Any:
    mock_element.tag = _SAMPLE_ROOT_TAG
    return mock_element


@pytest.fixture
def mock_child_element(mocker: MockerFixture) -> Any:
    child_el = mocker.MagicMock(spec=Element)
    child_el.tag = _SAMPLE_CHILD_TAG
    return child_el


def test_parse_xml_and_extract_root_success(
    mocker: MockerFixture, mock_root_element: Any
):
    mock_parsed_xml = mocker.MagicMock()
    mock_parsed_xml.getroot.return_value = mock_root_element
    mock_defused_parse = mocker.patch(
        "twiliowebhook.api.xml.ElementTree.parse", return_value=mock_parsed_xml
    )
    root = parse_xml_and_extract_root(_DUMMY_FILE_PATH)
    mock_defused_parse.assert_called_once_with(_DUMMY_FILE_PATH)
    mock_parsed_xml.getroot.assert_called_once()
    assert root == mock_root_element
    assert root.tag == _SAMPLE_ROOT_TAG


def test_parse_xml_and_extract_root_no_root_element(mocker: MockerFixture):
    mock_parsed_xml = mocker.MagicMock()
    mock_parsed_xml.getroot.return_value = None
    mock_defused_parse = mocker.patch(
        "twiliowebhook.api.xml.ElementTree.parse", return_value=mock_parsed_xml
    )
    expected_error_message = (
        f"Failed to get root element from XML file: {_DUMMY_FILE_PATH}"
    )
    with pytest.raises(ValueError, match=expected_error_message):
        parse_xml_and_extract_root(_DUMMY_FILE_PATH)
    mock_defused_parse.assert_called_once_with(_DUMMY_FILE_PATH)
    mock_parsed_xml.getroot.assert_called_once()


def test_parse_xml_and_extract_root_parse_error(mocker: MockerFixture):
    mock_defused_parse = mocker.patch(
        "twiliowebhook.api.xml.ElementTree.parse",
        side_effect=ParseError("mocked XML parse error"),
    )
    with pytest.raises(ParseError, match="mocked XML parse error"):
        parse_xml_and_extract_root(_DUMMY_FILE_PATH)
    mock_defused_parse.assert_called_once_with(_DUMMY_FILE_PATH)


def test_find_xml_element_success(mock_root_element: Any, mock_child_element: Any):
    mock_root_element.find.return_value = mock_child_element
    found_element = find_xml_element(mock_root_element, _SAMPLE_CHILD_TAG)
    mock_root_element.find.assert_called_once_with(_SAMPLE_CHILD_TAG)
    assert found_element == mock_child_element
    assert found_element.tag == _SAMPLE_CHILD_TAG


def test_find_xml_element_not_found(mock_root_element: Any):
    mock_root_element.find.return_value = None
    expected_error_message = (
        f"Element with tag '{_SAMPLE_NON_EXISTENT_TAG}' not found in XML tree."
    )
    with pytest.raises(ValueError, match=expected_error_message):
        find_xml_element(mock_root_element, _SAMPLE_NON_EXISTENT_TAG)
    mock_root_element.find.assert_called_once_with(_SAMPLE_NON_EXISTENT_TAG)


def test_convert_xml_root_to_string_no_logger(
    mocker: MockerFixture, mock_root_element: Any
):
    mock_defused_tostring = mocker.patch(
        "twiliowebhook.api.xml.ElementTree.tostring",
        return_value=_SAMPLE_XML_STRING,
    )
    xml_string = convert_xml_root_to_string(root=mock_root_element, logger=None)
    mock_defused_tostring.assert_called_once_with(mock_root_element, encoding="unicode")
    assert xml_string == _SAMPLE_XML_STRING


def test_convert_xml_root_to_string_with_logger(
    mocker: MockerFixture,
    mock_root_element: Any,
):
    mock_defused_tostring = mocker.patch(
        "twiliowebhook.api.xml.ElementTree.tostring",
        return_value=_SAMPLE_XML_STRING,
    )
    mock_logger = mocker.MagicMock(spec=Logger)
    xml_string = convert_xml_root_to_string(root=mock_root_element, logger=mock_logger)
    mock_defused_tostring.assert_called_once_with(mock_root_element, encoding="unicode")
    assert xml_string == _SAMPLE_XML_STRING
    mock_logger.info.assert_called_once_with("XML string: %s", _SAMPLE_XML_STRING)
