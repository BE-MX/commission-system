"""Recovery guards never require production services or databases."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recover_colorwork_order_office as office
import recover_colorwork_order_remote as remote


class RecoveryGuardTests(unittest.TestCase):
    def office_args(self):
        rev, schema = office.REVISION, office.SCHEMA
        return [dict(status='failed', revision=rev, completed=['office']),
                dict(status='upgraded', schema=schema, database='159_storage_transfers', pending=[schema]),
                dict(revision=rev, schema=schema), rev, rev, remote.PREVIOUS]

    def test_inspected_office_interruption_is_accepted(self):
        office.validate(*self.office_args())

    def test_other_release_states_are_rejected(self):
        for index, key, value in [(0, 'status', 'succeeded'), (0, 'revision', 'a' * 40),
                                 (0, 'completed', []), (1, 'status', 'running-ddl'),
                                 (1, 'schema', '159_storage_transfers'),
                                 (1, 'pending', []), (1, 'database', '158'),
                                 (2, 'schema', '159_storage_transfers')]:
            with self.subTest(key=key, value=value):
                args = self.office_args()
                args[index][key] = value
                with self.assertRaises(RuntimeError):
                    office.validate(*args)

    def test_source_drift_is_rejected(self):
        for dirty in [('changed', ''), ('', 'changed')]:
            with self.assertRaises(RuntimeError):
                office.validate(*self.office_args(), *dirty)
        args = self.office_args()
        args[5] = 'c' * 40
        with self.assertRaises(RuntimeError):
            office.validate(*args)

    def remote_args(self):
        source = Path('/safe/candidate')
        return [dict(revision=remote.REVISION, previous=remote.PREVIOUS,
                     schema=remote.SCHEMA, schema_changed=True, environment=None),
                dict(status='failed', source=str(source)), source, remote.PREVIOUS, '']

    def test_inspected_remote_interruption_is_accepted(self):
        remote.validate(*self.remote_args())

    def test_unreviewed_environment_or_failed_candidate_is_rejected(self):
        for index, key, value in [(0, 'environment', '/another/venv'),
                                 (0, 'schema_changed', False),
                                 (0, 'previous', 'c' * 40),
                                 (1, 'status', 'activating'),
                                 (1, 'source', '/another/candidate')]:
            args = self.remote_args()
            args[index][key] = value
            with self.subTest(key=key):
                with self.assertRaises(RuntimeError):
                    remote.validate(*args)

    def test_wrong_recovery_revision_is_rejected_before_accessing_hosts(self):
        with self.assertRaises(ValueError):
            remote.execute({'revision': 'a' * 40})


if __name__ == '__main__':
    unittest.main()
