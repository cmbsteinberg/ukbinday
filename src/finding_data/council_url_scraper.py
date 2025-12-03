"""
Module for scraping UK council waste collection URLs from sitemaps and homepages.

This module provides the CouncilURLScraper class that:
1. Finds sitemaps via robots.txt or common locations
2. Recursively parses sitemap indexes
3. Extracts waste-related URLs from sitemaps
4. Falls back to homepage scraping when sitemaps are unavailable or empty
"""

import polars as pl
import httpx
import asyncio
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET
from typing import List, Optional
import logging
import time
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def get_council_urls(
    govuk_council_urls: str = "https://govuk-app-assets-production.s3.eu-west-1.amazonaws.com/data/local-links-manager/links_to_services_provided_by_local_authorities.csv",
) -> pl.DataFrame:
    """
    Fetches council service URLs from GOV.UK and extracts base domain URLs.

    This function downloads the GOV.UK council services CSV, filters for household waste
    collection information, extracts the top-level domain (TLD) from each URL, and
    returns a deduplicated list of council websites.

    Args:
        govuk_council_urls: URL to the GOV.UK council services CSV file.

    Returns:
        A Polars DataFrame with columns:
            - Authority Name: The name of the local authority
            - GSS: The Government Statistical Service code
            - URL: The base domain URL (e.g., https://example.gov.uk/)

    Raises:
        requests.RequestException: If the CSV download fails.
    """
    print("Fetching council waste collection URLs...")
    la_urls = (
        pl.read_csv(govuk_council_urls)
        .select(
            ["Authority Name", "GSS", "URL"],
        )
        .filter(pl.col("URL").is_not_null())
        # Extract base domain (scheme + netloc)
        .with_columns(
            pl.col("URL")
            .map_elements(
                lambda url: f"{urlparse(url).scheme}://{urlparse(url).netloc}/",
                return_dtype=pl.String,
            )
            .alias("URL")
        )
        # Filter out invalid URLs
        .filter(
            (pl.col("URL").str.starts_with("http://") | pl.col("URL").str.starts_with("https://")) &
            (~pl.col("URL").str.contains(":///"))
        )
        # Upgrade http to https for consistency
        .with_columns(
            pl.col("URL").str.replace("http://", "https://").alias("URL")
        )
        # Group by Authority Name and get first unique URL
        .unique(subset=["Authority Name"])
    )
    logger.info(f"Found {len(la_urls)} councils with valid URLs")
    return la_urls


class CouncilURLScraper:
    """
    Scraper for finding council waste collection URLs via sitemaps and homepage fallback.

    This class handles the complete workflow for discovering waste collection URLs:
    - Finding sitemaps from robots.txt or common locations
    - Recursively parsing sitemap indexes
    - Extracting waste-related URLs from sitemaps
    - Falling back to homepage HTML scraping when needed

    Attributes:
        batch_size: Number of councils to process concurrently
        max_depth: Maximum recursion depth for sitemap indexes (default: 2)
        max_child_sitemaps: Maximum child sitemaps to parse per index (default: 10)
        waste_keywords: Keywords used to identify waste-related URLs
    """

    def __init__(self, batch_size: int = 10, max_depth: int = 2, max_child_sitemaps: int = 10):
        """
        Initialize the CouncilURLScraper.

        Args:
            batch_size: Number of councils to process concurrently
            max_depth: Maximum recursion depth for sitemap indexes
            max_child_sitemaps: Maximum child sitemaps to parse per index
        """
        self.batch_size = batch_size
        self.max_depth = max_depth
        self.max_child_sitemaps = max_child_sitemaps
        self.waste_keywords = [
            "waste",
            "bin",
            "collection",
            "recycling",
            "refuse",
            "rubbish",
        ]

    async def _try_sitemap_url(self, sitemap_url: str, client: httpx.AsyncClient) -> Optional[str]:
        """
        Attempts to access a single sitemap URL.

        Args:
            sitemap_url: The full sitemap URL to try.
            client: An httpx AsyncClient for making HTTP requests.

        Returns:
            The sitemap URL if successful, None otherwise.
        """
        try:
            response = await client.head(sitemap_url, follow_redirects=True, timeout=5.0)
            if response.status_code == 200:
                logger.debug(f"HEAD success: {sitemap_url}")
                return sitemap_url
            else:
                logger.debug(f"HEAD returned {response.status_code} for {sitemap_url}")
        except httpx.TimeoutException:
            logger.debug(f"HEAD timeout: {sitemap_url}")
        except httpx.ConnectError as e:
            error_msg = str(e).lower()
            if 'ssl' in error_msg or 'tls' in error_msg or 'certificate' in error_msg:
                logger.warning(f"🔒 HEAD TLS/SSL error for {sitemap_url}: {e}")
            else:
                logger.debug(f"HEAD connection error for {sitemap_url}: {type(e).__name__}: {e}")
        except Exception as e:
            error_msg = str(e).lower()
            if 'ssl' in error_msg or 'tls' in error_msg or 'certificate' in error_msg:
                logger.warning(f"🔒 HEAD TLS/SSL error for {sitemap_url}: {e}")
            else:
                logger.debug(f"HEAD failed for {sitemap_url}: {type(e).__name__}: {e}")

        # Try GET if HEAD fails
        try:
            response = await client.get(
                sitemap_url, follow_redirects=True, timeout=5.0
            )
            if response.status_code == 200:
                logger.debug(f"GET success: {sitemap_url}")
                return sitemap_url
            else:
                logger.debug(f"GET returned {response.status_code} for {sitemap_url}")
        except httpx.TimeoutException:
            logger.debug(f"GET timeout: {sitemap_url}")
        except httpx.ConnectError as e:
            error_msg = str(e).lower()
            if 'ssl' in error_msg or 'tls' in error_msg or 'certificate' in error_msg:
                logger.warning(f"🔒 GET TLS/SSL error for {sitemap_url}: {e}")
            else:
                logger.debug(f"GET connection error for {sitemap_url}: {type(e).__name__}: {e}")
        except Exception as e:
            error_msg = str(e).lower()
            if 'ssl' in error_msg or 'tls' in error_msg or 'certificate' in error_msg:
                logger.warning(f"🔒 GET TLS/SSL error for {sitemap_url}: {e}")
            else:
                logger.debug(f"GET failed for {sitemap_url}: {type(e).__name__}: {e}")

        return None

    async def _check_robots_txt(self, url: str, client: httpx.AsyncClient) -> Optional[str]:
        """
        Checks robots.txt for sitemap directive.

        Args:
            url: Base URL of the website.
            client: An httpx AsyncClient for making HTTP requests.

        Returns:
            Sitemap URL if found in robots.txt, None otherwise.
        """
        robots_url = f"{url.rstrip('/')}/robots.txt"
        try:
            response = await client.get(robots_url, follow_redirects=True, timeout=5.0)
            if response.status_code == 200:
                # Parse robots.txt for Sitemap directive
                for line in response.text.split('\n'):
                    if line.lower().startswith('sitemap:'):
                        sitemap_url = line.split(':', 1)[1].strip()
                        logger.debug(f"Found sitemap in robots.txt: {sitemap_url}")
                        return sitemap_url
        except Exception as e:
            logger.debug(f"Could not fetch robots.txt for {url}: {type(e).__name__}")
        return None

    def _extract_waste_urls_from_urlset(self, root: ET.Element) -> List[str]:
        """
        Extract waste-related URLs from a regular sitemap (urlset).

        Args:
            root: Parsed XML root element.

        Returns:
            List of up to 5 waste-related URLs.
        """
        namespaces = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        # Find all <loc> tags
        urls = []
        for loc in root.findall(".//ns:loc", namespaces):
            if loc.text:
                urls.append(loc.text)

        # Try without namespace if nothing found
        if not urls:
            for loc in root.findall(".//loc"):
                if loc.text:
                    urls.append(loc.text)

        # Filter URLs containing waste-related keywords
        waste_urls = [
            url
            for url in urls
            if any(keyword in url.lower() for keyword in self.waste_keywords)
        ]

        return waste_urls[:5]

    async def _process_sitemap_index(
        self,
        council_name: str,
        root: ET.Element,
        parent_sitemap_url: str,
        client: httpx.AsyncClient,
        depth: int
    ) -> List[str]:
        """
        Process a sitemap index by recursively fetching child sitemaps.

        Args:
            council_name: Name of the council (for logging)
            root: Parsed XML root element of the sitemap index
            parent_sitemap_url: URL of the parent sitemap (for relative URL resolution)
            client: httpx AsyncClient
            depth: Current recursion depth

        Returns:
            Combined list of waste URLs from all child sitemaps
        """
        namespaces = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        # Extract child sitemap URLs
        child_sitemap_urls = []
        for loc in root.findall(".//ns:loc", namespaces):
            if loc.text:
                # Resolve relative URLs against parent sitemap URL
                absolute_url = urljoin(parent_sitemap_url, loc.text.strip())
                child_sitemap_urls.append(absolute_url)

        # Try without namespace if nothing found
        if not child_sitemap_urls:
            for loc in root.findall(".//loc"):
                if loc.text:
                    absolute_url = urljoin(parent_sitemap_url, loc.text.strip())
                    child_sitemap_urls.append(absolute_url)

        logger.info(f"Found {len(child_sitemap_urls)} child sitemaps for {council_name} (depth={depth})")

        # Limit number of child sitemaps to prevent excessive requests
        if len(child_sitemap_urls) > self.max_child_sitemaps:
            logger.warning(f"Limiting {council_name} to first {self.max_child_sitemaps} child sitemaps (found {len(child_sitemap_urls)})")
            child_sitemap_urls = child_sitemap_urls[:self.max_child_sitemaps]

        # Fetch all child sitemaps in parallel
        tasks = [
            self.find_waste_urls_in_sitemap(
                council_name,
                child_url,
                client,
                depth=depth + 1
            )
            for child_url in child_sitemap_urls
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Combine results, filtering out exceptions
        all_waste_urls = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Failed to parse child sitemap {child_sitemap_urls[i]} for {council_name}: {result}")
            else:
                all_waste_urls.extend(result)

        # Deduplicate and return up to 5 URLs
        unique_urls = list(dict.fromkeys(all_waste_urls))  # Preserves order
        return unique_urls[:5]

    async def find_sitemap_for_url(
        self,
        council_name: str,
        url: str,
        client: httpx.AsyncClient,
    ) -> Optional[str]:
        """
        Attempts to find the sitemap URL for a given council website.

        First checks robots.txt for sitemap directive, then tries common sitemap locations.

        Args:
            council_name: Name of the council (for logging purposes).
            url: Base URL of the council website.
            client: An httpx AsyncClient for making HTTP requests.

        Returns:
            The URL of the sitemap if found, None otherwise.
        """
        start_time = time.time()
        logger.debug(f"Searching sitemap for {council_name} at {url}")

        # First, check robots.txt - much faster!
        sitemap_from_robots = await self._check_robots_txt(url, client)
        if sitemap_from_robots:
            # Verify the sitemap URL actually works
            verified = await self._try_sitemap_url(sitemap_from_robots, client)
            if verified:
                elapsed = time.time() - start_time
                logger.info(f"✓ Found sitemap via robots.txt for {council_name} in {elapsed:.1f}s: {verified}")
                return verified

        # If robots.txt didn't work, try common locations
        sitemap_suffixes = [
            "sitemap.xml",
            "sitemap_index.xml",
            "sitemap",
            "sitemap1.xml",
            "sitemap-index.xml",
        ]

        # Try all sitemap URLs in parallel
        sitemap_urls = [f"{url.rstrip('/')}/{suffix}" for suffix in sitemap_suffixes]
        tasks = [self._try_sitemap_url(sitemap_url, client) for sitemap_url in sitemap_urls]
        results = await asyncio.gather(*tasks)

        elapsed = time.time() - start_time

        # Return the first successful result
        for result in results:
            if result:
                logger.info(f"✓ Found sitemap for {council_name} in {elapsed:.1f}s: {result}")
                return result

        logger.warning(f"✗ No sitemap found for {council_name} after {elapsed:.1f}s: {url}")
        return None

    async def find_waste_urls_in_sitemap(
        self,
        council_name: str,
        sitemap_url: str,
        client: httpx.AsyncClient,
        depth: int = 0
    ) -> List[str]:
        """
        Parses a sitemap and finds URLs related to household waste collection.

        Handles both sitemap indexes (recursively) and regular sitemaps.
        Searches for URLs containing keywords like 'waste', 'bin', 'collection', etc.

        Args:
            council_name: Name of the council (for logging purposes).
            sitemap_url: URL of the sitemap to parse.
            client: An httpx AsyncClient for making HTTP requests.
            depth: Current recursion depth (for sitemap indexes).

        Returns:
            A list of URLs from the sitemap that match waste collection keywords.
        """
        start_time = time.time()
        logger.debug(f"Parsing sitemap for {council_name}: {sitemap_url} (depth={depth})")

        try:
            response = await client.get(sitemap_url, follow_redirects=True, timeout=15.0)
            if response.status_code != 200:
                logger.warning(f"Sitemap returned status {response.status_code} for {council_name}")
                return []

            # Parse XML
            root = ET.fromstring(response.content)

            # Detect sitemap type by root element
            root_tag = root.tag.split('}')[-1]  # Remove namespace prefix

            if root_tag == 'sitemapindex' and depth < self.max_depth:
                # This is a sitemap index - recursively fetch child sitemaps
                logger.debug(f"Detected sitemap index for {council_name}, processing recursively...")
                return await self._process_sitemap_index(
                    council_name,
                    root,
                    sitemap_url,
                    client,
                    depth
                )

            elif root_tag == 'urlset':
                # This is a regular sitemap - extract and filter URLs
                waste_urls = self._extract_waste_urls_from_urlset(root)

                elapsed = time.time() - start_time
                if waste_urls:
                    logger.info(f"Found {len(waste_urls)} waste URLs for {council_name} in {elapsed:.1f}s")
                else:
                    logger.debug(f"No waste URLs found in sitemap for {council_name} (depth={depth}, elapsed={elapsed:.1f}s)")

                return waste_urls

            else:
                # Unknown format or max depth reached
                if depth >= self.max_depth:
                    logger.warning(f"Max recursion depth {self.max_depth} reached for {council_name}")
                else:
                    logger.warning(f"Unknown sitemap format for {council_name}: {root_tag}")
                return []

        except httpx.TimeoutException:
            elapsed = time.time() - start_time
            logger.warning(f"Timeout parsing sitemap for {council_name} after {elapsed:.1f}s")
            return []
        except httpx.ConnectError as e:
            elapsed = time.time() - start_time
            error_msg = str(e).lower()
            if 'ssl' in error_msg or 'tls' in error_msg or 'certificate' in error_msg:
                logger.warning(f"🔒 TLS/SSL error parsing sitemap for {council_name} after {elapsed:.1f}s: {e}")
            else:
                logger.error(f"Connection error parsing sitemap for {council_name} after {elapsed:.1f}s: {e}")
            return []
        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = str(e).lower()
            if 'ssl' in error_msg or 'tls' in error_msg or 'certificate' in error_msg:
                logger.warning(f"🔒 TLS/SSL error parsing sitemap for {council_name} after {elapsed:.1f}s: {e}")
            else:
                logger.error(f"Error parsing sitemap for {council_name} after {elapsed:.1f}s: {type(e).__name__}: {e}")
            return []

    async def find_waste_urls_from_homepage(
        self,
        council_name: str,
        homepage_url: str,
        client: httpx.AsyncClient
    ) -> List[str]:
        """
        Scrape homepage HTML for waste-related URLs as fallback.

        This is used when no sitemap is found or sitemap returns no results.
        Uses regex to extract href attributes and filters for waste keywords.

        Args:
            council_name: Name of the council (for logging)
            homepage_url: Base URL of the council website
            client: httpx AsyncClient

        Returns:
            List of up to 5 waste-related URLs found on homepage
        """
        logger.debug(f"Scraping homepage for {council_name}: {homepage_url}")

        try:
            response = await client.get(homepage_url, follow_redirects=True, timeout=10.0)
            if response.status_code != 200:
                logger.warning(f"Homepage returned status {response.status_code} for {council_name}")
                return []

            html = response.text

            # Extract all href attributes using regex
            # Matches: href="..." or href='...'
            href_pattern = r'href=["\'](.*?)["\']'
            hrefs = re.findall(href_pattern, html, re.IGNORECASE)

            # Parse base domain for filtering
            parsed_base = urlparse(homepage_url)
            base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"

            waste_urls = []
            seen_urls = set()

            for href in hrefs:
                # Skip empty, anchors, javascript, mailto, tel
                if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                    continue

                # Convert relative URLs to absolute
                absolute_url = urljoin(homepage_url, href.strip())

                # Parse the absolute URL
                parsed_url = urlparse(absolute_url)

                # Only include URLs from same domain
                if parsed_url.netloc != parsed_base.netloc:
                    continue

                # Check for waste keywords in path
                url_lower = absolute_url.lower()
                if any(keyword in url_lower for keyword in self.waste_keywords):
                    # Normalize URL (remove fragments, trailing slashes for deduplication)
                    normalized_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path.rstrip('/')}"
                    if parsed_url.query:
                        normalized_url += f"?{parsed_url.query}"

                    if normalized_url not in seen_urls:
                        seen_urls.add(normalized_url)
                        waste_urls.append(absolute_url)

                        # Stop after finding 5 URLs
                        if len(waste_urls) >= 5:
                            break

            if waste_urls:
                logger.info(f"Found {len(waste_urls)} waste URLs from homepage for {council_name}")
            else:
                logger.debug(f"No waste URLs found on homepage for {council_name}")

            return waste_urls

        except httpx.TimeoutException:
            logger.warning(f"Timeout scraping homepage for {council_name}")
            return []
        except Exception as e:
            logger.warning(f"Error scraping homepage for {council_name}: {type(e).__name__}: {e}")
            return []

    async def process_council(
        self,
        council_name: str,
        gss: str,
        url: str,
        client: httpx.AsyncClient
    ) -> dict:
        """
        Processes a single council: finds sitemap and extracts waste collection URLs.

        This combines sitemap discovery, URL extraction, and homepage fallback
        into a single operation.

        Args:
            council_name: Name of the council.
            gss: Government Statistical Service code.
            url: Base URL of the council website.
            client: An httpx AsyncClient for making HTTP requests.

        Returns:
            A dictionary containing:
                - Authority Name
                - GSS
                - URL
                - sitemap_url
                - waste_collection_urls
        """
        start_time = time.time()
        logger.info(f"⏳ Processing {council_name}...")

        # Find the sitemap
        sitemap_url = await self.find_sitemap_for_url(council_name, url, client)

        # If sitemap found, extract waste URLs
        waste_urls = []
        if sitemap_url:
            waste_urls = await self.find_waste_urls_in_sitemap(council_name, sitemap_url, client)

        # FALLBACK: If no waste URLs found (no sitemap OR empty results), try homepage
        if not waste_urls:
            logger.info(f"No waste URLs from sitemap for {council_name}, trying homepage...")
            waste_urls = await self.find_waste_urls_from_homepage(council_name, url, client)

        elapsed = time.time() - start_time
        logger.info(f"✅ Completed {council_name} in {elapsed:.1f}s (sitemap: {'Yes' if sitemap_url else 'No'}, waste URLs: {len(waste_urls)})")

        return {
            "Authority Name": council_name,
            "GSS": gss,
            "URL": url,
            "sitemap_url": sitemap_url,
            "waste_collection_urls": waste_urls,
        }

    async def process_all_councils(self, councils_df: pl.DataFrame, batch_size: int = 10) -> pl.DataFrame:
        """
        Processes all councils in small batches to avoid connection pool exhaustion.

        Args:
            councils_df: DataFrame containing council information with columns:
                - Authority Name
                - GSS
                - URL
            batch_size: Number of councils to process concurrently (default: 10)

        Returns:
            A DataFrame with columns:
                - Authority Name
                - GSS
                - URL
                - sitemap_url: The discovered sitemap URL (or None)
                - waste_collection_urls: List of relevant waste collection URLs
        """
        start_time = time.time()
        total_councils = len(councils_df)
        logger.info(f"\n{'='*80}")
        logger.info(f"🚀 Starting to process {total_councils} councils in batches of {batch_size}...")
        logger.info(f"{'='*80}\n")

        # Use a browser-like user agent to avoid being blocked
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }

        all_results = []

        async with httpx.AsyncClient(
            limits=httpx.Limits(max_connections=batch_size * 2, max_keepalive_connections=batch_size),
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers=headers,
            follow_redirects=True
        ) as client:
            # Process councils in batches
            councils_list = list(councils_df.iter_rows(named=True))

            for i in range(0, len(councils_list), batch_size):
                batch = councils_list[i:i+batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(councils_list) + batch_size - 1) // batch_size

                logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} councils)...")

                tasks = [
                    self.process_council(row["Authority Name"], row["GSS"], row["URL"], client)
                    for row in batch
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Check for exceptions
                for j, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"Council failed with exception: {result}")
                        row = batch[j]
                        all_results.append({
                            "Authority Name": row["Authority Name"],
                            "GSS": row["GSS"],
                            "URL": row["URL"],
                            "sitemap_url": None,
                            "waste_collection_urls": [],
                        })
                    else:
                        all_results.append(result)

        elapsed = time.time() - start_time
        logger.info(f"\n{'='*80}")
        logger.info(f"🎉 Completed processing all {total_councils} councils in {elapsed:.1f}s ({elapsed/total_councils:.1f}s per council average)")
        logger.info(f"{'='*80}\n")

        # Convert results back to DataFrame
        return pl.DataFrame(all_results)
