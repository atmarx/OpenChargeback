/* OpenChargeback - Minimal JavaScript */

// Auto-dismiss flash messages after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(dismissFlashMessages, 5000);
    initTheme();
    initDropdownClose();
});

// Theme Toggle
function initTheme() {
    var saved = localStorage.getItem('theme');
    if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.documentElement.classList.add('dark');
        updateThemeUI(true);
    }
}

function toggleTheme() {
    var isDark = document.documentElement.classList.toggle('dark');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
    updateThemeUI(isDark);
}

function updateThemeUI(isDark) {
    var icon = document.getElementById('themeIcon');
    var label = document.getElementById('themeLabel');
    if (icon) icon.innerHTML = isDark ? '&#9728;' : '&#9790;';
    if (label) label.textContent = isDark ? 'Light Mode' : 'Dark Mode';
}

// User Dropdown
function toggleUserMenu() {
    var dropdown = document.getElementById('userDropdown');
    if (dropdown) {
        dropdown.classList.toggle('show');
    }
}

function initDropdownClose() {
    document.addEventListener('click', function(e) {
        var container = document.querySelector('.user-menu-container');
        var dropdown = document.getElementById('userDropdown');
        if (container && dropdown && !container.contains(e.target)) {
            dropdown.classList.remove('show');
        }
    });
}

document.body.addEventListener('htmx:afterSwap', function() {
    setTimeout(dismissFlashMessages, 5000);
});

function dismissFlashMessages() {
    document.querySelectorAll('.flash-message').forEach(function(el) {
        el.style.animation = 'slideOut 0.3s ease forwards';
        setTimeout(function() { el.remove(); }, 300);
    });
}

// Checkbox selection helpers
function toggleAll(source) {
    var checkboxes = document.querySelectorAll('input[name="charge_ids"]');
    checkboxes.forEach(function(cb) {
        cb.checked = source.checked;
    });
    updateSelectedCount();
}

function updateSelectedCount() {
    var checked = document.querySelectorAll('input[name="charge_ids"]:checked').length;
    var countEl = document.getElementById('selected-count');
    if (countEl) {
        countEl.textContent = checked + ' selected';
    }
}

// Add event listeners for checkboxes
document.addEventListener('change', function(e) {
    if (e.target.name === 'charge_ids') {
        updateSelectedCount();
    }
});

// htmx configuration
document.body.addEventListener('htmx:configRequest', function(e) {
    // Could add CSRF token here if needed
});

// Handle htmx errors
document.body.addEventListener('htmx:responseError', function(e) {
    console.error('htmx error:', e.detail);
});
