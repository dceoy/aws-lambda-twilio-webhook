"""Module for manipulating XML files."""

from xml.etree.ElementTree import Element  # noqa: S405

from aws_lambda_powertools import Logger
from defusedxml import ElementTree


def parse_xml_and_extract_root(xml_file_path: str) -> Element:
    """Parse a XML file and extract the root element.

    Args:
        xml_file_path (str): The path to the XML file.

    Returns:
        ElementTree.Element: The root element of the parsed XML file.

    Raises:
        ValueError: If the XML file cannot be parsed or is empty.

    """
    root = ElementTree.parse(xml_file_path).getroot()
    if root is None:
        error_message = f"Failed to get root element from XML file: {xml_file_path}"
        raise ValueError(error_message)
    return root


def find_xml_element(root: Element, namespaces: str) -> Element:
    """Find an element in the XML tree by tag name.

    Args:
        root (Element): The root element of the XML tree.
        namespaces (str): The tag name of the element to find.

    Returns:
        Element: The found element, or None if not found.

    Raises:
        ValueError: If the element with the specified tag name is not found.

    """
    element = root.find(namespaces)
    if element is None:
        error_message = f"Element with tag '{namespaces}' not found in XML tree."
        raise ValueError(error_message)
    return element


def convert_xml_root_to_string(root: Element, logger: Logger | None = None) -> str:
    """Convert the XML root element to a string.

    Args:
        root (Element): The root element of the XML tree.
        logger (Logger | None): Optional logger for logging the XML string.

    Returns:
        str: The XML string representation of the root element.

    """
    xml_string = ElementTree.tostring(root, encoding="unicode")
    if logger is not None:
        logger.info("XML string: %s", xml_string)
    return xml_string
