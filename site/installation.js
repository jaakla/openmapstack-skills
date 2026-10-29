// Keep every guide readable when JavaScript is unavailable.
const tablist = document.querySelector('.install-tabs');
const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
const panels = tabs.map((tab) => document.getElementById(tab.getAttribute('aria-controls')));

function activateTab(index, updateHash = false) {
  tabs.forEach((tab, position) => {
    const selected = position === index;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    panels[position].hidden = !selected;
  });
  if (updateHash) {
    history.replaceState(null, '', `#${panels[index].id}`);
    window.omsAnalytics?.track('feature_used', { feature: tabs[index].id.replace(/^tab-/, '') });
  }
}

function selectFromHash() {
  const index = panels.findIndex((panel) => `#${panel.id}` === location.hash);
  if (index !== -1) activateTab(index);
}

panels.forEach((panel, index) => {
  panel.setAttribute('role', 'tabpanel');
  panel.setAttribute('aria-labelledby', tabs[index].id);
  panel.tabIndex = 0;
});
tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => activateTab(index, true));
  tab.addEventListener('keydown', (event) => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    activateTab(next, true);
    tabs[next].focus();
  });
});
activateTab(0);
selectFromHash();
window.addEventListener('hashchange', selectFromHash);
tablist.hidden = false;

const status = document.querySelector('.copy-status');
document.querySelectorAll('[data-copy]').forEach((button) => {
  button.hidden = false;
  button.addEventListener('click', async () => {
    const code = document.getElementById(button.dataset.copy);
    try {
      await navigator.clipboard.writeText(code.textContent);
      status.textContent = 'Copied to clipboard.';
      window.omsAnalytics?.track('install_command_copied', { client: button.dataset.copy.replace(/^command-/, '') });
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(code);
      selection.removeAllRanges();
      selection.addRange(range);
      status.textContent = 'Clipboard unavailable. The text is selected; copy it with Ctrl+C or ⌘C.';
    }
  });
});
