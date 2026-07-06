/**
 * AI Customer Sentiment — Frontend JavaScript
 * Handles interactivity, API calls, toast notifications, and real-time updates.
 */

// =============================================
// Toast Notification System
// =============================================

function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span>${getToastIcon(type)}</span>
        <span style="flex: 1;">${message}</span>
        <button class="toast-close" onclick="dismissToast(this.parentElement)">×</button>
    `;

    container.appendChild(toast);

    // Auto-dismiss
    setTimeout(() => dismissToast(toast), duration);
}

function dismissToast(toast) {
    if (!toast || toast.classList.contains('removing')) return;
    toast.classList.add('removing');
    setTimeout(() => toast.remove(), 300);
}

function getToastIcon(type) {
    const icons = {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️',
    };
    return icons[type] || icons.info;
}

// =============================================
// Sync Operations
// =============================================

function triggerSync(fullSync = false) {
    const btn = document.getElementById('btn-sync') || document.getElementById('btn-sync-transcripts');
    if (btn) {
        btn.classList.add('loading');
        btn.disabled = true;
    }

    showToast('Starting sync with Fireflies...', 'info');

    fetch('/api/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full_sync: fullSync }),
    })
    .then(r => r.json())
    .then(result => {
        if (btn) {
            btn.classList.remove('loading');
            btn.disabled = false;
        }

        if (result.status === 'completed') {
            showToast(
                `Sync complete! ${result.transcripts_fetched} fetched, ` +
                `${result.transcripts_analyzed} analyzed, ${result.alerts_generated} alerts.`,
                'success', 6000
            );
            // Refresh after short delay
            setTimeout(() => window.location.reload(), 2000);
        } else if (result.status === 'skipped') {
            showToast(result.message, 'warning');
        } else {
            const errorMsg = result.errors && result.errors.length > 0
                ? result.errors[0] : 'Unknown error';
            showToast(`Sync issue: ${errorMsg}`, 'warning', 6000);
            // Still refresh to show any partial results
            setTimeout(() => window.location.reload(), 2000);
        }
    })
    .catch(err => {
        if (btn) {
            btn.classList.remove('loading');
            btn.disabled = false;
        }
        showToast('Sync failed: ' + err.message, 'error');
    });
}

// =============================================
// Mock Data Seeding
// =============================================

function seedMockData() {
    const btn = document.getElementById('btn-seed-mock');
    if (btn) {
        btn.classList.add('loading');
        btn.disabled = true;
    }

    showToast('Loading demo data...', 'info');

    fetch('/api/seed-mock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    })
    .then(r => r.json())
    .then(result => {
        if (btn) {
            btn.classList.remove('loading');
            btn.disabled = false;
        }

        if (result.success) {
            showToast('Demo data loaded! Refreshing...', 'success');
            setTimeout(() => window.location.reload(), 1500);
        } else {
            showToast('Failed to load demo data: ' + (result.error || 'Unknown error'), 'error');
        }
    })
    .catch(err => {
        if (btn) {
            btn.classList.remove('loading');
            btn.disabled = false;
        }
        showToast('Error: ' + err.message, 'error');
    });
}

// =============================================
// Alert Management
// =============================================

function updateAlertStatus(alertId, status) {
    fetch(`/api/alerts/${alertId}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            showToast(`Alert ${status}`, 'success');
            // Animate the card
            const card = document.getElementById(`alert-${alertId}`);
            if (card) {
                card.style.opacity = '0.5';
                card.style.transform = 'translateX(20px)';
            }
            setTimeout(() => window.location.reload(), 1000);
        } else {
            showToast('Failed to update alert', 'error');
        }
    })
    .catch(err => showToast('Error: ' + err.message, 'error'));
}

// =============================================
// Manual Transcripts
// =============================================

function openManualTranscriptModal() {
    const modal = document.getElementById('manual-transcript-modal');
    if (modal) modal.style.display = 'block';
    // Default date to today
    document.getElementById('manual-date').valueAsDate = new Date();
}

function closeManualTranscriptModal() {
    const modal = document.getElementById('manual-transcript-modal');
    if (modal) modal.style.display = 'none';
}

function handleUploadTranscript(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        const text = e.target.result;
        
        // Populate modal
        document.getElementById('manual-content').value = text;
        
        // Optionally set title from filename (remove extension)
        const titleInput = document.getElementById('manual-title');
        titleInput.value = file.name.replace(/\.[^/.]+$/, "");

        // Reset the file input so the same file can be selected again
        event.target.value = '';
        
        // Open the modal
        openManualTranscriptModal();
    };
    reader.readAsText(file);
}

function submitManualTranscript() {
    const title = document.getElementById('manual-title').value;
    const date = document.getElementById('manual-date').value;
    const email = document.getElementById('manual-email').value;
    const content = document.getElementById('manual-content').value;

    if (!content.trim()) {
        showToast('Transcript content is required.', 'error');
        return;
    }

    const btn = document.getElementById('btn-submit-manual');
    btn.classList.add('loading');
    btn.disabled = true;

    showToast('Analyzing manual transcript...', 'info');

    fetch('/api/transcripts/manual', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            title: title,
            date: date,
            organizer_email: email,
            content: content
        })
    })
    .then(r => r.json())
    .then(result => {
        btn.classList.remove('loading');
        btn.disabled = false;

        if (result.success) {
            closeManualTranscriptModal();
            showToast('Transcript analyzed successfully!', 'success');
            setTimeout(() => window.location.href = '/transcript/' + result.transcript_id, 1500);
        } else {
            showToast('Failed to process: ' + result.error, 'error');
        }
    })
    .catch(err => {
        btn.classList.remove('loading');
        btn.disabled = false;
        showToast('Error: ' + err.message, 'error');
    });
}

// =============================================
// Dashboard Auto-Refresh (every 60s)
// =============================================

let refreshInterval = null;

function startAutoRefresh(intervalMs = 60000) {
    // Only on dashboard page
    if (window.location.pathname !== '/') return;

    refreshInterval = setInterval(() => {
        fetch('/api/dashboard/stats')
            .then(r => r.json())
            .then(stats => {
                // Update stat cards
                const total = document.getElementById('stat-total');
                const unhappy = document.getElementById('stat-unhappy');
                const score = document.getElementById('stat-score');
                const alerts = document.getElementById('stat-alerts');

                if (total) animateValue(total, stats.analyzed_transcripts);
                if (unhappy) animateValue(unhappy, stats.unhappy_customers);
                if (score) total.textContent = stats.avg_customer_score.toFixed(2);
                if (alerts) animateValue(alerts, stats.alerts_today);
            })
            .catch(() => {}); // Silently ignore refresh errors
    }, intervalMs);
}

function animateValue(element, newValue) {
    const current = parseInt(element.textContent) || 0;
    if (current === newValue) return;

    element.style.transition = 'transform 0.3s ease, opacity 0.3s ease';
    element.style.transform = 'translateY(-10px)';
    element.style.opacity = '0';

    setTimeout(() => {
        element.textContent = newValue;
        element.style.transform = 'translateY(10px)';
        setTimeout(() => {
            element.style.transform = 'translateY(0)';
            element.style.opacity = '1';
        }, 50);
    }, 300);
}

// =============================================
// Initialize
// =============================================

document.addEventListener('DOMContentLoaded', function() {
    startAutoRefresh();

    // Add keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        // Ctrl+S to sync
        if (e.ctrlKey && e.key === 's') {
            e.preventDefault();
            // On settings page, save settings. Otherwise, trigger sync.
            if (window.location.pathname === '/settings') {
                if (typeof saveSettings === 'function') saveSettings();
            } else {
                triggerSync();
            }
        }
    });
});
