export const weeks = Array.from({ length: 14 }, (_, i) => i + 1);
export const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
export const assessments = module => (module.assessment_types || []).flatMap(group => (group.assessments || []).map(item => ({ ...item, group, module_title: module.module_title })));
export const planItems = record => record.recommendation_payload?.items || (record.recommendation_payload?.weeks || []).flatMap(week => week.items || []);
export const datedPlanItems = (record, unscheduled = []) => {
  const unknownIds = new Set(unscheduled.map(item => item.assessment_id));
  return planItems(record).filter(item => Number.isInteger(item.week) && !unknownIds.has(item.assessment_id));
};
export function weekLabel(schedule) {
  if (schedule?.kind === 'week') return `Week ${schedule.week}`;
  if (schedule?.kind === 'week_range') return `Weeks ${schedule.start_week}–${schedule.end_week}`;
  return schedule?.raw || 'Week unknown';
}
export function weightLabel(item, group = item.group) {
  const value = item.weight_percent;
  if (value == null) return group?.group_weight_percent != null ? `Individual weight unknown · ${group.group_weight_percent}% group total` : 'Weight unknown';
  const scope = item.weight_scope === 'module' ? 'of module' : item.weight_scope_name || item.weight_scope || 'scope unknown';
  return `${value}% ${scope}`;
}
export function capacity(items, budget) {
  return weeks.map(week => {
    const hours = Math.round(items.filter(i => i.week === week).reduce((sum, i) => sum + i.estimated_hours, 0) * 100) / 100;
    return { week, hours, exceeded: hours > budget };
  });
}

export function newestPlan(records = []) {
  return [...records].sort((a, b) => (Date.parse(b.created_at || '') || 0) - (Date.parse(a.created_at || '') || 0) || Number(b.id) - Number(a.id))[0] || null;
}
