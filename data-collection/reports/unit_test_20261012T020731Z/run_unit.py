# -*- coding: utf-8 -*-
"""전체 단위 시험을 돌리고 시험별 결과를 JSON 으로 남긴다(coverage run 아래에서 실행).

  coverage run -m run_unit <출력 JSON>
"""
import json
import platform
import sys
import time
import unittest
from datetime import datetime, timezone


class Recorder(unittest.TextTestResult):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.rows = []
        self._t = {}

    def startTest(self, test):
        self._t[test.id()] = time.perf_counter()
        super().startTest(test)

    def _add(self, test, outcome, detail=''):
        start = self._t.get(test.id(), time.perf_counter())
        self.rows.append({'id': test.id(), 'outcome': outcome,
                          'seconds': round(time.perf_counter() - start, 4),
                          'detail': detail[:300],
                          'doc': (test.shortDescription() or '')})

    def addSuccess(self, test):
        super().addSuccess(test)
        self._add(test, 'pass')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._add(test, 'fail', self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._add(test, 'error', self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._add(test, 'skip', reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._add(test, 'expected_failure')

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._add(test, 'unexpected_success')


def main(out):
    started = datetime.now(timezone.utc)
    suite = unittest.defaultTestLoader.discover('tests')
    runner = unittest.TextTestRunner(resultclass=Recorder, verbosity=1)
    result = runner.run(suite)
    finished = datetime.now(timezone.utc)
    payload = {
        'started_at': started.isoformat(), 'finished_at': finished.isoformat(),
        'python': sys.version.split()[0], 'platform': platform.platform(),
        'command': 'python -X utf8 -m coverage run -m run_unit (unittest discover -s tests)',
        'total': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'skipped': len(result.skipped), 'successful': result.wasSuccessful(),
        'tests': result.rows,
    }
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
