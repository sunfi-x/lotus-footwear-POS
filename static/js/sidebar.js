// Sidebar toggle & active link highlighting
(function () {
  'use strict';

  const STORAGE_KEY = 'lotus_sidebar_collapsed';
  const body = document.body;
  const sidebar = document.getElementById('sidebar');

  // ── Restore collapse state ────────────────────────────────────────────────
  if (localStorage.getItem(STORAGE_KEY) === '1') {
    body.classList.add('sidebar-collapsed');
  }

  // ── Toggle handler ────────────────────────────────────────────────────────
  const toggleBtn = document.getElementById('sidebar-toggle');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', function () {
      const isCollapsed = body.classList.toggle('sidebar-collapsed');
      localStorage.setItem(STORAGE_KEY, isCollapsed ? '1' : '0');
    });
  }

  // ── Active link highlighting ──────────────────────────────────────────────
  const path = window.location.pathname;
  const links = document.querySelectorAll('.nav-link[href]');

  let bestMatch = null;
  let bestLen   = 0;

  links.forEach(function (link) {
    const href = link.getAttribute('href');
    if (!href || href === '#') return;
    // exact or prefix match — prefer longest match
    if (path === href || (path.startsWith(href) && href !== '/')) {
      if (href.length > bestLen) {
        bestLen   = href.length;
        bestMatch = link;
      }
    } else if (href === '/' && path === '/') {
      bestMatch = link;
      bestLen   = 1;
    }
  });

  if (bestMatch) {
    bestMatch.classList.add('active');
  }

  // ── Keyboard shortcut: Alt+\ to toggle sidebar ───────────────────────────
  document.addEventListener('keydown', function (e) {
    if (e.altKey && (e.key === '\\' || e.key === '|')) {
      e.preventDefault();
      body.classList.toggle('sidebar-collapsed');
      const c = body.classList.contains('sidebar-collapsed');
      localStorage.setItem(STORAGE_KEY, c ? '1' : '0');
    }
  });
})();
