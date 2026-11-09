from umbrielmod.schema import MAX_DIGITS, decimals, format_number


def test_decimals():
    assert decimals(1) == 0
    assert decimals(0.5) == 1
    assert decimals(0.125) == 3
    assert decimals(0.0005) == 4
    assert decimals(1.333333) == 6
    assert decimals(1 / 3) == MAX_DIGITS


def test_format_number_keeps_precision_and_minimum():
    assert format_number(0.125, 2) == "0.125"
    assert format_number(0.0005, 2) == "0.0005"
    assert format_number(0.5, 2) == "0.50"
    assert format_number(250, 1) == "250.0"
    assert format_number(1 / 3, 2) == "0.333333"
    assert format_number(-0.0, 2) == "0.00"
    assert format_number(-1e-9, 1) == "0.0"
    assert format_number(-1.25, 1) == "-1.25"
