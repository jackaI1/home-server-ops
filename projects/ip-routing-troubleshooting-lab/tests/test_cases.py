import pytest
from routing_lab.cases import fault_commands, CASES


@pytest.mark.parametrize("name", ["link-down", "mtu-mismatch", "wrong-ospf-area", "bgp-prefix-filter", "session-flap"])
def test_cases_have_reversible_actions(name):
    inject = fault_commands(name, False)
    repair = fault_commands(name, True)
    assert inject and repair and inject != repair
    assert all(router == "pe1" and kind in ("ip", "vtysh") and args for router, kind, args in inject + repair)
    assert CASES[name]["symptoms"] and CASES[name]["fix_check"]


def test_unknown_case_rejected_before_any_command():
    with pytest.raises(ValueError):
        fault_commands("typo", False)
