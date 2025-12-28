"""
Common error handling and file I/O utilities for extraction scripts.

This module provides reusable functions to reduce code duplication across
extraction scripts for error handling, JSON/YAML file operations, and logging.
"""

import json
import traceback
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, TypeVar, Callable
from functools import wraps
import asyncio

T = TypeVar('T')


# ============================================================================
# ERROR HANDLING DECORATORS
# ============================================================================


def handle_exceptions(
    council_name: Optional[str] = None,
    return_value: Any = None,
    print_traceback: bool = False,
):
    """
    Decorator to handle exceptions in async functions.

    Args:
        council_name: Name of council being processed (for error messages)
        return_value: Value to return on error (default: None)
        print_traceback: Whether to print full traceback on error

    Usage:
        @handle_exceptions(council_name="MyCouncil", print_traceback=True)
        async def process_council(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                name = council_name or kwargs.get('council_name', 'Unknown')
                print(f"❌ {name}: {str(e)}")
                if print_traceback:
                    traceback.print_exc()
                return return_value

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                name = council_name or kwargs.get('council_name', 'Unknown')
                print(f"❌ {name}: {str(e)}")
                if print_traceback:
                    traceback.print_exc()
                return return_value

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def safe_execute(
    func: Callable[[], T],
    error_message: str = "Error occurred",
    return_on_error: T = None,
    print_traceback: bool = False,
) -> T:
    """
    Safely execute a function and handle any exceptions.

    Args:
        func: Function to execute
        error_message: Message to print on error
        return_on_error: Value to return if error occurs
        print_traceback: Whether to print full traceback

    Returns:
        Function result or return_on_error if exception occurs

    Usage:
        data = safe_execute(
            lambda: json.loads(response_text),
            error_message="Failed to parse JSON",
            return_on_error={},
            print_traceback=True
        )
    """
    try:
        return func()
    except Exception as e:
        print(f"❌ {error_message}: {str(e)}")
        if print_traceback:
            traceback.print_exc()
        return return_on_error


# ============================================================================
# FILE I/O UTILITIES
# ============================================================================


def read_json(file_path: str | Path, default: Any = None) -> Any:
    """
    Read JSON file with error handling.

    Args:
        file_path: Path to JSON file
        default: Value to return if read fails (default: None)

    Returns:
        Parsed JSON data or default value on error
    """
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️  File not found: {file_path}")
        return default
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in {file_path}: {str(e)}")
        return default
    except Exception as e:
        print(f"❌ Error reading {file_path}: {str(e)}")
        return default


def write_json(
    data: Any,
    file_path: str | Path,
    indent: int = 2,
    ensure_dir: bool = True,
) -> bool:
    """
    Write data to JSON file with error handling.

    Args:
        data: Data to write
        file_path: Path to output file
        indent: JSON indentation level (default: 2)
        ensure_dir: Create parent directories if needed (default: True)

    Returns:
        True if successful, False otherwise
    """
    try:
        file_path = Path(file_path)
        if ensure_dir:
            file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w") as f:
            json.dump(data, f, indent=indent)
        return True
    except Exception as e:
        print(f"❌ Error writing to {file_path}: {str(e)}")
        return False


def read_yaml(file_path: str | Path, default: Any = None) -> Any:
    """
    Read YAML file with error handling.

    Args:
        file_path: Path to YAML file
        default: Value to return if read fails (default: None)

    Returns:
        Parsed YAML data or default value on error
    """
    try:
        with open(file_path, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"⚠️  File not found: {file_path}")
        return default
    except yaml.YAMLError as e:
        print(f"❌ Invalid YAML in {file_path}: {str(e)}")
        return default
    except Exception as e:
        print(f"❌ Error reading {file_path}: {str(e)}")
        return default


def write_yaml(
    data: Any,
    file_path: str | Path,
    ensure_dir: bool = True,
    sort_keys: bool = False,
) -> bool:
    """
    Write data to YAML file with error handling.

    Args:
        data: Data to write
        file_path: Path to output file
        ensure_dir: Create parent directories if needed (default: True)
        sort_keys: Whether to sort dictionary keys (default: False)

    Returns:
        True if successful, False otherwise
    """
    try:
        file_path = Path(file_path)
        if ensure_dir:
            file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=sort_keys)
        return True
    except Exception as e:
        print(f"❌ Error writing to {file_path}: {str(e)}")
        return False


# ============================================================================
# ASYNC FILE I/O UTILITIES
# ============================================================================


async def read_json_async(file_path: str | Path, default: Any = None) -> Any:
    """
    Async version of read_json (uses thread pool to avoid blocking).

    Args:
        file_path: Path to JSON file
        default: Value to return if read fails

    Returns:
        Parsed JSON data or default value on error
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, read_json, file_path, default)


async def write_json_async(
    data: Any,
    file_path: str | Path,
    indent: int = 2,
    ensure_dir: bool = True,
) -> bool:
    """
    Async version of write_json (uses thread pool to avoid blocking).

    Args:
        data: Data to write
        file_path: Path to output file
        indent: JSON indentation level
        ensure_dir: Create parent directories if needed

    Returns:
        True if successful, False otherwise
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, write_json, data, file_path, indent, ensure_dir
    )


# ============================================================================
# BATCH PROCESSING UTILITIES
# ============================================================================


async def process_batch(
    items: List[Any],
    processor: Callable,
    semaphore_limit: int = 50,
    filter_none: bool = True,
) -> List[Any]:
    """
    Process a batch of items concurrently with semaphore control.

    Args:
        items: Items to process
        processor: Async function to process each item
        semaphore_limit: Maximum concurrent tasks (default: 50)
        filter_none: Filter out None results (default: True)

    Returns:
        List of results

    Usage:
        results = await process_batch(
            councils,
            lambda c: process_council(session, c),
            semaphore_limit=20
        )
    """
    semaphore = asyncio.Semaphore(semaphore_limit)

    async def process_with_semaphore(item):
        async with semaphore:
            return await processor(item)

    tasks = [process_with_semaphore(item) for item in items]
    results = await asyncio.gather(*tasks)

    if filter_none:
        return [r for r in results if r is not None]
    return results


# ============================================================================
# PROGRESS REPORTING
# ============================================================================


def print_summary(
    total: int,
    successful: int,
    operation: str = "processed",
) -> None:
    """
    Print a summary of batch operations.

    Args:
        total: Total items processed
        successful: Number of successful operations
        operation: Description of operation (default: "processed")

    Usage:
        print_summary(100, 87, "extracted")
    """
    failed = total - successful
    success_rate = (successful / total * 100) if total > 0 else 0

    print("\n" + "=" * 80)
    print(f"✅ Successfully {operation}: {successful}/{total} ({success_rate:.1f}%)")
    if failed > 0:
        print(f"❌ Failed: {failed}")
    print("=" * 80)
