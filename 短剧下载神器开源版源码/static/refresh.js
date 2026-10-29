/* Display preferences do not affect downloads or subtitle processing. */
(() => {
  const el = id => document.getElementById(id);
  const read = key => { try { return localStorage.getItem(key) === '1'; } catch (_) { return false; } };
  const save = (key, value) => { try { localStorage.setItem(key, value ? '1' : '0'); } catch (_) {} };
  function navigation(compact) {
    document.body.classList.toggle('sidebar-collapsed', compact);
    const button = el('toggleSidebar');
    button.setAttribute('aria-expanded', String(!compact));
    button.setAttribute('aria-label', compact ? 'Expand navigation' : 'Collapse navigation');
    button.title = compact ? 'Expand navigation' : 'Collapse navigation';
    save('vip_compact_sidebar', compact);
  }
  function library(compact) {
    el('libraryGrid').classList.toggle('compact-library', compact);
    const button = el('libraryDensityToggle');
    button.textContent = compact ? 'Comfortable cards' : 'Compact cards';
    button.setAttribute('aria-pressed', String(compact));
    save('vip_compact_library', compact);
  }
  document.querySelectorAll('.tab[data-tab]').forEach(button => { button.title = button.querySelector('span')?.textContent || ''; });
  navigation(read('vip_compact_sidebar')); library(read('vip_compact_library'));
  el('toggleSidebar').onclick = () => navigation(!document.body.classList.contains('sidebar-collapsed'));
  el('libraryDensityToggle').onclick = () => library(!el('libraryGrid').classList.contains('compact-library'));
})();
