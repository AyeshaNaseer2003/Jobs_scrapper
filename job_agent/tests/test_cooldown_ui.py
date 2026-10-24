import unittest
from unittest.mock import patch
from Jobs_scrapper.job_agent.interactive import wait_for_cooldown


class CooldownUiTests(unittest.TestCase):
    def test_declining_wait_does_not_sleep(self):
        with patch('job_agent.interactive.time.sleep') as sleep:
            self.assertFalse(wait_for_cooldown(200, read=lambda prompt: 'n'))
            sleep.assert_not_called()

    def test_wait_completes_without_bypassing_deadline(self):
        with patch('job_agent.interactive.time.time', side_effect=[100, 160, 200]), patch('job_agent.interactive.time.sleep') as sleep:
            self.assertTrue(wait_for_cooldown(200, read=lambda prompt: 'y'))
            self.assertEqual(sleep.call_count, 2)
            self.assertTrue(all(call.args[0] <= 30 for call in sleep.call_args_list))
