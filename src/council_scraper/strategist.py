"""Strategist for planning actions."""

from abc import ABC, abstractmethod

from rich.console import Console

from .models import Action, Config, HistoryEntry, Observation, TestData

console = Console()

# Constants for scoring and filtering
MIN_RELEVANCE_SCORE = 0.3  # Minimum score for inputs/buttons to be considered
MAX_EXPLORATORY_BUTTONS = 3  # Max buttons to try in exploratory mode
RECENT_HISTORY_WINDOW = 5  # Look back this many actions for deduplication
CLICK_RETRY_WINDOW = 2  # Only block clicks if in last N actions


class Rule(ABC):
    """Base class for action proposal rules."""

    @abstractmethod
    def propose(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """Return proposed actions, possibly empty."""
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """Lower numbers = higher priority."""
        pass


class DismissCookieConsentRule(Rule):
    """Dismiss cookie consent banners."""

    @property
    def priority(self) -> int:
        return 1

    def propose(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """Look for cookie consent buttons and propose to click them."""
        candidates = []

        # Look for buttons with cookie-related text
        accept_terms = [
            "accept",
            "agree",
            "ok",
            "got it",
            "allow",
            "consent",
            "accept all",
            "allow all",
            "dismiss",
        ]

        for btn in observation.buttons:
            btn_text_lower = btn.text.lower()
            if any(term in btn_text_lower for term in accept_terms):
                # Check if nearby text suggests this is a cookie banner
                is_cookie_banner = False
                if any(
                    word in observation.visible_text_sample.lower()
                    for word in ["cookie", "privacy", "gdpr", "consent"]
                ):
                    is_cookie_banner = True

                if is_cookie_banner or btn.text == "Accept" or btn.text == "Agree":
                    candidates.append(
                        Action(
                            action_type="click",
                            selector=btn.selector,
                            description=f"Dismiss cookie banner: {btn.text}",
                            confidence=0.9 if is_cookie_banner else 0.7,
                        )
                    )

        return candidates


class FillPostcodeRule(Rule):
    """Fill in a postcode field if found."""

    @property
    def priority(self) -> int:
        return 10

    def propose(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """Find high-relevance empty input and propose to fill with postcode."""
        candidates = []

        # Find highest-relevance empty input
        high_relevance_inputs = sorted(
            [
                inp
                for inp in observation.inputs
                if inp.relevance_score > MIN_RELEVANCE_SCORE and not inp.current_value
            ],
            key=lambda x: x.relevance_score,
            reverse=True,
        )

        if high_relevance_inputs:
            inp = high_relevance_inputs[0]
            candidates.append(
                Action(
                    action_type="fill",
                    selector=inp.selector,
                    value=test_data.test_postcode,
                    description=f"Fill postcode field: {inp.label_text or inp.placeholder or inp.name}",
                    confidence=inp.relevance_score,
                )
            )

        return candidates


class ClickSubmitAfterFillRule(Rule):
    """Click submit button after filling a field."""

    @property
    def priority(self) -> int:
        return 20

    def propose(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """If we just filled something, look for a submit button."""
        candidates = []

        # Check if last action was a fill
        if history and history[-1].action.action_type == "fill":
            # Find high-relevance buttons near the filled input
            high_relevance_buttons = sorted(
                [
                    btn
                    for btn in observation.buttons
                    if btn.relevance_score > MIN_RELEVANCE_SCORE
                ],
                key=lambda x: x.relevance_score,
                reverse=True,
            )

            if high_relevance_buttons:
                btn = high_relevance_buttons[0]
                candidates.append(
                    Action(
                        action_type="click",
                        selector=btn.selector,
                        description=f"Submit form: {btn.text}",
                        confidence=btn.relevance_score,
                    )
                )

        return candidates


class SelectAddressRule(Rule):
    """Select an address from a dropdown if available."""

    @property
    def priority(self) -> int:
        return 30

    def propose(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """Find address-looking select elements and propose to select first option."""
        candidates = []

        for sel in observation.selects:
            if sel.looks_like_address_list and len(sel.options) > 1:
                # Find first non-placeholder option
                for opt in sel.options:
                    if not opt.is_placeholder:
                        candidates.append(
                            Action(
                                action_type="select",
                                selector=sel.selector,
                                value=opt.value or opt.text,
                                description=f"Select address: {opt.text[:50]}",
                                confidence=0.8,
                            )
                        )
                        break

        return candidates


class OpenCustomDropdownRule(Rule):
    """Open a custom dropdown if it's closed."""

    @property
    def priority(self) -> int:
        return 40

    def propose(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """Find closed custom dropdowns and propose to click them."""
        candidates = []

        for dropdown in observation.custom_dropdowns:
            if not dropdown.is_open and dropdown.looks_like_address_list:
                candidates.append(
                    Action(
                        action_type="click",
                        selector=dropdown.trigger_selector,
                        description="Open custom dropdown",
                        confidence=0.7,
                    )
                )

        return candidates


class SelectFromCustomDropdownRule(Rule):
    """Select an option from an open custom dropdown."""

    @property
    def priority(self) -> int:
        return 35

    def propose(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """Find open custom dropdowns and propose to select first option."""
        candidates = []

        for dropdown in observation.custom_dropdowns:
            if (
                dropdown.is_open
                and dropdown.options
                and dropdown.looks_like_address_list
            ):
                # Build a proper selector for the first option
                first_option = dropdown.options[0]
                # Use :has-text or role='option' for better targeting
                option_selector = f"[role='option']:has-text(\"{first_option[:30]}\")"
                candidates.append(
                    Action(
                        action_type="click",
                        selector=option_selector,
                        description=f"Select from custom dropdown: {first_option[:50]}",
                        confidence=0.7,
                    )
                )

        return candidates


class ClickContinueButtonRule(Rule):
    """Click a continue/next button."""

    @property
    def priority(self) -> int:
        return 50

    def propose(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """Find and propose to click continue/next buttons."""
        candidates = []

        continue_terms = ["next", "continue", "proceed", "confirm"]
        for btn in observation.buttons:
            if (
                any(term in btn.text.lower() for term in continue_terms)
                and btn.is_enabled
            ):
                candidates.append(
                    Action(
                        action_type="click",
                        selector=btn.selector,
                        description=f"Click {btn.text}",
                        confidence=0.8,
                    )
                )

        return candidates


class ExploratoryClickRule(Rule):
    """Exploratory clicks on buttons we haven't tried yet."""

    @property
    def priority(self) -> int:
        return 100

    def propose(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """Propose clicks on any buttons we haven't tried yet."""
        candidates = []

        # Get buttons we've already tried
        tried_selectors = {
            entry.action.selector
            for entry in history
            if entry.action.action_type == "click"
        }

        # Find buttons we haven't tried
        untried = [
            btn
            for btn in observation.buttons
            if btn.selector not in tried_selectors and btn.is_enabled
        ]

        # Sort by relevance and return top few
        untried.sort(key=lambda x: x.relevance_score, reverse=True)
        for btn in untried[:MAX_EXPLORATORY_BUTTONS]:
            candidates.append(
                Action(
                    action_type="click",
                    selector=btn.selector,
                    description=f"Try clicking: {btn.text}",
                    confidence=btn.relevance_score * 0.5,
                )
            )

        return candidates


class Strategist:
    """Plans actions based on observations and history."""

    def __init__(self, config: Config):
        self.config = config
        self.rules = self._default_rules()

    def get_actions(
        self,
        observation: Observation,
        history: list[HistoryEntry],
        test_data: TestData,
    ) -> list[Action]:
        """Return prioritised list of candidate actions."""
        all_candidates = []

        for rule in sorted(self.rules, key=lambda r: r.priority):
            candidates = rule.propose(observation, history, test_data)
            all_candidates.extend(candidates)

        console.log(
            f"[dim]Generated {len(all_candidates)} candidate actions from rules[/dim]"
        )

        # Filter already-tried actions
        filtered = self._filter_tried(all_candidates, history, observation)

        console.log(f"[dim]After filtering: {len(filtered)} unique actions[/dim]")

        # Sort by confidence descending
        filtered.sort(key=lambda a: a.confidence, reverse=True)

        if filtered:
            console.log(
                f"[dim]Top action: {filtered[0].description} (confidence: {filtered[0].confidence:.2f})[/dim]"
            )

        return filtered

    def _filter_tried(
        self,
        candidates: list[Action],
        history: list[HistoryEntry],
        observation: Observation,
    ) -> list[Action]:
        """Remove actions we've already tried recently."""
        seen = set()
        result = []

        # Build set of recently tried action keys
        recently_tried = set()
        for entry in history[-RECENT_HISTORY_WINDOW:]:  # Check recent actions
            if entry.action.action_type in ("fill", "select"):
                # For fill/select, exact match on (type, selector, value)
                key = (
                    entry.action.action_type,
                    entry.action.selector,
                    entry.action.value,
                )
                recently_tried.add(key)
            elif entry.action.action_type == "click":
                # For clicks, match on (type, selector) but only if very recent
                # This allows click retries after page changes
                if entry in history[-CLICK_RETRY_WINDOW:]:
                    key = (entry.action.action_type, entry.action.selector, None)
                    recently_tried.add(key)

        for action in candidates:
            # Build key for this action
            if action.action_type in ("fill", "select"):
                key = (action.action_type, action.selector, action.value)
            else:
                # For clicks, normalize value to None
                key = (action.action_type, action.selector, None)

            # Skip if we've tried this recently
            if key in recently_tried:
                continue

            # Skip duplicates within current candidates
            if key in seen:
                continue

            seen.add(key)
            result.append(action)

        return result

    def _default_rules(self) -> list[Rule]:
        return [
            DismissCookieConsentRule(),
            FillPostcodeRule(),
            ClickSubmitAfterFillRule(),
            SelectAddressRule(),
            SelectFromCustomDropdownRule(),
            OpenCustomDropdownRule(),
            ClickContinueButtonRule(),
            ExploratoryClickRule(),
        ]
