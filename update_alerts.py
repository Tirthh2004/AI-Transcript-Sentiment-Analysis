import os

css_append = '''
/* ============================================
   Kanban Board
   ============================================ */
.kanban-board {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-lg);
    align-items: start;
    margin-top: var(--space-lg);
}

.kanban-column {
    background: rgba(243, 240, 251, 0.5);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-lg);
    padding: var(--space-md);
    min-height: 400px;
    display: flex;
    flex-direction: column;
}

.kanban-column-header {
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--text-secondary);
    margin-bottom: var(--space-md);
    padding-bottom: var(--space-sm);
    border-bottom: 2px solid var(--border-subtle);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.kanban-column-header .count {
    background: var(--bg-card);
    padding: 2px 8px;
    border-radius: var(--radius-full);
    font-size: 0.75rem;
    color: var(--text-muted);
}

.kanban-column .alert-card {
    flex-direction: column;
    align-items: stretch;
    padding: var(--space-md);
    margin-bottom: var(--space-md);
}

.kanban-column .alert-card::before {
    top: 0; left: 0; bottom: auto; right: 0;
    height: 3px; width: auto;
}

.kanban-column .alert-icon {
    position: absolute;
    top: var(--space-sm);
    right: var(--space-md);
    font-size: 1.2rem;
    margin: 0;
}

.kanban-column .alert-content {
    margin-top: var(--space-sm);
}

.kanban-column .alert-actions {
    margin-top: var(--space-md);
    padding-top: var(--space-md);
    border-top: 1px solid var(--border-subtle);
    flex-direction: row;
    justify-content: flex-end;
}
'''

with open('static/css/style.css', 'a', encoding='utf-8') as f:
    f.write(css_append)


alerts_html = '''{% extends "base.html" %}
{% block title %}Alerts{% endblock %}

{% block content %}
<div class="page-header">
    <div>
        <h1 class="page-title">🔔 Alerts & Warnings</h1>
        <p class="page-subtitle">Customer sentiment alerts requiring attention</p>
    </div>
    <div class="flex gap-md items-center">
        <div class="flex gap-sm" style="font-size: 0.8rem;">
            <span class="badge badge-none">{{ alert_counts.total }} total</span>
            <span class="badge badge-moderate">{{ alert_counts.new }} new</span>
            <span class="badge badge-positive">{{ alert_counts.resolved }} resolved</span>
        </div>
    </div>
</div>

<!-- Filter Bar -->
<div class="filter-bar">
    <span class="text-muted" style="font-size: 0.8rem; font-weight: 600;">SEVERITY FILTER:</span>
    <a href="/alerts?severity=all" class="filter-btn {% if severity_filter == 'all' %}active{% endif %}">All</a>
    <a href="/alerts?severity=mild" class="filter-btn {% if severity_filter == 'mild' %}active{% endif %}">💡 Mild</a>
    <a href="/alerts?severity=moderate" class="filter-btn {% if severity_filter == 'moderate' %}active{% endif %}">⚠️ Moderate</a>
    <a href="/alerts?severity=severe" class="filter-btn {% if severity_filter == 'severe' %}active{% endif %}">🚨 Severe</a>
</div>

{% set new_alerts = alerts | selectattr('status', 'equalto', 'new') | list %}
{% set ack_alerts = alerts | selectattr('status', 'equalto', 'acknowledged') | list %}
{% set res_alerts = alerts | selectattr('status', 'equalto', 'resolved') | list %}

<!-- Kanban Board -->
<div class="kanban-board">
    <!-- Column: New -->
    <div class="kanban-column">
        <div class="kanban-column-header">
            <span>🔴 New</span>
            <span class="count">{{ new_alerts|length }}</span>
        </div>
        {% for alert in new_alerts %}
            <div class="alert-card severity-{{ alert.severity }}" id="alert-{{ alert.id }}">
                <span class="alert-icon">
                    {% if alert.severity == 'severe' %}🚨
                    {% elif alert.severity == 'moderate' %}⚠️
                    {% else %}💡
                    {% endif %}
                </span>
                <div class="alert-content">
                    <div class="alert-title">
                        <a href="/transcript/{{ alert.transcript_id }}" style="color: var(--text-primary);">
                            {{ alert.title or 'Unknown Call' }}
                        </a>
                    </div>
                    <div class="alert-message" style="max-height: 80px; overflow: hidden;">{{ alert.message }}</div>
                    <div class="alert-meta" style="flex-wrap: wrap;">
                        <span class="badge badge-{{ alert.severity }}">{{ alert.severity }}</span>
                        <span class="badge" style="background: var(--bg-input); color: var(--text-secondary); border: 1px solid var(--border-subtle);">
                            {{ alert.trigger_type }}
                        </span>
                    </div>
                </div>
                <div class="alert-actions">
                    <a href="/transcript/{{ alert.transcript_id }}" class="btn btn-sm btn-secondary">View Call</a>
                    <button class="btn btn-sm btn-secondary" onclick="updateAlertStatus({{ alert.id }}, 'acknowledged')">
                        ✓ Ack
                    </button>
                </div>
            </div>
        {% else %}
            <div class="empty-state" style="padding: 2rem 1rem; min-height: unset;">
                <div class="empty-state-text">No new alerts</div>
            </div>
        {% endfor %}
    </div>

    <!-- Column: Acknowledged -->
    <div class="kanban-column">
        <div class="kanban-column-header">
            <span>🟡 Acknowledged</span>
            <span class="count">{{ ack_alerts|length }}</span>
        </div>
        {% for alert in ack_alerts %}
            <div class="alert-card severity-{{ alert.severity }}" id="alert-{{ alert.id }}">
                <span class="alert-icon">
                    {% if alert.severity == 'severe' %}🚨
                    {% elif alert.severity == 'moderate' %}⚠️
                    {% else %}💡
                    {% endif %}
                </span>
                <div class="alert-content">
                    <div class="alert-title">
                        <a href="/transcript/{{ alert.transcript_id }}" style="color: var(--text-primary);">
                            {{ alert.title or 'Unknown Call' }}
                        </a>
                    </div>
                    <div class="alert-message" style="max-height: 80px; overflow: hidden;">{{ alert.message }}</div>
                    <div class="alert-meta" style="flex-wrap: wrap;">
                        <span class="badge badge-{{ alert.severity }}">{{ alert.severity }}</span>
                        <span class="badge" style="background: var(--bg-input); color: var(--text-secondary); border: 1px solid var(--border-subtle);">
                            {{ alert.trigger_type }}
                        </span>
                    </div>
                </div>
                <div class="alert-actions">
                    <a href="/transcript/{{ alert.transcript_id }}" class="btn btn-sm btn-secondary">View Call</a>
                    <button class="btn btn-sm btn-secondary" onclick="updateAlertStatus({{ alert.id }}, 'resolved')">
                        ✅ Resolve
                    </button>
                </div>
            </div>
        {% else %}
            <div class="empty-state" style="padding: 2rem 1rem; min-height: unset;">
                <div class="empty-state-text">No acknowledged alerts</div>
            </div>
        {% endfor %}
    </div>

    <!-- Column: Resolved -->
    <div class="kanban-column">
        <div class="kanban-column-header">
            <span>🟢 Resolved</span>
            <span class="count">{{ res_alerts|length }}</span>
        </div>
        {% for alert in res_alerts %}
            <div class="alert-card severity-{{ alert.severity }}" id="alert-{{ alert.id }}">
                <span class="alert-icon">
                    {% if alert.severity == 'severe' %}🚨
                    {% elif alert.severity == 'moderate' %}⚠️
                    {% else %}💡
                    {% endif %}
                </span>
                <div class="alert-content">
                    <div class="alert-title">
                        <a href="/transcript/{{ alert.transcript_id }}" style="color: var(--text-primary);">
                            {{ alert.title or 'Unknown Call' }}
                        </a>
                    </div>
                    <div class="alert-message" style="max-height: 80px; overflow: hidden;">{{ alert.message }}</div>
                    <div class="alert-meta" style="flex-wrap: wrap;">
                        <span class="badge badge-{{ alert.severity }}">{{ alert.severity }}</span>
                        <span class="badge" style="background: var(--bg-input); color: var(--text-secondary); border: 1px solid var(--border-subtle);">
                            {{ alert.trigger_type }}
                        </span>
                    </div>
                </div>
                <div class="alert-actions">
                    <a href="/transcript/{{ alert.transcript_id }}" class="btn btn-sm btn-secondary">View Call</a>
                </div>
            </div>
        {% else %}
            <div class="empty-state" style="padding: 2rem 1rem; min-height: unset;">
                <div class="empty-state-text">No resolved alerts</div>
            </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
'''

with open('templates/alerts.html', 'w', encoding='utf-8') as f:
    f.write(alerts_html)
