"""Tests for agent/installation.py — stable installation UUID persistence."""
import json
import sys
import os
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch

# Make agent/ importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import installation


def _stub_data_dir(tmp_path: Path):
    """Patch installation._data_dir to return tmp_path."""
    return patch.object(installation, '_data_dir', return_value=tmp_path)


class TestGetInstallationId(unittest.TestCase):

    def test_first_call_creates_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / 'bh'
            with _stub_data_dir(tmp):
                iid = installation.get_installation_id()
            self.assertTrue((tmp / 'device.json').exists())
            data = json.loads((tmp / 'device.json').read_text())
            self.assertEqual(data['installation_id'], iid)

    def test_idempotent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / 'bh'
            with _stub_data_dir(tmp):
                iid1 = installation.get_installation_id()
                iid2 = installation.get_installation_id()
            self.assertEqual(iid1, iid2)

    def test_survives_bad_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / 'bh'
            tmp.mkdir(parents=True)
            (tmp / 'device.json').write_text('not valid json')
            with _stub_data_dir(tmp):
                iid = installation.get_installation_id()
            # Should have regenerated a valid UUID
            self.assertIsNotNone(uuid.UUID(iid))

    def test_survives_missing_installation_id_key(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / 'bh'
            tmp.mkdir(parents=True)
            (tmp / 'device.json').write_text(json.dumps({'other': 'data'}))
            with _stub_data_dir(tmp):
                iid = installation.get_installation_id()
            # Should have regenerated a valid UUID
            self.assertIsNotNone(uuid.UUID(iid))

    def test_uuid_format(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / 'bh'
            with _stub_data_dir(tmp):
                iid = installation.get_installation_id()
            # Should not raise
            parsed = uuid.UUID(iid)
            self.assertIsNotNone(parsed)

    def test_works_on_windows_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / 'BH_Win'
            with patch.dict(os.environ, {'LOCALAPPDATA': td}):
                with patch.object(sys, 'platform', 'win32'):
                    result = installation._data_dir()
            self.assertEqual(result, Path(td) / 'BuildHarvey')

    def test_data_dir_darwin(self):
        with patch.object(sys, 'platform', 'darwin'):
            result = installation._data_dir()
        self.assertEqual(result, Path.home() / 'Library' / 'Application Support' / 'BuildHarvey')

    def test_data_dir_linux(self):
        with patch.object(sys, 'platform', 'linux'):
            result = installation._data_dir()
        self.assertEqual(result, Path.home() / '.buildharvey-data')


if __name__ == '__main__':
    unittest.main(verbosity=2)
