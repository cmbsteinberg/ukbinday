import calendar
import json
import os
import re
from datetime import datetime, timedelta
from enum import Enum

import holidays
import pandas as pd
import requests
from dateutil.parser import parse
from seleniumwire import webdriver as wiredriver
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from urllib3.exceptions import MaxRetryError
from webdriver_manager.chrome import ChromeDriverManager

date_format = "%d/%m/%Y"
days_of_week = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


class Region(Enum):
    ENG = 1
    NIR = 2
    SCT = 3
    WLS = 4


def check_postcode(postcode: str):
    """
    Checks a postcode exists and validates UK formatting against a RegEx string
        :param postcode: Postcode to parse
    """
    postcode_api_url = "https://api.postcodes.io/postcodes/"
    postcode_api_response = requests.get(f"{postcode_api_url}{postcode}")

    if postcode_api_response.status_code != 200:
        val_error = json.loads(postcode_api_response.text)
        raise ValueError(
            f"Exception: {val_error['error']} Status: {val_error['status']}"
        )
    return True


def check_paon(paon: str):
    """
    Checks that PAON data exists
        :param paon: PAON data to check, usually house number
    """
    try:
        if paon is None:
            raise ValueError("Invalid house number")
        return True
    except Exception as ex:
        print(f"Exception encountered: {ex}")
        print("Please check the provided house number.")
        exit(1)


def check_uprn(uprn: str):
    """
    Checks that the UPRN exists
        :param uprn: UPRN to check
    """
    try:
        if uprn is None or uprn == "":
            raise ValueError("Invalid UPRN")
        return True
    except Exception as ex:
        print(f"Exception encountered: {ex}")
        print("Please check the provided UPRN.")


def check_usrn(usrn: str):
    """
    Checks that the USRN exists
        :param uprn: USRN to check
    """
    try:
        if usrn is None or usrn == "":
            raise ValueError("Invalid USRN")
        return True
    except Exception as ex:
        print(f"Exception encountered: {ex}")
        print("Please check the provided USRN.")


def get_date_with_ordinal(date_number: int) -> str:
    """
    Return ordinal text on day of date
        :rtype: str
        :param date_number: Date number as an integer (e.g. 4)
        :return: Return date with ordinal suffix (e.g. 4th)
    """
    return str(date_number) + (
        "th"
        if 4 <= date_number % 100 <= 20
        else {1: "st", 2: "nd", 3: "rd"}.get(date_number % 10, "th")
    )


def has_numbers(inputString: str) -> bool:
    """

    :rtype: bool
    :param inputString: String to check for numbers
    :return: True if any numbers are found in input string
    """
    return any(char.isdigit() for char in inputString)


def remove_ordinal_indicator_from_date_string(date_string: str) -> str:
    """
    Remove the ordinal indicator from a written date as a string.
    E.g. June 12th 2022 -> June 12 2022
    :rtype: str
    """
    ord_day_pattern = re.compile(r"(?<=\d)(st|nd|rd|th)")
    return re.compile(ord_day_pattern).sub("", date_string)


def parse_header(raw_header: str) -> dict:
    """
    Parses a header string and returns one that can be useful
            :rtype: dict
            :param raw_header: header as a string, with values to separate as pipe (|)
            :return: header in a dictionary format that can be used in requests
    """
    header = dict()
    for line in raw_header.split("|"):
        if line.startswith(":"):
            a, b = line[1:].split(":", 1)
            a = f":{a}"
        else:
            a, b = line.split(":", 1)

        header[a.strip()] = b.strip()

    return header


def is_holiday(date_to_check: datetime, region: Region = Region.ENG) -> bool:
    """
    Checks if a given date is a public holiday
        :param date_to_check: Date to check if holiday
        :param region: The UK nation to check. Defaults to ENG.
        :return: Bool - true if a holiday, false if not
    """
    uk_holidays = holidays.country_holidays("GB", subdiv=region.name)

    if date_to_check in uk_holidays:
        return True
    else:
        return False


def is_weekend(date_to_check: datetime) -> bool:
    """
    Checks if a given date is a weekend
    :param date_to_check: Date to check if it falls on a weekend
    :return: Bool - true if a weekend day, false if not
    """
    return True if date_to_check.date().weekday() >= 5 else False


def is_working_day(date_to_check: datetime, region: Region = Region.ENG) -> bool:
    """
    Wraps is_holiday() and is_weekend() into one function
    :param date_to_check: Date to check if holiday
    :param region: The UK nation to check. Defaults to ENG.
    :return: Bool - true if a working day (non-holiday, Mon-Fri).
    """
    return (
        False
        if is_holiday(date_to_check, region) or is_weekend(date_to_check)
        else True
    )


def get_next_working_day(date: datetime, region: Region = Region.ENG) -> datetime:
    while not is_working_day(date, region):
        date += timedelta(days=1)
    return date


def get_weekday_dates_in_period(start: datetime, day_of_week: int, amount=8) -> list:
    """
    Returns a list of dates of a given weekday from a start date for the given amount of weeks
        :param start: Start date
        :param day_of_week: Day of week number. Recommended to use calendar.DAY (Monday=0, Sunday=6)
        :param amount: Number of weeks to get dates. Defaults to 8 weeks.
        :return: List of dates where the specified weekday is in the period
    """
    return (
        pd.date_range(
            start=start, freq=f"W-{calendar.day_abbr[day_of_week]}", periods=amount
        )
        .strftime(date_format)
        .tolist()
    )


def get_dates_every_x_days(start: datetime, step: int, amount: int = 8) -> list:
    """
    Returns a list of dates for `X` days from start date. For example, calling `get_stepped_dates_in_period(s, 21, 4)` would
    return `4` dates every `21` days from the start date `s`
        :param start: Date to start from
        :param step: X amount of days
        :param amount: Number of dates to find
        :return: List of dates every X days from start date
        :rtype: list
    """
    return (
        pd.date_range(start=start, freq=f"{step}D", periods=amount)
        .strftime(date_format)
        .tolist()
    )


def get_next_occurrence_from_day_month(date: datetime) -> datetime:
    current_date = datetime.now()
    # Get the current day and month as integers
    current_day = current_date.day
    current_month = current_date.month

    # Extract the target day and month from the input date
    target_day = date.day
    target_month = date.month

    # Check if the target date has already occurred this year
    if (target_month < current_month) or (
        target_month == current_month and target_day < current_day
    ):
        date = pd.to_datetime(date) + pd.DateOffset(years=1)

    return date


def remove_alpha_characters(input_string: str) -> str:
    return "".join(c for c in input_string if c.isdigit() or c == " ")


def update_input_json(council: str, url: str, input_file_path: str, **kwargs):
    """
    Create or update a council's entry in the input.json file.

    :param council: Name of the council.
    :param url: URL associated with the council.
    :param input_file_path: Path to the input JSON file.
    :param kwargs: Additional parameters to store (postcode, paon, uprn, usrn, web_driver, skip_get_url).
    """
    try:
        data = load_data(input_file_path)
        council_data = data.get(council, {"wiki_name": council})
        council_data.update({"url": url, **kwargs})
        data[council] = council_data

        save_data(input_file_path, data)
    except IOError as e:
        print(f"Error updating the JSON file: {e}")
    except json.JSONDecodeError:
        print("Failed to decode JSON, check the integrity of the input file.")


def load_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            return json.load(file)
    return {}


def save_data(file_path, data):
    with open(file_path, "w") as file:
        json.dump(data, file, sort_keys=True, indent=4)


def get_next_day_of_week(day_name, date_format="%d/%m/%Y"):
    days_of_week = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    today = datetime.now()
    today_idx = today.weekday()  # Monday is 0 and Sunday is 6
    target_idx = days_of_week.index(day_name)

    days_until_target = (target_idx - today_idx) % 7
    if days_until_target == 0:
        days_until_target = 7  # Ensure it's the next instance of the day, not today if today is that day

    next_day = today + timedelta(days=days_until_target)
    return next_day.strftime(date_format)


def contains_date(string, fuzzy=False) -> bool:
    """
    Return whether the string can be interpreted as a date.

    :param string: str, string to check for date
    :param fuzzy: bool, ignore unknown tokens in string if True
    """
    try:
        parse(string, fuzzy=fuzzy)
        return True

    except ValueError:
        return False


def create_webdriver(
    web_driver: str = None,
    headless: bool = True,
    user_agent: str = None,
    session_name: str = None,
):
    """
    Create and return a Chrome WebDriver configured for optional headless operation.

    :param web_driver: URL to the Selenium server for remote web drivers. If None, a local driver is created.
    :param headless: Whether to run the browser in headless mode.
    :param user_agent: Optional custom user agent string.
    :param session_name: Optional custom session name string.
    :return: An instance of a Chrome WebDriver.
    :raises WebDriverException: If the WebDriver cannot be created.
    """
    # FORCE LOCAL BROWSER for Selenium-based councils
    # Override remote web_driver to use local selenium-wire instead
    # This ensures better request tracking while maintaining performance
    if web_driver:  # Only override if web_driver was specified
        web_driver = None

    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    if user_agent:
        options.add_argument(f"--user-agent={user_agent}")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    if session_name and web_driver:
        options.set_capability("se:name", session_name)

    # Enable performance logging for network capture (works with both local and remote)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    try:
        if web_driver:
            # Use regular selenium for remote webdriver (selenium-wire has compatibility issues)
            # But we enable performance logging to capture network requests via CDP
            driver = webdriver.Remote(
                command_executor=web_driver,
                options=options
            )
        else:
            # Use selenium-wire for local webdriver to enable request tracking
            seleniumwire_options = {
                'disable_encoding': True,  # Don't decode responses
                # Exclude patterns to avoid buffering static resources (improves performance)
                'exclude_hosts': [],  # We'll filter in quit() instead for better control
            }
            driver = wiredriver.Chrome(
                service=ChromeService(ChromeDriverManager().install()),
                options=options,
                seleniumwire_options=seleniumwire_options
            )

        # Set window position to ensure it's visible on screen
        driver.set_window_position(0, 0)

        # If there's an active RequestTracker, register this driver and wrap quit()
        if hasattr(_tracker_context, 'tracker') and _tracker_context.tracker:
            tracker = _tracker_context.tracker
            tracker.drivers.append(driver)

            # Wrap quit() to extract logs BEFORE the driver is closed
            original_quit = driver.quit
            def quit_with_logging():
                try:
                    # Extract selenium-wire requests before quitting
                    if hasattr(driver, 'requests'):  # selenium-wire
                        # Filter out static assets (images, fonts, media, CSS) to improve performance
                        # Keep JS as it might contain important data or API calls
                        static_extensions = (
                            '.css', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico',
                            '.woff', '.woff2', '.ttf', '.eot', '.otf',
                            '.mp4', '.webm', '.mp3', '.wav',
                            '.webp', '.avif', '.bmp', '.tiff'
                        )

                        for req in driver.requests:
                            # Skip static assets by URL extension
                            url_lower = req.url.lower()
                            if any(url_lower.endswith(ext) for ext in static_extensions):
                                continue

                            # Skip common static asset paths
                            if any(path in url_lower for path in ['/fonts/', '/images/', '/img/', '/media/']):
                                continue
                            # Extract request body (limit size to avoid memory issues)
                            request_body = None
                            if req.body:
                                # Skip very large request bodies (>1MB)
                                if len(req.body) > 1_000_000:
                                    request_body = f'<too large: {len(req.body)} bytes>'
                                else:
                                    try:
                                        request_body = json.loads(req.body.decode('utf-8'))
                                    except:
                                        try:
                                            body_str = req.body.decode('utf-8')
                                            request_body = body_str if len(body_str) < 10000 else body_str[:10000] + '... [truncated]'
                                        except:
                                            request_body = '<binary or unreadable>'

                            # Extract response body (limit size to avoid memory issues)
                            response_body = None
                            if req.response and req.response.body:
                                # Skip very large responses (>1MB) to improve performance
                                if len(req.response.body) > 1_000_000:
                                    response_body = f'<too large: {len(req.response.body)} bytes>'
                                else:
                                    try:
                                        response_body = json.loads(req.response.body.decode('utf-8'))
                                    except:
                                        try:
                                            body_str = req.response.body.decode('utf-8')
                                            response_body = body_str if len(body_str) < 10000 else body_str[:10000] + '... [truncated]'
                                        except:
                                            response_body = '<binary or unreadable>'

                            tracker.requests_log.append({
                                'method': req.method,
                                'url': req.url,
                                'request_headers': dict(req.headers) if req.headers else {},
                                'request_body': request_body,
                                'status_code': req.response.status_code if req.response else None,
                                'response_headers': dict(req.response.headers) if req.response and req.response.headers else {},
                                'response_body': response_body,
                                'source': 'selenium-wire',
                                'timestamp': datetime.now().isoformat()
                            })
                except Exception:
                    pass  # Don't fail if log extraction fails
                finally:
                    original_quit()  # Always quit the driver
            driver.quit = quit_with_logging

        return driver
    except MaxRetryError as e:
        print(f"Failed to create WebDriver: {e}")
        raise


# Request tracking functionality
import threading
from typing import List, Dict, Any

_tracker_context = threading.local()


class RequestTracker:
    """Context manager to track all HTTP requests during execution"""

    def __init__(self, council_name: str = None, output_dir: str = "request_logs"):
        self.council_name = council_name
        self.output_dir = output_dir
        self.requests_log: List[Dict[str, Any]] = []
        self._original_request = None
        self._original_session_request = None
        self._original_create_webdriver = None
        self.drivers = []
        self.start_time = None
        self.metadata = {}

    def __enter__(self):
        self.start_time = datetime.now()

        # Store in thread-local storage so create_webdriver can find us
        _tracker_context.tracker = self

        # Monkey-patch requests library (module-level function)
        self._original_request = requests.request
        tracker_self = self

        def logged_request(*args, **kwargs):
            # Extract request body BEFORE making the request
            # Note: requests library pre-processes json parameter into data
            request_body = None
            if 'json' in kwargs and kwargs['json'] is not None:
                # Prefer json if it's not None (original user data)
                request_body = kwargs['json']
            elif 'data' in kwargs and kwargs['data']:
                # data might be JSON string or form data
                data = kwargs['data']
                # Try to parse if it's a JSON string
                if isinstance(data, (str, bytes)):
                    try:
                        request_body = json.loads(data if isinstance(data, str) else data.decode('utf-8'))
                    except:
                        request_body = data  # Keep as is
                else:
                    request_body = data

            # Also capture params (query string)
            params = kwargs.get('params', None)

            response = tracker_self._original_request(*args, **kwargs)

            # Try to parse response body
            response_body = None
            try:
                response_body = response.json()
            except (ValueError, json.JSONDecodeError):
                # Not JSON, try to get text (truncate if too long)
                try:
                    text = response.text
                    response_body = text if len(text) < 10000 else text[:10000] + '... [truncated]'
                except:
                    response_body = '<binary or unreadable>'

            tracker_self.requests_log.append({
                'method': kwargs.get('method', args[0] if args else 'GET'),
                'url': kwargs.get('url', args[1] if len(args) > 1 else ''),
                'request_headers': dict(kwargs.get('headers', {})),
                'request_params': params,
                'request_body': request_body,
                'status_code': response.status_code,
                'response_headers': dict(response.headers),
                'response_body': response_body,
                'source': 'requests',
                'timestamp': datetime.now().isoformat()
            })
            return response

        requests.request = logged_request

        # ALSO monkey-patch Session.request (used by session.get(), session.post(), etc.)
        self._original_session_request = requests.Session.request

        def logged_session_request(session_self, method, url, **kwargs):
            # Extract request body BEFORE making the request
            # Note: requests library pre-processes json parameter into data
            request_body = None
            if 'json' in kwargs and kwargs['json'] is not None:
                # Prefer json if it's not None (original user data)
                request_body = kwargs['json']
            elif 'data' in kwargs and kwargs['data']:
                # data might be JSON string or form data
                data = kwargs['data']
                # Try to parse if it's a JSON string
                if isinstance(data, (str, bytes)):
                    try:
                        request_body = json.loads(data if isinstance(data, str) else data.decode('utf-8'))
                    except:
                        request_body = data  # Keep as is
                else:
                    request_body = data

            # Also capture params (query string)
            params = kwargs.get('params', None)

            response = tracker_self._original_session_request(session_self, method, url, **kwargs)

            # Try to parse response body
            response_body = None
            try:
                response_body = response.json()
            except (ValueError, json.JSONDecodeError):
                # Not JSON, try to get text (truncate if too long)
                try:
                    text = response.text
                    response_body = text if len(text) < 10000 else text[:10000] + '... [truncated]'
                except:
                    response_body = '<binary or unreadable>'

            tracker_self.requests_log.append({
                'method': method,
                'url': url,
                'request_headers': dict(kwargs.get('headers', {})),
                'request_params': params,
                'request_body': request_body,
                'status_code': response.status_code,
                'response_headers': dict(response.headers),
                'response_body': response_body,
                'source': 'requests.Session',
                'timestamp': datetime.now().isoformat()
            })
            return response

        requests.Session.request = logged_session_request

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore original functions
        if self._original_request:
            requests.request = self._original_request

        if hasattr(self, '_original_session_request') and self._original_session_request:
            requests.Session.request = self._original_session_request

        # Clear thread-local storage
        if hasattr(_tracker_context, 'tracker'):
            del _tracker_context.tracker

        return False  # Don't suppress exceptions

    def _extract_network_from_performance_logs(self, driver) -> List[Dict[str, Any]]:
        """Extract network requests from Chrome DevTools Protocol performance logs"""
        network_requests = []

        try:
            logs = driver.get_log('performance')
        except Exception as e:
            # If performance logs not available, skip
            return network_requests

        # Store network events by request ID
        events_by_request_id = {}

        for entry in logs:
            try:
                log = json.loads(entry['message'])
                message = log.get('message', {})
                method = message.get('method', '')
                params = message.get('params', {})

                # Track different network event types
                if method == 'Network.requestWillBeSent':
                    request_id = params.get('requestId')
                    if request_id not in events_by_request_id:
                        events_by_request_id[request_id] = {}
                    events_by_request_id[request_id]['request'] = params.get('request', {})
                    events_by_request_id[request_id]['type'] = params.get('type', '')

                elif method == 'Network.responseReceived':
                    request_id = params.get('requestId')
                    if request_id not in events_by_request_id:
                        events_by_request_id[request_id] = {}
                    events_by_request_id[request_id]['response'] = params.get('response', {})

                elif method == 'Network.loadingFinished':
                    request_id = params.get('requestId')
                    if request_id not in events_by_request_id:
                        events_by_request_id[request_id] = {}
                    events_by_request_id[request_id]['finished'] = True

            except (json.JSONDecodeError, KeyError):
                continue

        # Static resource extensions to exclude
        static_extensions = (
            '.css', '.js', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.woff', '.woff2',
            '.ttf', '.eot', '.otf', '.mp4', '.webm', '.mp3', '.wav', '.pdf', '.zip', '.map'
        )

        # Convert events to request format
        for request_id, events in events_by_request_id.items():
            request_data = events.get('request', {})
            response_data = events.get('response', {})
            resource_type = events.get('type', '')

            # Skip if we don't have basic request info
            if not request_data or 'url' not in request_data:
                continue

            url = request_data.get('url', '')

            # Filter out Chrome internal URLs and data URIs
            if url.startswith(('chrome-extension://', 'data:', 'about:')):
                continue

            # Skip static resources by URL extension
            url_lower = url.lower()
            if any(url_lower.endswith(ext) for ext in static_extensions):
                continue

            # Skip common static resource types (but keep XHR, Fetch, Document)
            if resource_type in ('Image', 'Stylesheet', 'Script', 'Font', 'Media'):
                continue

            network_requests.append({
                'method': request_data.get('method', 'GET'),
                'url': url,
                'request_headers': request_data.get('headers', {}),
                'request_body': request_data.get('postData', None),
                'status_code': response_data.get('status', None),
                'response_headers': response_data.get('headers', {}),
                'response_body': '<not captured by CDP - use selenium-wire for response bodies>',
                'resource_type': resource_type,
                'source': 'selenium-cdp',
                'timestamp': datetime.now().isoformat()
            })

        return network_requests

    def get_all_requests(self) -> List[Dict[str, Any]]:
        """Get all tracked requests from both requests library and selenium"""
        # All requests (HTTP and selenium-wire) are already in requests_log
        # They are extracted in real-time or in the quit() wrapper
        return list(self.requests_log)

    def add_metadata(self, **kwargs):
        """Add metadata like UPRN, postcode, etc."""
        self.metadata.update(kwargs)

    def save_to_file(self, success: bool = True) -> str:
        """Save tracked requests to a JSON file"""
        os.makedirs(self.output_dir, exist_ok=True)

        filename = f"{self.council_name}.json" if self.council_name else "requests.json"
        filepath = os.path.join(self.output_dir, filename)

        data = {
            "council": self.council_name,
            "timestamp": self.start_time.isoformat() if self.start_time else None,
            "success": success,
            "total_requests": len(self.get_all_requests()),
            "requests": self.get_all_requests(),
            "metadata": self.metadata
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        return filepath
