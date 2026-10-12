// Run against the Flask frontend. API requests are intercepted; no live AI is used.
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fixture = JSON.parse(await readFile(new URL('./fixture.json', import.meta.url)));
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BROWSER_EXECUTABLE
    ? { executablePath: process.env.BROWSER_EXECUTABLE }
    : {}),
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
let project = null;
let created = 0;
let failProcess = true;
let processBody = '';
let recommendationRequests = 0;
let releaseProcess;
const errors = [];

page.on('pageerror', error => errors.push(error.message));
await page.route('**/api/**', async route => {
  const req = route.request();
  const path = new URL(req.url()).pathname;
  let payload;

  if (path === '/api/projects' && req.method() === 'POST') {
    created++;
    project = {
      ...structuredClone(fixture.project),
      modules: [],
      recommendations: [],
    };
    payload = project;
  } else if (path === '/api/projects') {
    payload = project ? [{ id: 1, name: project.name }] : [];
  } else if (path.endsWith('/process')) {
    processBody = req.postData();
    await new Promise(resolve => { releaseProcess = resolve; });
    if (failProcess) {
      return route.fulfill({
        status: 422,
        json: {
          payload: null,
          errors: ['Could not process screenshots.'],
        },
      });
    }
    project.modules = structuredClone(fixture.project.modules);
    project.recommendations = structuredClone(fixture.project.recommendations);
    return route.fulfill({
      json: {
        payload: {
          modules: project.modules,
          study_plan: project.recommendations[0].recommendation_payload,
        },
        errors: [
          'One screenshot could not be read. Remaining modules are available.',
        ],
      },
    });
  } else if (path.endsWith('/schedule')) {
    payload = fixture.schedule;
  } else if (path.endsWith('/recommendations') && req.method() === 'POST') {
    recommendationRequests++;
    return route.fulfill({
      status: 500,
      json: { payload: null, errors: ['Study plans must be automatic.'] },
    });
  } else {
    payload = project;
  }

  await route.fulfill({ json: { payload, errors: [] } });
});

try {
  await page.goto(process.env.FRONTEND_URL || 'http://127.0.0.1:5173');
  await page.locator('.processing-screen').waitFor({ state: 'detached' });
  await page.getByLabel('Trimester name').fill('Demo trimester');
  await page.getByLabel('Module title').fill('INF1103');
  await page.getByLabel('Assessment screenshots').setInputFiles([
    { name: 'first.png', mimeType: 'image/png', buffer: Buffer.from('first') },
    { name: 'second.png', mimeType: 'image/png', buffer: Buffer.from('second') },
  ]);

  await page.getByRole('button', { name: 'Build assessment schedule' }).click();
  await page.getByRole('status', { name: 'Building your trimester…' }).waitFor();
  assert.match(await page.locator('.processing-screen').innerText(), /generating your study plan/i);
  while (!releaseProcess) await new Promise(resolve => setTimeout(resolve, 10));
  releaseProcess();
  releaseProcess = null;
  await page
    .getByRole('alert')
    .filter({ hasText: 'Could not process screenshots.' })
    .waitFor();
  assert.equal(
    await page.locator('input[type=file]').evaluate(element => element.files.length),
    2,
  );

  failProcess = false;
  await page.getByRole('button', { name: 'Build assessment schedule' }).click();
  await page.getByRole('status', { name: 'Building your trimester…' }).waitFor();
  while (!releaseProcess) await new Promise(resolve => setTimeout(resolve, 10));
  releaseProcess();
  releaseProcess = null;
  await page.getByRole('heading', { name: 'Your assessments.' }).waitFor();
  assert.equal(created, 1);
  assert.match(processBody, /file_fields/);
  assert.match(processBody, /first.png/);
  assert.match(processBody, /second.png/);
  assert.equal(await page.locator('.week-heading').count(), 14);
  assert.match(await page.locator('.week-heading.recess').innerText(), /RECESS\s+7/);
  assert.equal(await page.getByRole('tab', { name: /INF1103/ }).count(), 1);
  assert.equal(await page.getByRole('tabpanel').count(), 1);
  await page.getByRole('heading', { name: 'This week, simply' }).waitFor();
  await page
    .getByText('One screenshot could not be read.', { exact: false })
    .waitFor();

  await page.getByRole('button', { name: 'View study plan' }).click();
  await page.getByRole('heading', { name: 'Suggestions' }).waitFor();
  await page.getByText('Keep Week 7 free for recess.', { exact: true }).waitFor();
  assert.equal(await page.locator('.suggestion-card').count(), 2);
  assert.equal(await page.locator('.workload-week').count(), 0);
  assert.equal(
    await page.getByRole('heading', { name: /Week 7 —/ }).count(),
    0,
  );
  assert.equal(recommendationRequests, 0);
  await page
    .getByRole('heading', { name: /assessment date.*still unknown/ })
    .waitFor();
  assert.equal(await page.locator('.week-plan[open]').count(), 1);

  await page.reload();
  await page.getByText('Keep Week 7 free for recess.', { exact: true }).waitFor();
  await page.getByRole('button', { name: '← Assessments' }).click();
  await page.getByRole('heading', { name: 'Your study focus' }).waitFor();
  assert.equal(await page.evaluate(() => localStorage.length), 0);

  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    true,
  );
  await page.getByRole('button', { name: 'Start again' }).click();
  await page.getByRole('heading', { name: 'Your trimester, made simple.' }).waitFor();
  assert.deepEqual(errors, []);
  console.log(
    'Automatic workflow passed: retry, upload grouping, schedule, recess, AI highlights, weekly plan, reload and mobile.',
  );
} finally {
  await browser.close();
}
