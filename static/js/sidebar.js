/* sidebar.js – dropdowns, active states, rail dot, and earnings badge */
(function () {
  const HIDDEN_CLASS = 'hidden';

  document.addEventListener('DOMContentLoaded', () => {
    setupDropdowns();
    highlightActiveNav();
    setupMobileToggle();
    setupEarningsBadge();
    setupReportsBadge();
  });

  // ————————————————— Dropdowns —————————————————
  function setupDropdowns() {
    const dropdownLis = Array.from(
      document.querySelectorAll('.sidebar .nav-list > .nav-item')
    ).filter((li) => li.querySelector(':scope > .dropdown-items'));

    dropdownLis.forEach((li) => {
      const header = li.querySelector(':scope > .nav-link');
      const list   = li.querySelector(':scope > .dropdown-items');
      if (!header || !list) return;

      const caret =
        header.querySelector('.dropdown-caret') ||
        header.querySelector(':scope > svg:last-of-type');

      const open = () => {
        li.classList.add('open', 'active');
        list.classList.remove(HIDDEN_CLASS);
        if (caret) caret.classList.add('rotate-180');
        if (list.classList.contains('rail-list')) ensureRailDot(list, true);
      };

      const close = () => {
        li.classList.remove('open');
        list.classList.add(HIDDEN_CLASS);
        if (caret) caret.classList.remove('rotate-180');
      };

      const toggle = () => {
        if (li.classList.contains('open')) close();
        else {
          // close others
          dropdownLis.forEach((other) => {
            if (other !== li) {
              const ol = other.querySelector(':scope > .dropdown-items');
              const oc = other.querySelector(':scope > .nav-link > svg:last-of-type');
              other.classList.remove('open');
              ol && ol.classList.add(HIDDEN_CLASS);
              oc && oc.classList.remove('rotate-180');
            }
          });
          open();
        }
      };

      // keep inline onclick working, but prefer JS
      window.toggleDropdown = function (triggerEl) {
        const liEl = triggerEl?.closest('.nav-item');
        if (liEl === li) toggle();
      };
      if (!header.hasAttribute('onclick')) {
        header.addEventListener('click', (e) => {
          if (header.tagName !== 'A') e.preventDefault();
          e.stopPropagation();
          toggle();
        });
      }

      // mark active sub-link from URL and auto-open
      const links = list.querySelectorAll('.dropdown-link[href]');
      const currentPath = normalizePath(window.location.pathname);
      let hasActive = false;
      links.forEach((a) => {
        const href = normalizePath(a.getAttribute('href') || '');
        if (href && href === currentPath) {
          const subLi = a.closest('.dropdown-item') || a.parentElement;
          if (subLi) subLi.classList.add('active');
          hasActive = true;
        }
      });
      if (hasActive) open();

      // visual feedback on click before navigation + move dot
      links.forEach((a) => {
        a.addEventListener('click', () => {
          list.querySelectorAll('.dropdown-item').forEach((i) => i.classList.remove('active'));
          const subLi = a.closest('.dropdown-item') || a.parentElement;
          if (subLi) subLi.classList.add('active');
          li.classList.add('active');
          if (!list.classList.contains(HIDDEN_CLASS) && list.classList.contains('rail-list')) {
            ensureRailDot(list, true);
          }
        });
      });

      // reposition the dot when list visibility changes / viewport changes
      if (list.classList.contains('rail-list')) {
        const mo = new MutationObserver(() => ensureRailDot(list, true));
        mo.observe(list, { attributes: true, attributeFilter: ['class'] });
        window.addEventListener('resize', () => ensureRailDot(list, true));
      }
    });
  }

  // ——— Rail dot helpers ———
  function ensureRailDot(listEl, reposition = false) {
    let dot = listEl.querySelector(':scope > .rail-dot');
    if (!dot) {
      dot = document.createElement('span');
      dot.className = 'rail-dot';
      listEl.prepend(dot);
    }
    if (reposition && !listEl.classList.contains(HIDDEN_CLASS)) {
      const li = listEl.querySelector('li.dropdown-item.active') || listEl.querySelector('li.dropdown-item');
      if (li) {
        const y = li.offsetTop + li.offsetHeight / 2;
        dot.style.top = y + 'px';
      }
    }
  }

  // ————————————————— Top-level active highlight —————————————————
  function highlightActiveNav() {
    const current = normalizePath(window.location.pathname);
    const navLinks = document.querySelectorAll('.nav-link[href]');
    navLinks.forEach((link) => {
      const href = normalizePath(link.getAttribute('href') || '');
      if (href && href === current) {
        const item = link.closest('.nav-item');
        if (item && !item.querySelector(':scope > .dropdown-items')) {
          item.classList.add('active');
        }
      }
    });
  }

  // ————————————————— Mobile toggle —————————————————
  function setupMobileToggle() {
    const btn = document.getElementById('mobileMenuToggle');
    const sidebar = document.querySelector('.sidebar');
    if (!btn || !sidebar) return;
    btn.addEventListener('click', () => sidebar.classList.toggle('open'));
  }

  // ————————————————— Earnings badge —————————————————
  function setupEarningsBadge() {
    const badge = document.getElementById('earningsBadge');
    const link  = document.getElementById('earningsNavLink');
    const LS_KEY = 'earningsBadgeCount';

    function render(count) {
      if (!badge) return;
      const n = Math.max(0, Number(count) || 0);
      if (n > 0) {
        badge.textContent = n > 9 ? '9+' : String(n);
        badge.style.display = 'inline-flex';
        badge.classList.remove('hidden');
      } else {
        badge.textContent = '0';
        badge.style.display = 'none';
        badge.classList.add('hidden');
      }
    }
    function setBadge(n, persist = true) {
      render(n);
      if (persist) {
        try { localStorage.setItem(LS_KEY, String(Math.max(0, Number(n) || 0))); } catch {}
      }
    }
    window.setEarningsBadgeCount = setBadge;

    const saved = localStorage.getItem(LS_KEY);
    const fromServer = link?.dataset.pendingCountInitial;

    if (saved !== null && saved !== '0') setBadge(saved, false);
    else if (fromServer && fromServer !== '0') setBadge(fromServer, true);
    else setBadge(0, false);

    (async () => {
      try {
        const resp = await fetch('/api/earnings/pending-count/', { headers: { 'X-Requested-With': 'fetch' } });
        if (resp.ok) {
          const json = await resp.json();
          if (typeof json.count === 'number') setBadge(json.count, true);
        }
      } catch {}
    })();
  }

  // ————————————————— Reports badge —————————————————
  function setupReportsBadge() {
    const badge = document.getElementById('reportsBadge');
    const link  = document.getElementById('reportsNavLink');
    const LS_KEY = 'reportsBadgeCount';

    function render(count) {
      if (!badge) return;
      const n = Math.max(0, Number(count) || 0);
      if (n > 0) {
        badge.textContent = n > 9 ? '9+' : String(n);
        badge.style.display = 'inline-flex';
        badge.classList.remove('hidden');
      } else {
        badge.textContent = '0';
        badge.style.display = 'none';
        badge.classList.add('hidden');
      }
    }
    function setBadge(n, persist = true) {
      render(n);
      if (persist) {
        try { localStorage.setItem(LS_KEY, String(Math.max(0, Number(n) || 0))); } catch {}
      }
    }
    window.setReportsBadgeCount = setBadge;

    const saved = localStorage.getItem(LS_KEY);
    const fromServer = link?.dataset.pendingCountInitial;

    if (saved !== null && saved !== '0') setBadge(saved, false);
    else if (fromServer && fromServer !== '0') setBadge(fromServer, true);
    else setBadge(0, false);

    (async () => {
      try {
        const resp = await fetch('/reports/api/pending-count/', { headers: { 'X-Requested-With': 'fetch' } });
        if (resp.ok) {
          const json = await resp.json();
          if (typeof json.count === 'number') setBadge(json.count, true);
        }
      } catch {}
    })();
  }

  // ————————————————— Helpers —————————————————
  function normalizePath(p) { return String(p || '').replace(/\/+$/, ''); }
})();
