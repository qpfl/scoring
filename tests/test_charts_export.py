import json

from qpfl import charts
from scripts import export_charts


def test_build_charts_stamps_the_season_and_week():
    block = charts.build_charts([], [], current_season=2026, completed_through=10)
    assert block == {
        'version': charts.CHARTS_VERSION,
        'season': 2026,
        'completed_through': 10,
    }


def test_export_writes_charts_json(tmp_path, monkeypatch):
    output = tmp_path / 'charts.json'
    monkeypatch.setattr(export_charts, 'load_history', lambda season, week: ([], [], {}, {}))
    monkeypatch.setattr(
        'sys.argv',
        [
            'export_charts.py',
            '--current-season',
            '2026',
            '--completed-through',
            '3',
            '--output',
            str(output),
        ],
    )
    export_charts.main()
    written = json.loads(output.read_text())
    assert written['completed_through'] == 3 and 'generated_at' in written

    # A rerun with the same data leaves the file (and its timestamp) alone.
    stamp = written['generated_at']
    export_charts.main()
    assert json.loads(output.read_text())['generated_at'] == stamp
