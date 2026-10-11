# Frontend demo

`timetable.html` is a generated, framework-free snapshot of the latest saved
Logic Manager result. It keeps the first frontend iteration intentionally
small: modules are rows, teaching Weeks 1-14 are columns, and assessments are
selectable priority dots. Module and priority filters narrow the view. The
final `?` column shows assessments whose source did not provide enough week
information.

Regenerate it from a saved CLI result:

```sh
python -m helpers.timetable_renderer stackplan-result.json frontend-demo/timetable.html
```
