"""Observer for capturing page state."""

import re
from datetime import datetime

from playwright.async_api import Page
from rich.console import Console

from models import (
    ButtonElement,
    CustomDropdown,
    InputElement,
    LinkElement,
    Observation,
    SelectElement,
    SelectOption,
)

console = Console()


class Observer:
    """Observes and snapshots page state."""

    def __init__(self):
        # Keywords are instance variables for potential customization
        self.postcode_keywords = [
            "postcode",
            "post code",
            "postal code",
            "zip",
            "zip code",
            "your postcode",
            "enter postcode",
            "postcodes",
        ]
        self.address_keywords = [
            "address",
            "house",
            "street",
            "property",
            "building",
            "flat",
            "apartment",
            "dwelling",
            "premises",
        ]
        # Date patterns for detecting actual bin collection dates
        self.date_day_names = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        self.date_month_abbrevs = [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ]
        self.error_keywords = [
            "postcode not found",
            "invalid postcode",
            "postcode is not recognised",
            "postcode not recognised",
            "no addresses found",
            "address not found",
            "no properties found",
        ]

    async def observe(
        self, page: Page, previous_selectors: set[str] | None = None
    ) -> Observation:
        """Create a snapshot of the current page state."""
        url = page.url
        title = await page.title()
        timestamp = datetime.now()

        console.log(f"[dim]Observing page: {url}[/dim]")

        # Get visible text sample
        visible_text = await page.locator("body").text_content() or ""
        visible_text_sample = visible_text[:1000]

        # Find elements
        inputs = await self._find_inputs(page)
        buttons = await self._find_buttons(page)
        links = await self._find_links(page)
        selects = await self._find_selects(page)
        custom_dropdowns = await self._find_custom_dropdowns(page)

        console.log(
            f"[dim]Found {len(inputs)} inputs, {len(buttons)} buttons, {len(links)} links, {len(selects)} selects[/dim]"
        )

        # Detect success and error indicators
        contains_success, success_text = self._detect_success_indicators(visible_text)
        contains_error, error_text = self._detect_error_indicators(visible_text)

        if contains_success:
            console.log(f"[green]✓ Success indicator detected: {success_text}[/green]")
        if contains_error:
            console.log(f"[yellow]! Error indicator detected: {error_text}[/yellow]")

        # Find new elements (stateless - pass in previous selectors)
        if previous_selectors is None:
            previous_selectors = set()

        current_selectors = (
            {inp.selector for inp in inputs}
            | {btn.selector for btn in buttons}
            | {link.selector for link in links}
        )
        new_elements = list(current_selectors - previous_selectors)

        return Observation(
            url=url,
            page_title=title,
            timestamp=timestamp,
            inputs=inputs,
            buttons=buttons,
            links=links,
            selects=selects,
            custom_dropdowns=custom_dropdowns,
            visible_text_sample=visible_text_sample,
            contains_error_message=contains_error,
            error_message_text=error_text,
            contains_success_indicators=contains_success,
            success_indicator_text=success_text,
            new_elements_since_last=new_elements,
        )

    async def _find_inputs(self, page: Page) -> list[InputElement]:
        """Find all text input elements on the page."""
        inputs = []
        selectors = [
            "input[type='text']",
            "input[type='search']",
            "input[type='tel']",
            "input:not([type])",
            "textarea",
        ]

        for selector in selectors:
            count = await page.locator(selector).count()
            for i in range(count):
                try:
                    element = page.locator(selector).nth(i)
                    is_visible = await element.is_visible()
                    if not is_visible:
                        continue

                    # Build a reliable selector: prefer ID > name+type > name+nth > nth
                    elem_id = await element.get_attribute("id")
                    name = await element.get_attribute("name")
                    input_type = await element.get_attribute("type")

                    if elem_id:
                        elem_selector = f"#{elem_id}"
                    elif name:
                        # Check if name is unique to avoid collision
                        name_count = await page.locator(f"[name='{name}']").count()
                        if name_count == 1:
                            # Unique name, safe to use
                            elem_selector = f"[name='{name}']"
                        else:
                            # Multiple elements with same name, need to be more specific
                            if input_type:
                                # Try name + type combination
                                type_name_count = await page.locator(
                                    f"{selector}[name='{name}']"
                                ).count()
                                if type_name_count == 1:
                                    elem_selector = f"{selector}[name='{name}']"
                                else:
                                    # Still not unique, use nth with name as context
                                    elem_selector = (
                                        f"{selector}[name='{name}'] >> nth={i}"
                                    )
                            else:
                                elem_selector = f"[name='{name}'] >> nth={i}"
                    else:
                        # Fallback to nth with selector type
                        elem_selector = f"{selector} >> nth={i}"

                    placeholder = await element.get_attribute("placeholder")
                    value = await element.input_value()
                    is_enabled = await element.is_enabled()
                    is_required = await element.get_attribute("required") is not None
                    pattern = await element.get_attribute("pattern")
                    maxlength_str = await element.get_attribute("maxlength")
                    maxlength = int(maxlength_str) if maxlength_str else None
                    autocomplete = await element.get_attribute("autocomplete")

                    # Get label
                    label_text = await self._get_label_for_element(page, element)
                    nearby_text = await self._get_nearby_text(page, element)

                    inp = InputElement(
                        selector=elem_selector,
                        tag=await element.evaluate("el => el.tagName"),
                        input_type=input_type,
                        id=elem_id,
                        name=name,
                        placeholder=placeholder,
                        label_text=label_text,
                        nearby_text=nearby_text,
                        current_value=value,
                        is_visible=is_visible,
                        is_enabled=is_enabled,
                        is_required=is_required,
                        pattern=pattern,
                        maxlength=maxlength,
                        autocomplete=autocomplete,
                    )

                    # Score relevance
                    inp.relevance_score = self._score_input_relevance(inp)
                    inputs.append(inp)
                except Exception as e:
                    console.log(f"[red]Error processing input element: {e}[/red]")
                    continue

        return inputs

    async def _find_buttons(self, page: Page) -> list[ButtonElement]:
        """Find all clickable buttons on the page."""
        buttons = []
        selectors = ["button", "input[type='submit']", "a[role='button']"]

        for selector in selectors:
            count = await page.locator(selector).count()
            for i in range(count):
                try:
                    element = page.locator(selector).nth(i)
                    is_visible = await element.is_visible()
                    if not is_visible:
                        continue

                    # Build reliable selector: prefer ID > text > nth
                    elem_id = await element.get_attribute("id")
                    text = await element.text_content()
                    button_type = await element.get_attribute("type")
                    is_enabled = await element.is_enabled()

                    if elem_id:
                        elem_selector = f"#{elem_id}"
                    elif text and len(text.strip()) < 50:
                        # Use text-based selector for short, unique text
                        clean_text = text.strip()
                        # Normalize whitespace: collapse multiple spaces/newlines to single space
                        clean_text = " ".join(clean_text.split())
                        clean_text = clean_text.replace('"', '\\"')
                        elem_selector = f'{selector}:has-text("{clean_text}")'
                    else:
                        # Fallback to nth
                        elem_selector = f"{selector} >> nth={i}"

                    # Check if it's a primary button
                    classes = await element.get_attribute("class") or ""
                    is_primary = any(
                        cls in classes.lower()
                        for cls in ["btn-primary", "primary", "main", "cta", "submit"]
                    )

                    btn = ButtonElement(
                        selector=elem_selector,
                        tag=selector.split("[")[0],
                        text=text or "",
                        id=elem_id,
                        type=button_type,
                        is_visible=is_visible,
                        is_enabled=is_enabled,
                        is_primary=is_primary,
                    )

                    # Score relevance
                    btn.relevance_score = self._score_button_relevance(btn)
                    buttons.append(btn)
                except Exception as e:
                    console.log(f"[red]Error processing button element: {e}[/red]")
                    continue

        return buttons

    async def _find_links(self, page: Page) -> list[LinkElement]:
        """Find all relevant navigation links on the page."""
        links = []
        # Only look for <a> tags that are NOT buttons (already captured)
        selector = "a:not([role='button'])"

        count = await page.locator(selector).count()
        for i in range(count):
            try:
                element = page.locator(selector).nth(i)
                is_visible = await element.is_visible()
                if not is_visible:
                    continue

                # Get link properties
                href = await element.get_attribute("href")
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue

                text = await element.text_content()
                if not text or len(text.strip()) == 0:
                    continue

                elem_id = await element.get_attribute("id")

                # Build selector: prefer ID > text > nth
                if elem_id:
                    elem_selector = f"#{elem_id}"
                elif text and len(text.strip()) < 100:
                    clean_text = " ".join(text.strip().split())
                    clean_text = clean_text.replace('"', '\\"')
                    elem_selector = f'a:has-text("{clean_text}")'
                else:
                    elem_selector = f"a >> nth={i}"

                link = LinkElement(
                    selector=elem_selector,
                    href=href,
                    text=text.strip() or "",
                    id=elem_id,
                    is_visible=is_visible,
                )

                # Score relevance
                link.relevance_score = self._score_link_relevance(link)

                # Only include links with some relevance to bins/waste
                if link.relevance_score > 0.1:
                    links.append(link)

            except Exception as e:
                console.log(f"[red]Error processing link element: {e}[/red]")
                continue

        return links

    async def _find_selects(self, page: Page) -> list[SelectElement]:
        """Find all select elements on the page."""
        selects = []
        count = await page.locator("select").count()

        for i in range(count):
            try:
                element = page.locator("select").nth(i)
                is_visible = await element.is_visible()
                if not is_visible:
                    continue

                # Build reliable selector
                elem_id = await element.get_attribute("id")
                name = await element.get_attribute("name")
                is_enabled = await element.is_enabled()

                if elem_id:
                    elem_selector = f"#{elem_id}"
                elif name:
                    elem_selector = f"select[name='{name}']"
                else:
                    elem_selector = f"select >> nth={i}"

                # Get label
                label_text = await self._get_label_for_element(page, element)

                # Get options
                options = []
                option_count = await element.locator("option").count()
                for j in range(option_count):
                    try:
                        option_elem = element.locator("option").nth(j)
                        option_value = await option_elem.get_attribute("value") or ""
                        option_text = await option_elem.text_content() or ""
                        is_placeholder = (
                            "select" in option_text.lower() or option_value == ""
                        )
                        options.append(
                            SelectOption(
                                value=option_value,
                                text=option_text,
                                is_placeholder=is_placeholder,
                            )
                        )
                    except Exception:
                        continue

                # Detect if it looks like addresses
                looks_like_address = any(
                    "street" in opt.text.lower() or "," in opt.text for opt in options
                )

                # Get selected value
                selected = await element.evaluate("el => el.value")

                sel = SelectElement(
                    selector=elem_selector,
                    options=options,
                    id=elem_id,
                    name=name,
                    label_text=label_text,
                    selected_value=selected,
                    is_visible=is_visible,
                    is_enabled=is_enabled,
                    looks_like_address_list=looks_like_address,
                )
                selects.append(sel)
            except Exception as e:
                console.log(f"[red]Error processing select element: {e}[/red]")
                continue

        return selects

    async def _find_custom_dropdowns(self, page: Page) -> list[CustomDropdown]:
        """Find custom (non-native) dropdown elements."""
        dropdowns = []

        # Look for elements with common dropdown patterns
        selectors = [
            "[role='combobox']",
            "[role='listbox']",
            "[aria-haspopup='listbox']",
            ".dropdown",
            ".select",
            ".autocomplete",
        ]

        for selector in selectors:
            try:
                count = await page.locator(selector).count()
                for i in range(count):
                    element = page.locator(selector).nth(i)
                    is_visible = await element.is_visible()
                    if not is_visible:
                        continue

                    # Build reliable selector: prefer ID > aria-label > nth
                    elem_id = await element.get_attribute("id")
                    aria_label = await element.get_attribute("aria-label")

                    if elem_id:
                        elem_selector = f"#{elem_id}"
                    elif aria_label:
                        elem_selector = f"{selector}[aria-label='{aria_label}']"
                    else:
                        # Use Playwright's nth syntax (0-indexed)
                        elem_selector = f"{selector} >> nth={i}"

                    options = await element.evaluate(
                        "el => Array.from(el.querySelectorAll('[role=option], .option, .dropdown-item')).map(o => o.textContent)"
                    )

                    is_open = await element.evaluate(
                        "el => el.getAttribute('aria-expanded') === 'true'"
                    )

                    dropdown = CustomDropdown(
                        trigger_selector=elem_selector,
                        options=options,
                        is_open=is_open,
                        looks_like_address_list=any(
                            "street" in str(opt).lower() or "," in str(opt)
                            for opt in options
                        ),
                    )
                    dropdowns.append(dropdown)
            except Exception as e:
                console.log(f"[red]Error processing custom dropdown: {e}[/red]")
                continue

        return dropdowns

    async def _get_label_for_element(self, page: Page, element) -> str | None:
        """Find label text for an element."""
        try:
            # Try aria-label
            aria_label = await element.get_attribute("aria-label")
            if aria_label:
                return aria_label

            # Try associated label via for attribute
            elem_id = await element.get_attribute("id")
            if elem_id:
                label = page.locator(f"label[for='{elem_id}']")
                # Check if label exists before checking visibility
                label_count = await label.count()
                if label_count > 0 and await label.first.is_visible():
                    return await label.first.text_content()

            # Try parent label
            label = await element.evaluate("el => el.closest('label')?.textContent")
            if label:
                return label
        except Exception:
            pass

        return None

    async def _get_nearby_text(self, page: Page, element) -> str | None:
        """Get text near an element (parent, siblings)."""
        try:
            # Get nearby text from parent and siblings
            text = await element.evaluate(
                """el => {
                let parentText = el.parentElement?.textContent || '';
                let siblingText = '';

                // Get text from previous and next siblings
                if (el.previousElementSibling) {
                    siblingText += el.previousElementSibling.textContent || '';
                }
                if (el.nextElementSibling) {
                    siblingText += ' ' + (el.nextElementSibling.textContent || '');
                }

                return (parentText + ' ' + siblingText).substring(0, 200);
            }"""
            )
            return text if text.strip() else None
        except Exception:
            pass

        return None

    def _score_input_relevance(self, inp: InputElement) -> float:
        """Score how relevant an input is to postcode/address lookup."""
        score = 0.0

        # Check label and placeholder
        combined_text = (
            (inp.label_text or "") + (inp.placeholder or "") + (inp.nearby_text or "")
        )
        combined_text_lower = combined_text.lower()

        for kw in self.postcode_keywords:
            if kw in combined_text_lower:
                score += 0.5
                break

        for kw in self.address_keywords:
            if kw in combined_text_lower:
                score += 0.3
                break

        # Check name/id
        name_id_text = ((inp.name or "") + (inp.id or "")).lower()
        if any(
            kw in name_id_text
            for kw in ["postcode", "postal", "address", "uprn", "property"]
        ):
            score += 0.3

        # Check pattern
        if inp.pattern and "A-Z" in inp.pattern:
            score += 0.4

        # Check maxlength
        if inp.maxlength and 7 <= inp.maxlength <= 10:
            score += 0.2

        # Is empty
        if not inp.current_value:
            score += 0.1

        # Is required
        if inp.is_required:
            score += 0.1

        return min(score, 1.0)

    def _score_button_relevance(self, btn: ButtonElement) -> float:
        """Score how relevant a button is to form submission."""
        score = 0.0
        text_lower = btn.text.lower()

        # Negative scoring for UI chrome (carousel, slides, etc.)
        carousel_terms = [
            "slide",
            "carousel",
            "pause",
            "previous",
            "prev",
            "go to slide",
        ]
        if any(term in text_lower for term in carousel_terms):
            return 0.0  # Zero out carousel buttons completely

        # High priority: bin-specific terms
        bin_terms = [
            "find my bin",
            "collection",
            "bin day",
            "check bins",
            "waste",
            "recycling",
            "bin",
            "rubbish",
        ]
        if any(term in text_lower for term in bin_terms):
            score += 0.5

        # Medium priority: search/lookup terms
        search_terms = [
            "find",
            "search",
            "look up",
            "lookup",
            "submit",
            "check",
            "get",
        ]
        if any(term in text_lower for term in search_terms):
            score += 0.4

        # Lower priority: generic navigation (but not "next" which is often carousel)
        nav_terms = ["continue", "proceed", "confirm"]
        if any(term in text_lower for term in nav_terms):
            score += 0.3

        # Penalize generic "next" unless combined with bin terms
        if "next" in text_lower and not any(term in text_lower for term in bin_terms):
            score -= 0.3

        # Bonus for submit buttons
        if btn.type == "submit":
            score += 0.3

        # Bonus for primary buttons
        if btn.is_primary:
            score += 0.2

        return max(0.0, min(score, 1.0))

    def _score_link_relevance(self, link: LinkElement) -> float:
        """Score how relevant a link is to bin collection lookup."""
        score = 0.0
        text_lower = link.text.lower()
        href_lower = link.href.lower()

        # High priority: links with specific bin/waste lookup language
        high_priority_terms = [
            "find my bin",
            "bin day",
            "bin collection",
            "check my bin",
            "when is my bin",
            "collection day",
            "collection calendar",
            "bin calendar",
            "waste collection",
        ]
        if any(term in text_lower for term in high_priority_terms):
            score += 0.8

        # Medium priority: general bin/waste terms
        bin_terms = ["bin", "waste", "recycling", "rubbish", "refuse", "collection"]
        if any(term in text_lower for term in bin_terms):
            score += 0.4

        # Bonus for waste terms in URL path
        if any(term in href_lower for term in bin_terms):
            score += 0.2

        # Lookup-style terms
        lookup_terms = ["find", "search", "check", "lookup", "when", "my"]
        if any(term in text_lower for term in lookup_terms):
            score += 0.2

        return min(score, 1.0)

    def _detect_success_indicators(self, text: str) -> tuple[bool, str | None]:
        """Detect if page contains success indicators (actual bin collection dates)."""
        text_lower = text.lower()

        # Check for day names
        has_day = any(day in text_lower for day in self.date_day_names)
        if not has_day:
            return False, None

        # Check for month/day pattern (e.g., "15 jan", "jan 15")
        has_date = bool(
            re.search(
                r"\d{1,2}\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
                text_lower,
            )
        )

        if has_day and has_date:
            # Found both day name and date pattern - likely a success page
            return True, "date_pattern_detected"

        return False, None

    def _detect_error_indicators(self, text: str) -> tuple[bool, str | None]:
        """Detect if page contains error indicators."""
        text_lower = text.lower()
        for keyword in self.error_keywords:
            if keyword in text_lower:
                return True, keyword
        return False, None
