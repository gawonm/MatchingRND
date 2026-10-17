import assert from 'node:assert/strict';
import test from 'node:test';
import { finishReport, startReport } from '../src/state/analysisReports.ts';

const report = method => ({ method, status: 'ok', markdown: '# 결과', claims: [], evidence: [], warnings: [], stats: {} });

test('프로필별 보고서와 로딩·오류·재시도 상태를 격리한다', () => {
  let entries = startReport({}, 'profile-1:1', 1);
  entries = startReport(entries, 'profile-2:2', 2);
  entries = finishReport(entries, 'profile-1:1', 1, report('first'));
  entries = finishReport(entries, 'profile-2:2', 2, null);
  assert.equal(entries['profile-1:1'].result.method, 'first');
  assert.equal(entries['profile-1:1'].status, 'idle');
  assert.equal(entries['profile-2:2'].status, 'error');

  entries = startReport(entries, 'profile-2:2', 3);
  entries = finishReport(entries, 'profile-2:2', 3, report('retry'));
  assert.equal(entries['profile-2:2'].result.method, 'retry');
});

test('이전 요청 응답은 같은 프로필의 최신 요청을 덮지 않는다', () => {
  let entries = startReport({}, 'profile-1:1', 1);
  entries = startReport(entries, 'profile-1:1', 2);
  const unchanged = finishReport(entries, 'profile-1:1', 1, report('stale'));
  assert.equal(unchanged, entries);
  entries = finishReport(entries, 'profile-1:1', 2, report('latest'));
  assert.equal(entries['profile-1:1'].result.method, 'latest');
});
