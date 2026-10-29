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
  return { window, document, navigator, context, scripts, listeners, captures, config: window.posthog?._i[0][1] };
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
  for (const flag of [undefined, true, false]) {
    const properties = flag === undefined ? {} : { $process_person_profile: flag };
    for (const name of ['$pageview', '$pageleave', '$web_vitals', 'demo_opened']) {
      assert.equal(config.before_send({ event: name, properties }).properties.$process_person_profile, false);
    }
  }
  assert.equal(config.before_send({ event: '$autocapture', properties: {} }), null);
  assert.equal(config.before_send({ event: 'route_search_completed', properties: {} }), null);
});

test('homepage interactions map to fixed, allow-listed events', () => {
  const { listeners, captures } = boot();
  click(listeners, { 'a[href]': { href: './skills/open-map-stack.zip' } });
  click(listeners, { 'a[href]': { href: './demos/tartu-observable/' } });
  click(listeners, { 'a[href]': { href: 'https://jaakla.github.io/openmapstack-samples/' } });
  click(listeners, { 'a[href]': { href: 'https://github.com/jaakla/openmapstack-skills#install' } });
  click(listeners, { 'a[href]': { href: 'https://cursor.com/docs/skills' } });
  click(listeners, { 'a[href]': { href: './skills/unknown.zip' } });
  assert.deepEqual(JSON.parse(JSON.stringify(captures().map(row => [row[1], row[2]]))), [
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

// Exercise the actual installation script: pointer intent alone is not a copy.
function installation(options = {}) {
  const state = boot();
  const clients = ['chatgpt', 'claude', 'codex', 'cursor'];
  function node(id) {
    return { id, hidden: false, handlers: {}, attributes: {}, dataset: {},
      setAttribute(name, value) { this.attributes[name] = value; },
      getAttribute(name) { return this.attributes[name]; },
      addEventListener(name, handler) { this.handlers[name] = handler; }, focus() {},
    };
  }
  const panels = clients.map(client => node('install-' + client));
  const tabs = clients.map((client, index) => {
    const tab = node('tab-' + client); tab.attributes['aria-controls'] = panels[index].id; return tab;
  });
  const buttons = clients.map(client => {
    const button = node('copy-' + client); button.dataset.copy = 'command-' + client; return button;
  });
  const commands = clients.map(client => ({ id: 'command-' + client, textContent: 'PRIVATE COMMAND' }));
  const elements = [...panels, ...tabs, ...commands];
  const status = { textContent: '' };
  state.document.querySelector = selector => selector === '.install-tabs'
    ? { querySelectorAll: () => tabs } : status;
  state.document.querySelectorAll = () => buttons;
  state.document.getElementById = id => elements.find(element => element.id === id);
  state.document.createRange = () => ({ selectNodeContents() {} });
  state.window.addEventListener = () => {};
  state.window.getSelection = () => ({ removeAllRanges() {}, addRange() {} });
  state.context.history = { replaceState() {} };
  state.navigator.clipboard = { writeText: async () => {
    if (options.clipboardFails) throw new Error('Clipboard denied');
  } };
  vm.runInContext(readFileSync(new URL('../site/installation.js', import.meta.url), 'utf8'), state.context);
  return { ...state, panels, tabs, buttons, status };
}

test('only a successful clipboard write records a copied command', async () => {
  const success = installation();
  await success.buttons[2].handlers.click();
  assert.equal(success.status.textContent, 'Copied to clipboard.');
  assert.equal(success.captures().length, 1);
  assert.equal(success.captures()[0][1], 'install_command_copied');
  assert.equal(success.captures()[0][2].client, 'codex');
  assert.doesNotMatch(JSON.stringify(success.captures()), /PRIVATE COMMAND/);
  const failure = installation({ clipboardFails: true });
  await failure.buttons[2].handlers.click();
  assert.match(failure.status.textContent, /Clipboard unavailable/);
  assert.equal(failure.captures().length, 0);
  // Bubbling pointer events cannot report success independently of the handler.
  click(failure.listeners, { '[data-copy]': failure.buttons[2] });
  assert.equal(failure.captures().length, 0);
});

test('keyboard and pointer installation selection each record the activated client once', () => {
  const state = installation();
  assert.equal(state.captures().length, 0, 'initial default is not user activity');
  state.tabs[0].handlers.keydown({ key: 'End', preventDefault() {} });
  assert.equal(state.panels[3].hidden, false);
  assert.equal(state.tabs[3].attributes['aria-selected'], 'true');
  assert.equal(state.captures().length, 1);
  assert.equal(state.captures()[0][2].feature, 'cursor');
  state.tabs[2].handlers.click();
  click(state.listeners, { '.install-tabs [role="tab"]': state.tabs[2] });
  assert.equal(state.panels[2].hidden, false);
  assert.equal(state.captures().length, 2, 'bubbling click must not double count');
  assert.equal(state.captures()[1][2].feature, 'codex');
});


test('navigation events dispatch immediately with the unload-safe transport', () => {
  const { window, captures } = boot();
  for (const event of ['demo_opened', 'repo_opened', 'skill_downloaded']) {
    window.omsAnalytics.track(event);
    const options = captures().at(-1)[3];
    assert.equal(options.transport, 'sendBeacon');
    assert.equal(options.send_instantly, true);
  }
  window.omsAnalytics.track('feature_used', { feature: 'codex' });
  assert.equal(captures().at(-1)[3], undefined, 'non-navigation activity stays batched');
});
