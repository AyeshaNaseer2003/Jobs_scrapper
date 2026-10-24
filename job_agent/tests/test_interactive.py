from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Jobs_scrapper.job_agent.interactive import wizard
from Jobs_scrapper.job_agent.__main__ import parser, main


class InteractiveTests(unittest.TestCase):
    def answers(self, values):
        return lambda prompt: next(values)

    def test_collect_accepts_defaults_and_search_has_dedicated_folder(self):
        with patch.dict('os.environ', {'JOB_KEYWORDS': 'Python', 'JOB_LOCATION': 'Karachi', 'MAX_JOBS': '25'}):
            args = wizard(self.answers(iter(['', '', '', '', '', ''])))
        parsed = parser().parse_args(args)
        self.assertEqual(parsed.command, 'collect')
        self.assertTrue(parsed.browser)
        self.assertEqual(parsed.keywords, 'Python')
        self.assertEqual(parsed.location, 'Karachi')
        self.assertEqual(parsed.hours, 168)
        self.assertEqual(parsed.max_jobs, 25)
        self.assertEqual(Path(parsed.database).parent, Path(parsed.export_dir))

    def test_bad_numbers_and_boolean_are_reprompted(self):
        args = wizard(self.answers(iter(['1', 'data analyst', 'Remote', '0', 'bad', '3', '-1', '5', 'maybe', 'y'])))
        parsed = parser().parse_args(args)
        self.assertEqual(parsed.hours, 72)
        self.assertEqual(parsed.max_jobs, 5)
        self.assertGreater(parsed.enrichment_limit, 0)

    def test_distinct_searches_do_not_mix_results(self):
        first = parser().parse_args(wizard(self.answers(iter(['1', 'Python', 'Pakistan', '7', '1', 'y']))))
        again = parser().parse_args(wizard(self.answers(iter(['1', 'Python', 'Pakistan', '7', '5', 'y']))))
        other = parser().parse_args(wizard(self.answers(iter(['1', 'Python', 'London', '7', '1', 'y']))))
        self.assertEqual(first.database, again.database)
        self.assertNotEqual(first.database, other.database)

    def test_second_option_runs_tests(self):
        self.assertEqual(wizard(self.answers(iter(['2']))), ['test'])

    def test_quit_and_eof_do_not_start_collection(self):
        self.assertIsNone(wizard(self.answers(iter(['3']))))
        with patch('job_agent.interactive.wizard', side_effect=EOFError), patch('job_agent.__main__.Client') as client:
            self.assertEqual(main([]), 130)
            client.assert_not_called()

    def test_no_arguments_dispatches_to_wizard(self):
        with patch('job_agent.interactive.wizard', return_value=None) as interactive:
            self.assertEqual(main([]), 0)
            interactive.assert_called_once()

    def test_yes_is_rejected_as_location(self):
        args = wizard(self.answers(iter(['1', 'data science', 'yes', 'Pakistan', '30', '100', 'y'])))
        self.assertEqual(parser().parse_args(args).location, 'Pakistan')

    def test_can_cancel_after_reviewing_search(self):
        self.assertIsNone(wizard(self.answers(iter(['1', 'Python', 'Pakistan', '7', '25', 'n']))))


if __name__ == '__main__':
    unittest.main()
