/* Universal right-click context menu + tezkor klaviatura cmd'lari */
(function () {
  let menuEl = null;
  let activeItems = [];

  function ensureMenu() {
    if (menuEl) return menuEl;
    menuEl = document.createElement('div');
    menuEl.className = 'ctx-menu';
    document.body.appendChild(menuEl);
    return menuEl;
  }

  function render(items) {
    const el = ensureMenu();
    el.innerHTML = '';
    items.forEach((it, i) => {
      if (it.sep) {
        const s = document.createElement('div');
        s.className = 'ctx-sep';
        el.appendChild(s);
        return;
      }
      const row = document.createElement('div');
      row.className = 'ctx-item' + (it.danger ? ' ctx-item--danger' : '');
      row.innerHTML =
        (it.icon || '') +
        '<span class="ctx-item-label">' + it.label + '</span>' +
        '<span class="ctx-item-key">' + (it.key || '') + '</span>';
      row.addEventListener('click', () => { hide(); it.action(); });
      el.appendChild(row);
    });
  }

  function show(x, y, items) {
    activeItems = items.filter(i => !i.sep);
    render(items);
    const el = ensureMenu();
    el.classList.add('show');
    const rect = el.getBoundingClientRect();
    const maxX = window.innerWidth - rect.width - 8;
    const maxY = window.innerHeight - rect.height - 8;
    el.style.left = Math.min(x, maxX) + 'px';
    el.style.top = Math.min(y, maxY) + 'px';
  }

  function hide() {
    if (menuEl) menuEl.classList.remove('show');
    activeItems = [];
  }

  document.addEventListener('click', hide);
  document.addEventListener('scroll', hide, true);
  document.addEventListener('keydown', function (e) {
    if (!menuEl || !menuEl.classList.contains('show')) return;
    if (e.key === 'Escape') { hide(); return; }
    const match = activeItems.find(
      it => it.key && it.key.toLowerCase() === e.key.toLowerCase()
    );
    if (match) { e.preventDefault(); hide(); match.action(); }
  });

  window.ctxMenu = { show, hide };
})();
