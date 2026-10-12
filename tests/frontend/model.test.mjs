import test from 'node:test';
import assert from 'node:assert/strict';
import { capacity, newestPlan, weekLabel, weightLabel, planItems, escape } from '../../frontend/static/model.js';

test('capacity checks aggregate backend plan tasks', () => {
  const totals = capacity([{ week: 4, estimated_hours: 4.5 }, { week: 4, estimated_hours: 4 }, { week: 5, estimated_hours: 8 }], 8);
  assert.equal(totals.length, 14);
  assert.equal(totals[3].hours, 8.5);
  assert.equal(totals[3].exceeded, true);
  assert.equal(totals[4].exceeded, false);
});
test('unknown individual weights preserve group totals without dividing them', () => {
  assert.equal(weightLabel({ weight_percent: null, group: { group_weight_percent: 5 } }), 'Individual weight unknown · 5% group total');
  assert.equal(weightLabel({ weight_percent: 20, weight_scope: 'group', weight_scope_name: 'Project' }), '20% Project');
});
test('API week_range and unknown timing retain their meaning', () => {
  assert.equal(weekLabel({ kind: 'week_range', start_week: 3, end_week: 6 }), 'Weeks 3–6');
  assert.equal(weekLabel({ kind: 'unknown', raw: 'To be announced' }), 'To be announced');
});
test('both recommendation shapes preserve assessment links', () => {
  const item = { assessment_id: 'A-1', title: 'Prepare' };
  assert.deepEqual(planItems({ recommendation_payload: { weeks: [{ week: 1, items: [item] }] } }), [item]);
  assert.deepEqual(planItems({ recommendation_payload: { items: [item] } }), [item]);
});
test('untrusted source wording cannot introduce HTML', () => {
  assert.equal(escape('<script>"x" & \'y\'</script>'), '&lt;script&gt;&quot;x&quot; &amp; &#39;y&#39;&lt;/script&gt;');
});

test('newest generated plan is shown regardless of acceptance status', () => {
  assert.equal(newestPlan([{id: 1, status: 'accepted', created_at: '2026-01-01'}, {id: 2, status: 'candidate', created_at: '2026-02-01'}]).id, 2);
  assert.equal(newestPlan([{id: 3}, {id: 7}]).id, 7);
  assert.equal(newestPlan([]), null);
});
