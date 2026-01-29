"""Utility functions for file I/O and common operations."""

import json
import logging
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar('T', bound=BaseModel)
logger = logging.getLogger('qpfl.utils')


def load_json(
    path: Path | str,
    schema: type[T] | None = None,
) -> Any | T:
    """
    Load JSON file with optional schema validation.

    Args:
        path: Path to JSON file (str or Path object)
        schema: Optional Pydantic model to validate against

    Returns:
        Parsed JSON (validated if schema provided)

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If JSON is malformed
        ValidationError: If schema validation fails

    Example:
        # Without validation:
        data = load_json('data/rosters.json')

        # With validation:
        from qpfl.schemas import RostersFile
        rosters = load_json('data/rosters.json', schema=RostersFile)
    """
    path = Path(path)

    logger.debug(f'Loading JSON from: {path}')

    if not path.exists():
        logger.error(f'File not found: {path}')
        raise FileNotFoundError(f'File not found: {path}')

    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        logger.debug(f'Successfully loaded JSON from: {path}')
    except json.JSONDecodeError as e:
        logger.error(f'Invalid JSON in {path}: {e.msg} at position {e.pos}')
        raise json.JSONDecodeError(f'Invalid JSON in {path}: {e.msg}', e.doc, e.pos) from e
    except Exception as e:
        logger.error(f'Unexpected error loading {path}: {e}')
        raise

    if schema:
        try:
            validated = schema(**data) if isinstance(data, dict) else schema(data)  # type: ignore[call-arg]
            logger.debug(f'Schema validation passed for: {path}')
            return validated
        except ValidationError as e:
            logger.error(f'Schema validation failed for {path}: {e}')
            raise ValueError(f'Schema validation failed for {path}:\n{e}') from e

    return data


def save_json(
    path: Path | str,
    data: Any,
    indent: int = 2,
    create_dirs: bool = True,
) -> None:
    """
    Save data as JSON file.

    Args:
        path: Path to write to (str or Path object)
        data: Data to serialize (must be JSON-serializable or Pydantic model)
        indent: Indentation level (default: 2 spaces)
        create_dirs: Create parent directories if they don't exist (default: True)

    Raises:
        TypeError: If data is not JSON-serializable
        OSError: If file cannot be written

    Example:
        save_json('data/output.json', {'key': 'value'})
    """
    path = Path(path)

    logger.debug(f'Saving JSON to: {path}')

    if create_dirs:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f'Failed to create directory {path.parent}: {e}')
            raise

    # Handle Pydantic models
    json_data = data.model_dump() if isinstance(data, BaseModel) else data

    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=indent, ensure_ascii=False)
        logger.debug(f'Successfully saved JSON to: {path}')
    except TypeError as e:
        logger.error(f'Data is not JSON-serializable: {e}')
        raise TypeError(f'Data is not JSON-serializable: {e}') from e
    except OSError as e:
        logger.error(f'Failed to write file {path}: {e}')
        raise


def load_json_safe(
    path: Path | str,
    default: Any = None,
    schema: type[T] | None = None,
) -> Any | T:
    """
    Load JSON file with safe fallback to default value.

    Like load_json, but returns default value instead of raising
    exceptions for missing or invalid files.

    Args:
        path: Path to JSON file
        default: Value to return if file missing or invalid (default: None)
        schema: Optional Pydantic model to validate against

    Returns:
        Parsed JSON, validated data, or default value

    Example:
        # Returns empty dict if file doesn't exist
        data = load_json_safe('data/optional.json', default={})
    """
    try:
        return load_json(path, schema=schema)
    except (FileNotFoundError, json.JSONDecodeError, ValidationError):
        return default


def validate_json_file(
    path: Path | str,
    schema: type[T],
) -> tuple[bool, str | None]:
    """
    Validate a JSON file against a schema without loading the data.

    Args:
        path: Path to JSON file
        schema: Pydantic model to validate against

    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if valid, False otherwise
        - error_message: None if valid, error description if invalid

    Example:
        from qpfl.schemas import RostersFile
        is_valid, error = validate_json_file('data/rosters.json', RostersFile)
        if not is_valid:
            print(f"Validation failed: {error}")
    """
    try:
        load_json(path, schema=schema)
        return True, None
    except FileNotFoundError:
        return False, f'File not found: {path}'
    except json.JSONDecodeError as e:
        return False, f'Invalid JSON: {e.msg} at position {e.pos}'
    except ValidationError as e:
        return False, f'Schema validation failed:\n{e}'
    except Exception as e:
        return False, f'Unexpected error: {e}'
