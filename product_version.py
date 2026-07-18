# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""Canonical product identity and semantic version."""

PRODUCT_NAME = "Ladder Dragon"
PRODUCT_SLUG = "LadderDragon"
__version__ = "2.10.30"


def product_label(component: str | None = None) -> str:
    label = f"{PRODUCT_NAME} {__version__}"
    return f"{label} ({component})" if component else label


def user_agent(component: str) -> str:
    return f"{PRODUCT_SLUG}/{__version__} ({component})"
