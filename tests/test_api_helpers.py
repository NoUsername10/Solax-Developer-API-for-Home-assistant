from custom_components.solax_developer_api.api import (
    chunked,
    classify_api_code,
    normalize_sn_list,
    split_time_windows,
)


def test_chunked_splits_sequence():
    data = list(range(11))
    chunks = chunked(data, 4)
    assert chunks == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10]]


def test_normalize_sn_list_dedupes_and_trims():
    serials = ["  A ", "a", "B", "", "  ", "b", "C"]
    assert normalize_sn_list(serials) == ["A", "B", "C"]


def test_classify_api_code_mapping():
    assert classify_api_code(10400) == "auth"
    assert classify_api_code(10401) == "auth"
    assert classify_api_code(10402) == "auth"
    assert classify_api_code(10405) == "quota"
    assert classify_api_code(10406) == "rate_limit"
    assert classify_api_code(10403) == "permission"
    assert classify_api_code(10500) == "permission"
    assert classify_api_code(10505) == "permission"
    assert classify_api_code(10506) == "permission"
    assert classify_api_code(10404) == "callback_not_configured"
    assert classify_api_code(10200) == "operation_error"
    assert classify_api_code(10001) == "operation_error"
    assert classify_api_code(11500) == "busy"
    assert classify_api_code(99999) == "api_error"
    assert classify_api_code(None) == "api_error"


def test_split_time_windows_splits_range():
    windows = split_time_windows(0, 2500, 1000)
    assert windows == [(0, 1000), (1000, 2000), (2000, 2500)]


def test_split_time_windows_rejects_invalid_range():
    import pytest

    with pytest.raises(ValueError, match="end_time must be greater than start_time"):
        split_time_windows(10, 10, 1000)
