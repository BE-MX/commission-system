"""Font preflight must fail before a Beijing release can be prepared."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote_backend


class PdfFontPrepareTests(unittest.TestCase):
    def test_incompatible_font_stops_prepare_before_later_release_steps(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / '.deploy_state'
            revision = 'a' * 40
            source = state / 'checkouts' / revision
            for checkout in (root, source):
                backend = checkout / 'backend'
                backend.mkdir(parents=True)
                (backend / 'requirements.txt').write_text('reportlab==4.5.1\n')
            (source / 'backend' / '.env').touch()

            def run(args, **kwargs):
                if args[1:] == ['-m', 'app.invoice.pdf_font']:
                    self.assertEqual(kwargs['cwd'], source / 'backend')
                    raise RuntimeError('ReportLab incompatible font')
                return ''

            with patch.object(remote_backend, 'ROOT', root), patch.object(
                remote_backend, 'STATE', state
            ), patch.object(remote_backend, 'schema_check', return_value={
                'schema': '202', 'pending': []
            }), patch.object(remote_backend, 'run', side_effect=run) as command:
                with self.assertRaisesRegex(RuntimeError, 'incompatible font'):
                    remote_backend.prepare(revision)

            self.assertEqual(command.call_args_list[-1].args[0][1:], [
                '-m', 'app.invoice.pdf_font'
            ])
            self.assertFalse((state / ('backend-prepared-' + revision + '.json')).exists())


if __name__ == '__main__':
    unittest.main()
