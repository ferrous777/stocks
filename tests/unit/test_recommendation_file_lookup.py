import json

import pytest

import app as app_module


@pytest.fixture
def recommendation_files(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, 'RESULTS_DIR', str(tmp_path))
    monkeypatch.setattr(app_module, 'CACHE_DIR', str(tmp_path / 'cache'))
    return tmp_path


def write_recommendation(directory, symbol, date):
    # Only lookup metadata is needed; no price or performance data is fabricated.
    path = directory / f'{symbol}_recommendations_{date}.json'
    path.write_text(json.dumps({'symbol': symbol, 'analysis_date': date}))


@pytest.mark.parametrize('available_date', ['20260517', '20260519'])
def test_dated_request_does_not_substitute_another_date(recommendation_files, available_date):
    write_recommendation(recommendation_files, 'AAPL', available_date)
    response = app_module.app.test_client().get('/api/recommendations/AAPL/20260518')
    assert response.status_code == 404


def test_latest_lookup_uses_recommendation_dates_without_backtests(recommendation_files):
    write_recommendation(recommendation_files, 'AAPL', '20260517')
    write_recommendation(recommendation_files, 'AAPL', '20260519')
    write_recommendation(recommendation_files, 'MSFT', '20260520')
    # Ignore malformed date suffixes, even when they sort after real dates.
    (recommendation_files / 'AAPL_recommendations_latest.json').write_text('not json')
    (recommendation_files / 'AAPL_recommendations_20269999.json').write_text('not json')

    recommendation, date = app_module.get_latest_recommendation('AAPL')

    assert date == '20260519'
    assert recommendation['analysis_date'] == date
    assert recommendation['symbol'] == 'AAPL'


def test_latest_lookup_does_not_relabel_an_older_recommendation(recommendation_files):
    (recommendation_files / 'AAPL_backtest_20260520.json').write_text('{}')
    write_recommendation(recommendation_files, 'AAPL', '20260517')
    recommendation, date = app_module.get_latest_recommendation('AAPL')
    assert date == recommendation['analysis_date'] == '20260517'


def test_latest_lookup_checks_combined_recommendation_files(recommendation_files):
    (recommendation_files / 'recommendations_20260519.json').write_text('{"AAPL": {}}')
    (recommendation_files / 'recommendations_20260520.json').write_text('{"MSFT": {}}')
    recommendation, date = app_module.get_latest_recommendation('AAPL')
    assert date == recommendation['analysis_date'] == '20260519'


def test_missing_symbol_returns_explicit_absence(recommendation_files):
    write_recommendation(recommendation_files, 'MSFT', '20260519')
    assert app_module.get_latest_recommendation('AAPL') == (None, None)


def test_corrupt_latest_file_is_not_hidden_by_older_results(recommendation_files):
    write_recommendation(recommendation_files, 'AAPL', '20260517')
    (recommendation_files / 'AAPL_recommendations_20260519.json').write_text('not json')
    with pytest.raises(json.JSONDecodeError):
        app_module.get_latest_recommendation('AAPL')
