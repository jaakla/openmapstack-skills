// Run with: node --test tests/site_analytics.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../site/analytics.js', import.meta.url), 'utf8');
const HOME = 'https://jaakla.github.io/openmapstack-skills/';

function element(props) {
  return { ...props, closest(selector) { return (this.matches?.[selector]) || null; } };
}

function boot(options = {}) {
  const scripts = [], listeners = {};
  const navigator = { onLine: true, webdriver: false, userAgent: 'Mozilla/5.0 Chrome/145', ...options.navigator };
  const document = {
    currentScript: { dataset: { release: 'abc123' } },
    referrer: '', head: { append: s => scripts.push(s) }, createElement: () => ({}),
    addEventListener: (name, fn) => { listeners[name] = fn; },
  };
  const window = {};
  const context = vm.createContext({ window, document, navigator, location: new URL(options.href || HOME), URL });
  vm.runInContext(source, context);
  const captures = () => (window.posthog || []).filter(row => row[0] === 'capture' && row[1] !== '$pageview');
  return { window, context, scripts, listeners, captures, config: window.posthog?._i[0][1] };
}

function click(listeners, matches) {
  listeners.click({ target: element({ matches }) });
}

test('development, other hosts, automation and privacy preferences never load the SDK', () => {
  for (const options of [
    { href: 'http://localhost:8000/' }, { href: 'https://other.example/openmapstack-skills/' },
    { href: 'https://jaakla.github.io/openmapstack-samples/' }, { href: 'http://jaakla.github.io/openmapstack-skills/' },
    { navigator: { webdriver: true } }, { navigator: { onLine: false } },
    { navigator: { doNotTrack: '1' } }, { navigator: { globalPrivacyControl: true } },
    { navigator: { userAgent: 'HeadlessChrome/145' } },
  ]) {
    const result = boot(options);
    assert.equal(result.scripts.length, 0, JSON.stringify(options));
    result.window.omsAnalytics.track('demo_opened', { target_site: 'nyc' });
    assert.equal(result.window.posthog, undefined);
  }
});

test('production SDK uses EU, replay off, web vitals on and no autocapture', () => {
  const { scripts, config, context, window } = boot();
  assert.equal(scripts.length, 1);
  assert.equal(scripts[0].async, true);
  assert.equal(config.api_host, 'https://eu.i.posthog.com');
  assert.equal(config.autocapture, false);
  assert.equal(config.disable_session_recording, true);
  assert.equal(config.capture_performance.web_vitals, true);
  assert.equal(config.capture_performance.network_timing, false);
  assert.equal(config.person_profiles, 'never');
  assert.equal(JSON.stringify(window.posthog.find(row => row[0] === 'register')[1]),
    JSON.stringify({ site: 'skills-home', environment: 'production', release: 'abc123' }));
  vm.runInContext(source, context);
  assert.equal(scripts.length, 1);
});

test('outbound payloads drop query strings, fragments, unknown fields and values', () => {
  const { config } = boot();
  const event = config.before_send({ event: 'skill_downloaded', properties: {
    token: 'public', distinct_id: 'anonymous', skill: 'spatial-sql', client: 'SECRET',
    arbitrary: { secret: 'SECRET' }, $set: { email: 'SECRET' },
    $current_url: HOME + '?q=SECRET#install-claude',
    $referrer: 'https://search.example/path?search=SECRET',
  } });
  assert.equal(event.properties.site, 'skills-home');
  assert.equal(event.properties.skill, 'spatial-sql');
  assert.equal(event.properties.$current_url, HOME);
  assert.equal(event.properties.$referrer, 'https://search.example/');
  assert.doesNotMatch(JSON.stringify(event), /SECRET|install-claude|\$set/);
  assert.equal(config.before_send({ event: '$autocapture', properties: {} }), null);
  assert.equal(config.before_send({ event: 'route_search_completed', properties: {} }), null);
});

test('homepage interactions map to fixed, allow-listed events', () => {
  const { listeners, captures } = boot();
  click(listeners, { '.install-tabs [role="tab"]': { id: 'tab-codex' } });
  click(listeners, { '[data-copy]': { dataset: { copy: 'command-claude' } } });
  click(listeners, { 'a[href]': { href: './skills/open-map-stack.zip' } });
  click(listeners, { 'a[href]': { href: './demos/tartu-observable/' } });
  click(listeners, { 'a[href]': { href: 'https://jaakla.github.io/openmapstack-samples/' } });
  click(listeners, { 'a[href]': { href: 'https://github.com/jaakla/openmapstack-skills#install' } });
  click(listeners, { 'a[href]': { href: 'https://cursor.com/docs/skills' } });
  click(listeners, { 'a[href]': { href: './skills/unknown.zip' } });
  assert.deepEqual(JSON.parse(JSON.stringify(captures().map(row => [row[1], row[2]]))), [
    ['feature_used', { feature: 'codex' }],
    ['install_command_copied', { client: 'claude' }],
    ['skill_downloaded', { skill: 'open-map-stack' }],
    ['demo_opened', { target_site: 'tartu-observable' }],
    ['demo_opened', { target_site: 'samples-gallery' }],
    ['repo_opened', {}],
  ]);
});

test('blocked analytics cannot break interactions or grow the SDK queue', () => {
  const { window, scripts, listeners } = boot();
  scripts[0].onerror();
  for (let i = 0; i < 100; i++) click(listeners, { 'a[href]': { href: './demos/nyc/' } });
  assert.equal(window.posthog.length, 0);
});
