#!/usr/bin/env python3
"""
JuhRadial MX - Dialog Windows (re-export shim)

Re-exports all dialog classes from their sharded modules so that existing
imports like ``from settings_dialogs import ButtonConfigDialog`` keep working.

SPDX-License-Identifier: GPL-3.0
"""

from settings_dialog_button import ButtonConfigDialog  # noqa: F401
from settings_dialog_radial import (  # noqa: F401
    RadialMenuConfigDialog,
    SliceConfigDialog,
)
from settings_dialog_apps import (  # noqa: F401
    AddApplicationDialog,
    ApplicationProfilesGridDialog,
    AppProfileSlicesDialog,
)
