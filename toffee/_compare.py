__all__ = ["compare_once"]

from .asynchronous import Component
from .asynchronous import asyncio
from .logger import *


def __default_compare(item1, item2):
    return item1 == item2


def tolerance_compare(tol=0.05):
    """Return a compare function that checks abs(a-b) < tol."""
    def cmp(dut_value, model_value):
        try:
            return abs(float(dut_value) - float(model_value)) < tol
        except (TypeError, ValueError):
            return False
    return cmp


def compare_once(dut_item, std_item, compare=None, match_detail=False):
    if compare is None:
        compare = __default_compare

    if not compare(dut_item, std_item):
        error(
            f"Mismatch\n----- STDOUT -----\n{std_item}\n----- DUTOUT -----\n{dut_item}\n------------------"
        )
        assert False, f"mismatch: {dut_item} != {std_item}"
    else:
        if match_detail:
            info(
                f"Match\n----- STDOUT -----\n{std_item}\n----- DUTOUT -----\n{dut_item}\n------------------"
            )
        else:
            info("Match")
        return True
