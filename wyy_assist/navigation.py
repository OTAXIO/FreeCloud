from __future__ import annotations

from collections.abc import Collection

from .model import Settings

LOGIC_1_STATES = frozenset({"my_tab", "menu_button", "free_listen_vip"})
LOGIC_2_STATES = frozenset({"home", "free_listen"})
NAVIGATION_STATES = LOGIC_1_STATES | LOGIC_2_STATES
STARTUP_STATES = frozenset({"launcher_icon", "splash_skip"})
AD_ENTRY_STATES = frozenset({"ad", "ad_interaction", "ad_close", "download_prompt", "landing"})


def filter_navigation_states(
    states: Collection[str], navigation_states: Collection[str] = LOGIC_1_STATES,
) -> set[str]:
    return set(states).difference(NAVIGATION_STATES - set(navigation_states))


def application_recognition_states(
    settings: Settings, navigation_states: Collection[str] = LOGIC_1_STATES,
) -> set[str]:
    return filter_navigation_states(settings.templates, navigation_states) - STARTUP_STATES
