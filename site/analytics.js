/* Optional PostHog RUM for the public project homepage. The page never depends on it.
 * Shares the EU PostHog project used by jaakla.github.io/openmapstack-samples/. */
(() => {
  'use strict';
  if (window.omsAnalytics) return;
  const token = 'phc_xD88zcSqjcjF2znkMUib6vjghN4CmLpn7CJz3kScQKNz';
  const host = 'https://eu.i.posthog.com';
  const prefix = '/openmapstack-skills/';
  const site = 'skills-home';
  const script = document.currentScript;
  const release = script?.dataset.release || 'unversioned';
  const events = new Set(['feature_used', 'install_command_copied', 'skill_downloaded', 'demo_opened', 'repo_opened']);
  const fields = new Set(['feature', 'client', 'skill', 'target_site']);
  const clients = ['chatgpt', 'claude', 'codex', 'cursor'];
  const skills = ['open-map-stack', 'reproducible-gis-project', 'geospatial-data-discovery', 'spatial-sql'];
  const demos = ['nyc', 'nyc-observable', 'tartu', 'tartu-observable', 'samples-gallery'];
  const enums = new Set([...clients, ...skills, ...demos]);
  function permitted() {
    try {
      return location.protocol === 'https:' && location.hostname === 'jaakla.github.io'
        && (location.pathname === '/openmapstack-skills' || location.pathname.startsWith(prefix))
        && navigator.onLine !== false && !navigator.webdriver
        && !/bot|crawler|spider|headless|playwright|lighthouse/i.test(navigator.userAgent)
        && navigator.doNotTrack !== '1' && !navigator.globalPrivacyControl;
    } catch { return false; }
  }
  function safeURL(value, external = false) {
    try {
      if (!value) return '';
      const url = new URL(value, location.href);
      if (!/^https?:$/.test(url.protocol)) return '';
      // Referring domain is enough for attribution; paths and fragments are dropped.
      return external ? url.origin + '/' : url.origin + url.pathname;
    } catch { return ''; }
  }
  function cleanProperties(properties) {
    const clean = {};
    for (const [key, value] of Object.entries(properties || {})) {
      if (fields.has(key) && typeof value === 'string' && enums.has(value)) clean[key] = value;
    }
    return clean;
  }
  function beforeSend(event) {
    if (!permitted() || !event || !new Set(['$pageview', '$pageleave', '$web_vitals', ...events]).has(event.event)) return null;
    const properties = event.properties || {}, clean = cleanProperties(properties);
    const technical = /^(?:token|distinct_id|\$(?:device_id|session_id|window_id|lib|lib_version|browser|browser_version|browser_language|os|os_version|device_type|screen_width|screen_height|viewport_width|viewport_height|is_identified|time|referring_domain|session_entry_host|session_entry_pathname|web_vitals_[A-Z]+_value|web_vitals_pageview_id|pageview_id))$/;
    for (const [key, value] of Object.entries(properties)) {
      if (technical.test(key) && ['string', 'number', 'boolean'].includes(typeof value)) clean[key] = value;
    }
    clean.$current_url = safeURL(properties.$current_url || location.href) || safeURL(location.href);
    clean.$host = location.host;
    clean.$pathname = new URL(clean.$current_url).pathname;
    for (const key of ['$referrer', '$initial_referrer', '$session_entry_referrer']) {
      if (properties[key]) clean[key] = safeURL(properties[key], true);
    }
    if (properties.$session_entry_url) clean.$session_entry_url = safeURL(properties.$session_entry_url);
    clean.site = site; clean.environment = 'production'; clean.release = release;
    return { ...event, properties: clean };
  }
  function track(name, properties = {}) {
    try {
      if (!permitted() || !events.has(name)) return;
      window.posthog?.capture(name, cleanProperties(properties));
    } catch { /* Analytics must never interrupt installation or navigation. */ }
  }
  window.omsAnalytics = { track, site };
  if (!permitted()) return;

  // Minimal version of PostHog's documented async snippet: queue until SDK loads.
  const posthog = window.posthog = window.posthog || [];
  if (!posthog.__SV) {
    posthog._i = [];
    posthog.init = (key, config) => posthog._i.push([key, config, 'posthog']);
    for (const method of ['capture', 'register']) posthog[method] = (...args) => posthog.push([method, ...args]);
    posthog.__SV = 1;
    const sdk = document.createElement('script');
    sdk.async = true; sdk.crossOrigin = 'anonymous';
    sdk.src = 'https://eu-assets.i.posthog.com/static/array.js';
    sdk.onerror = () => { posthog.length = 0; posthog.capture = () => {}; };
    document.head.append(sdk);
  }
  posthog.init(token, {
    api_host: host, defaults: '2026-08-30',
    autocapture: false, capture_pageview: false, capture_pageleave: true,
    capture_performance: { web_vitals: true, network_timing: false },
    disable_session_recording: true, disable_surveys: true,
    capture_heatmaps: false, capture_dead_clicks: false, capture_exceptions: false,
    enable_recording_console_log: false, rageclick: false, person_profiles: 'never',
    persistence: 'localStorage', cross_subdomain_cookie: false, disableDeviceModel: true,
    save_campaign_params: false, advanced_disable_flags: true, remote_config_refresh_interval_ms: 0,
    before_send: beforeSend,
  });
  posthog.register({ site, environment: 'production', release });
  posthog.capture('$pageview', { $current_url: safeURL(location.href), $referrer: safeURL(document.referrer, true) });

  // Delegated listener only reads element ids/hrefs that the homepage itself defines.
  document.addEventListener('click', event => {
    const target = event.target;
    const tab = target.closest?.('.install-tabs [role="tab"]');
    const client = tab?.id?.replace(/^tab-/, '');
    if (clients.includes(client)) track('feature_used', { feature: client });
    const copy = target.closest?.('[data-copy]');
    const copied = copy?.dataset.copy?.replace(/^command-/, '');
    if (clients.includes(copied)) track('install_command_copied', { client: copied });
    const link = target.closest?.('a[href]');
    if (!link) return;
    let url;
    try { url = new URL(link.href, location.href); } catch { return; }
    const download = /\/skills\/([a-z-]+)\.zip$/.exec(url.pathname)?.[1];
    if (url.hostname === location.hostname && skills.includes(download)) return track('skill_downloaded', { skill: download });
    const demo = url.hostname === location.hostname && url.pathname.startsWith(prefix + 'demos/')
      ? url.pathname.slice((prefix + 'demos/').length).split('/')[0]
      : url.hostname === 'jaakla.github.io' && url.pathname.startsWith('/openmapstack-samples') ? 'samples-gallery' : null;
    if (demos.includes(demo)) return track('demo_opened', { target_site: demo });
    if (url.hostname === 'github.com' && /^\/jaakla\/openmapstack-skills(?:[/#?]|$)/.test(url.pathname)) track('repo_opened');
  });
})();
