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

// Review page - Checkbox selection helpers
function toggleAll(source) {
    var checkboxes = document.querySelectorAll('.charge-checkbox');
    checkboxes.forEach(function(cb) {
        cb.checked = source.checked;
    });
    updateSelectedCount();
}

function updateSelectedCount() {
    var checkboxes = document.querySelectorAll('.charge-checkbox:checked');
    var count = checkboxes.length;
    var countSpan = document.getElementById('selected-count');
    if (countSpan) {
        countSpan.textContent = count + ' selected';
    }

    var approveBtn = document.getElementById('approve-selected-btn');
    var rejectBtn = document.getElementById('reject-selected-btn');

    // Toggle disabled class (not attribute - htmx interferes with disabled attribute)
    if (approveBtn) {
        if (count === 0) {
            approveBtn.classList.add('btn-disabled');
        } else {
            approveBtn.classList.remove('btn-disabled');
        }
    }
    if (rejectBtn) {
        if (count === 0) {
            rejectBtn.classList.add('btn-disabled');
        } else {
            rejectBtn.classList.remove('btn-disabled');
        }
    }

    // Update select-all checkbox state
    var allCheckboxes = document.querySelectorAll('.charge-checkbox');
    var selectAll = document.getElementById('select-all');
    if (selectAll && allCheckboxes.length > 0) {
        selectAll.checked = checkboxes.length === allCheckboxes.length;
        selectAll.indeterminate = checkboxes.length > 0 && checkboxes.length < allCheckboxes.length;
    }
}

function submitBulkAction(actionUrl, confirmMsg) {
    var checkboxes = document.querySelectorAll('.charge-checkbox:checked');

    if (checkboxes.length === 0) {
        return;
    }

    if (confirmMsg && !confirm(confirmMsg)) {
        return;
    }

    // Create a new form dynamically to bypass htmx
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = actionUrl;
    form.style.display = 'none';

    // Add charge_ids as hidden inputs
    checkboxes.forEach(function(cb) {
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'charge_ids';
        input.value = cb.value;
        form.appendChild(input);
    });

    // Append to body, submit, then remove
    document.body.appendChild(form);
    form.submit();
}

function updateTotalCount() {
    var rows = document.querySelectorAll('#review-table-body tr:not(.empty-row)');
    var count = rows.length;
    var subtitle = document.querySelector('.page-subtitle');
    if (subtitle && subtitle.textContent.includes('review')) {
        var periodText = subtitle.textContent.includes('in ') ? subtitle.textContent.split('in ')[1] : '';
        subtitle.textContent = count + ' charge' + (count !== 1 ? 's' : '') + ' need' + (count === 1 ? 's' : '') + ' review' + (periodText ? ' in ' + periodText : '');
    }

    // Update Approve All button count
    var approveAllBtn = document.querySelector('.page-header .btn-success');
    if (approveAllBtn && approveAllBtn.textContent.includes('Approve All')) {
        if (count > 0) {
            approveAllBtn.textContent = 'Approve All (' + count + ')';
            approveAllBtn.onclick = function() { return confirm('Approve all ' + count + ' flagged charges?'); };
        } else {
            approveAllBtn.style.display = 'none';
        }
    }

    // Update sidebar badge
    var sidebarBadge = document.querySelector('.sidebar .nav-item[href="/review"] .badge');
    if (sidebarBadge) {
        if (count > 0) {
            sidebarBadge.textContent = count;
        } else {
            sidebarBadge.remove();
        }
    }

    // Show empty state if no more charges
    if (count === 0) {
        var tableBody = document.getElementById('review-table-body');
        if (tableBody) {
            tableBody.innerHTML = '<tr class="empty-row"><td colspan="7" style="text-align: center; padding: 40px;"><div class="icon">&#10003;</div><h3>All caught up!</h3><p class="text-muted">No more charges to review.</p></td></tr>';
        }
    }
}

// Add event listeners for checkboxes (using event delegation)
document.addEventListener('change', function(e) {
    if (e.target.classList.contains('charge-checkbox')) {
        updateSelectedCount();
    }
});

// Initialize review page on load and after htmx swaps
function initReviewPage() {
    if (document.getElementById('review-table-body')) {
        updateSelectedCount();
    }
}

// Run on DOMContentLoaded
document.addEventListener('DOMContentLoaded', initReviewPage);

// Run after htmx content swaps
document.body.addEventListener('htmx:afterSettle', initReviewPage);

// Update counts after individual approve/reject actions
document.body.addEventListener('htmx:afterRequest', function(event) {
    var path = event.detail.pathInfo ? event.detail.pathInfo.requestPath : '';
    if (path && (path.includes('/approve') || path.includes('/reject'))) {
        setTimeout(function() {
            updateSelectedCount();
            updateTotalCount();
        }, 50);
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
