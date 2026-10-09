"""
CSS styles for the CatalogChat Streamlit UI.
"""

"""
Typography:
- Body: Plus Jakarta Sans (300/400/500/600)
- Headings: Space Grotesk (400/500/600)

Color Palette - Clean Blue Theme:
- #5AA9E6 primary, #7FC8F8 secondary, #F9F9F9 background
- #4A93C9 primary-dark, #B8E0FC secondary-light, #FFFFFF surface
- #1A2B3C text, #4A5568 text-light, #8896A6 text-muted
- #48BB78 success, #ECC94B warning, #F56565 error
"""

MAIN_CSS = """
<style>
/* Global Styles */
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600&family=Space+Grotesk:wght@400;500;600&display=swap');

:root {
    --font-body: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --font-heading: 'Space Grotesk', 'Plus Jakarta Sans', sans-serif;
    --color-primary: #5AA9E6;
    --color-primary-dark: #4A93C9;
    --color-primary-darker: #3A7DAD;
    --color-secondary: #7FC8F8;
    --color-secondary-dark: #5BB5F0;
    --color-secondary-light: #B8E0FC;
    --color-background: #F9F9F9;
    --color-surface: #FFFFFF;
    --color-surface-dark: #EDF2F7;
    --color-accent: #5AA9E6;
    --color-accent-dark: #4A93C9;
    --color-success: #48BB78;
    --color-success-dark: #38A169;
    --color-warning: #ECC94B;
    --color-warning-dark: #D69E2E;
    --color-error: #F56565;
    --color-error-dark: #E53E3E;
    --color-text: #1A2B3C;
    --color-text-light: #4A5568;
    --color-text-muted: #8896A6;
}

.stApp {
    font-family: var(--font-body);
    background-color: var(--color-background);
    font-weight: 400;
    letter-spacing: -0.01em;
}

/* Heading typography */
h1, h2, h3, h4, h5, h6,
.card-header,
.stepper-label {
    font-family: var(--font-heading);
}

/* Hide Streamlit branding & reduce top padding */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

.block-container {
    padding-top: 1rem !important;
}

/* ===== Hide Sidebar Completely ===== */
section[data-testid="stSidebar"] {
    display: none !important;
}

/* ===== Horizontal Stepper ===== */

/* Inline step: circle + label side by side */
.stepper-step-inline {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    padding: 0.35rem 0;
}

.stepper-circle {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-family: var(--font-heading);
    font-weight: 500;
    font-size: 0.8rem;
    flex-shrink: 0;
}

.stepper-circle.completed {
    background: var(--color-success);
    color: #FFFFFF;
}

.stepper-circle.active {
    background: var(--color-primary);
    color: #FFFFFF;
    box-shadow: 0 0 0 3px rgba(90, 169, 230, 0.25);
}

.stepper-circle.pending {
    background: var(--color-surface-dark);
    color: var(--color-text-muted);
}

.stepper-label {
    font-size: 0.8rem;
    font-weight: 500;
    white-space: nowrap;
}

.stepper-label.completed {
    color: var(--color-success-dark);
}

.stepper-label.active {
    color: var(--color-primary);
}

.stepper-label.pending {
    color: var(--color-text-muted);
}


/* Connector line between steps */
.stepper-connector-inline {
    height: 2px;
    border-radius: 1px;
    margin-top: 0.2rem;
}

.stepper-connector-inline.completed {
    background: var(--color-success);
}

.stepper-connector-inline.active {
    background: linear-gradient(90deg, var(--color-success), var(--color-primary));
}

.stepper-connector-inline.pending {
    background: var(--color-surface-dark);
}

/* ===== Custom Header ===== */
.main-header {
    padding: 0.5rem 2rem 0.25rem;
    margin-bottom: 0;
    text-align: center;
    background: transparent;
    border: none;
    box-shadow: none;
}

.main-header h1 {
    margin: 0;
    font-family: var(--font-heading);
    font-size: 1.6rem;
    font-weight: 500;
    letter-spacing: -0.02em;
    color: var(--color-text);
    display: inline-block;
    position: relative;
}

.main-header h1::after {
    content: '';
    display: block;
    width: 36px;
    height: 3px;
    background: linear-gradient(90deg, var(--color-primary), var(--color-secondary));
    border-radius: 2px;
    margin: 0.3rem auto 0;
}

.main-header p {
    margin: 0.4rem 0 0;
    color: var(--color-text-muted);
    font-size: 0.8rem;
    font-weight: 300;
    letter-spacing: 0.03em;
    text-transform: uppercase;
}

/* ===== Card Styles ===== */
.card {
    background: var(--color-surface);
    border-radius: 12px;
    padding: 1.5rem;
    box-shadow: 0 2px 8px rgba(26, 43, 60, 0.06);
    margin-bottom: 1rem;
    border: 1px solid var(--color-surface-dark);
}

.card-header {
    font-family: var(--font-heading);
    font-size: 1.05rem;
    font-weight: 500;
    letter-spacing: -0.01em;
    color: var(--color-text);
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

/* ===== Status Badges ===== */
.status-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    font-size: 0.875rem;
    font-weight: 500;
}

.status-pending {
    background: var(--color-surface-dark);
    color: var(--color-text-muted);
}

.status-active {
    background: var(--color-secondary-light);
    color: var(--color-primary-dark);
}

.status-complete {
    background: #C6F6D5;
    color: var(--color-success-dark);
}

.status-error {
    background: #FED7D7;
    color: var(--color-error-dark);
}

/* ===== Progress Indicator ===== */
.progress-container {
    background: var(--color-surface-dark);
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
}

.progress-step {
    display: flex;
    align-items: center;
    padding: 0.75rem;
    margin: 0.5rem 0;
    border-radius: 8px;
    transition: all 0.2s ease;
}

.progress-step.active {
    background: var(--color-secondary-light);
    border-left: 4px solid var(--color-primary);
}

.progress-step.complete {
    background: #C6F6D5;
    border-left: 4px solid var(--color-success);
}

.progress-step.pending {
    opacity: 0.6;
}

.step-number {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 600;
    font-size: 0.875rem;
    margin-right: 0.75rem;
}

.step-number.active {
    background: var(--color-primary);
    color: #FFFFFF;
}

.step-number.complete {
    background: var(--color-success);
    color: #FFFFFF;
}

.step-number.pending {
    background: var(--color-surface-dark);
    color: var(--color-text-muted);
}

/* ===== Decision Card ===== */
.decision-card {
    background: var(--color-surface);
    border: 2px solid var(--color-secondary);
    border-radius: 12px;
    padding: 1.5rem;
    margin: 1rem 0;
}

.decision-prompt {
    font-family: var(--font-heading);
    font-size: 1.05rem;
    font-weight: 500;
    letter-spacing: -0.01em;
    color: var(--color-text);
    margin-bottom: 1rem;
    line-height: 1.5;
}

.decision-context {
    background: var(--color-surface-dark);
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    font-size: 0.9rem;
    color: var(--color-text-light);
    border-left: 4px solid var(--color-primary);
}

/* ===== Option Buttons ===== */
.option-btn {
    display: inline-block;
    padding: 0.75rem 1.5rem;
    border-radius: 8px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
    margin: 0.25rem;
    border: none;
}

.option-btn-primary {
    background: var(--color-primary);
    color: #FFFFFF;
}

.option-btn-primary:hover {
    background: var(--color-primary-dark);
    transform: translateY(-1px);
}

.option-btn-secondary {
    background: var(--color-surface);
    color: var(--color-primary);
    border: 2px solid var(--color-primary);
}

.option-btn-secondary:hover {
    background: rgba(90, 169, 230, 0.08);
    border-color: var(--color-primary-dark);
    color: var(--color-primary-dark);
}

.option-btn-success {
    background: var(--color-success);
    color: #FFFFFF;
}

.option-btn-success:hover {
    background: var(--color-success-dark);
}

.option-btn-warning {
    background: var(--color-warning);
    color: var(--color-text);
}

.option-btn-warning:hover {
    background: var(--color-warning-dark);
}

/* ===== Schema Display ===== */
.schema-container {
    background: #2D3748;
    border-radius: 12px;
    padding: 1.5rem;
    overflow-x: auto;
}

.schema-level {
    margin: 1rem 0;
    padding: 1rem;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 8px;
}

.schema-level-title {
    font-family: var(--font-heading);
    color: var(--color-secondary);
    font-weight: 500;
    font-size: 1rem;
    margin-bottom: 0.75rem;
}

.schema-field {
    display: flex;
    align-items: center;
    padding: 0.5rem;
    margin: 0.25rem 0;
    background: rgba(249, 249, 249, 0.08);
    border-radius: 4px;
    font-family: 'Fira Code', monospace;
    font-size: 0.875rem;
}

.field-name {
    color: var(--color-secondary);
    min-width: 150px;
}

.field-selector {
    color: var(--color-success);
    margin-left: 1rem;
}

/* ===== Sample Data Table ===== */
.sample-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
}

.sample-table th {
    background: var(--color-primary);
    padding: 0.75rem 1rem;
    text-align: left;
    font-weight: 600;
    color: #FFFFFF;
    border-bottom: 2px solid var(--color-primary-dark);
}

.sample-table td {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--color-surface-dark);
    color: var(--color-text);
    background: var(--color-surface);
}

.sample-table tr:hover td {
    background: var(--color-surface-dark);
}

/* ===== Loading Spinner ===== */
.spinner-container {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

.spinner {
    width: 40px;
    height: 40px;
    border: 3px solid var(--color-surface-dark);
    border-top-color: var(--color-primary);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
}

.loading-text {
    margin-left: 1rem;
    color: var(--color-text-muted);
    font-weight: 500;
}

/* ===== Info Box ===== */
.info-box {
    background: var(--color-secondary-light);
    border: 1px solid var(--color-secondary);
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    color: var(--color-text);
}

.info-box-icon {
    margin-right: 0.5rem;
}

/* ===== Success Box ===== */
.success-box {
    background: #C6F6D5;
    border: 1px solid var(--color-success);
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    color: #22543D;
}

/* ===== Warning Box ===== */
.warning-box {
    background: #FEFCBF;
    border: 1px solid var(--color-warning);
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    color: #744210;
}

/* ===== Error Box ===== */
.error-box {
    background: #FED7D7;
    border: 1px solid var(--color-error);
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    color: #742A2A;
}

/* ===== Responsive Design ===== */
@media (max-width: 768px) {
    .main-header {
        padding: 1rem 1.5rem;
    }

    .main-header h1 {
        font-size: 1.3rem;
    }

    .card {
        padding: 1rem;
    }

    .decision-card {
        padding: 1rem;
    }

    .schema-container {
        padding: 1rem;
        font-size: 0.8rem;
    }

    .sample-table {
        font-size: 0.75rem;
    }

    .sample-table th,
    .sample-table td {
        padding: 0.5rem;
    }

    .stepper-circle {
        width: 24px;
        height: 24px;
        font-size: 0.7rem;
    }

    .stepper-label {
        font-size: 0.65rem;
    }

    .stepper-step-inline {
        gap: 0.2rem;
    }
}

/* ===== Custom Streamlit Overrides ===== */
.stApp > header {
    background-color: transparent;
}

.stButton > button {
    font-family: var(--font-heading);
    border-radius: 8px;
    font-weight: 500;
    letter-spacing: 0.01em;
    padding: 0.5rem 1.5rem;
    transition: all 0.2s ease;
}

.stButton > button[kind="primary"] {
    background-color: var(--color-primary);
    color: #FFFFFF;
    border: none;
}

.stButton > button[kind="primary"]:hover {
    background-color: var(--color-primary-dark);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(90, 169, 230, 0.4);
}

.stButton > button[kind="secondary"] {
    background-color: var(--color-surface);
    color: var(--color-primary);
    border: 2px solid var(--color-primary);
}

.stButton > button[kind="secondary"]:hover {
    background-color: rgba(90, 169, 230, 0.08);
    border-color: var(--color-primary-dark);
    color: var(--color-primary-dark);
}

.stTextInput > div > div > input {
    border-radius: 8px;
    border: 2px solid var(--color-surface-dark);
    padding: 0.75rem;
    background-color: var(--color-surface);
}

.stTextInput > div > div > input:focus {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 3px rgba(90, 169, 230, 0.2);
}

.stSelectbox > div > div {
    border-radius: 8px;
}

/* Expander styling */
.streamlit-expanderHeader {
    font-family: var(--font-heading);
    font-weight: 500;
    color: var(--color-text);
    background-color: var(--color-surface);
    border-radius: 8px;
}

/* Tab styling */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background-color: var(--color-surface);
    border-radius: 8px;
    padding: 4px;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 6px;
    padding: 0.5rem 1rem;
}

.stTabs [aria-selected="true"] {
    background-color: var(--color-secondary-light);
}

/* Metric styling */
div[data-testid="metric-container"] {
    background: var(--color-surface);
    border: 1px solid var(--color-surface-dark);
    border-radius: 12px;
    padding: 1rem;
}

div[data-testid="metric-container"] label {
    color: var(--color-text-muted);
}

div[data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: var(--color-text);
}

/* Code block styling */
.stCodeBlock {
    border-radius: 8px;
}

/* JSON display */
.json-display {
    background: #2D3748;
    color: #E2E8F0;
    padding: 1rem;
    border-radius: 8px;
    font-family: 'Fira Code', 'Monaco', monospace;
    font-size: 0.85rem;
    overflow-x: auto;
}

/* Pill/tag styling */
.tag {
    display: inline-block;
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 500;
    margin: 0.125rem;
}

.tag-blue {
    background: var(--color-secondary-light);
    color: var(--color-primary-dark);
}

.tag-green {
    background: #C6F6D5;
    color: var(--color-success-dark);
}

.tag-purple {
    background: #E9D8FD;
    color: #6B46C1;
}

.tag-orange {
    background: #FEEBC8;
    color: #C05621;
}

/* ===== Field Cards ===== */
.field-card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 0.75rem;
    margin: 1rem 0;
}

.field-card {
    background: var(--color-surface);
    border: 1px solid var(--color-surface-dark);
    border-radius: 10px;
    padding: 1rem;
    transition: box-shadow 0.2s ease;
}

.field-card:hover {
    box-shadow: 0 4px 12px rgba(26, 43, 60, 0.1);
}

.field-card-name {
    font-family: var(--font-heading);
    font-weight: 500;
    font-size: 0.95rem;
    color: var(--color-text);
    margin-bottom: 0.3rem;
}

.field-card-sample {
    color: var(--color-text-light);
    font-size: 0.85rem;
    font-style: italic;
    margin: 0.3rem 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
}

.field-card-type {
    display: inline-block;
    background: var(--color-secondary-light);
    color: var(--color-primary-dark);
    padding: 0.1rem 0.5rem;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 500;
}

/* Page preview */
.preview-bar {
    background: var(--color-surface);
    padding: 0.4rem 1rem;
    border-radius: 8px 8px 0 0;
    font-size: 0.8rem;
    color: var(--color-text);
    display: flex;
    align-items: center;
    gap: 0.5rem;
    border: 1px solid var(--color-surface-dark);
    border-bottom: none;
}

.preview-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
}

.preview-dot-red { background: #E74C3C; }
.preview-dot-yellow { background: #F39C12; }
.preview-dot-green { background: #27AE60; }

.preview-url {
    font-family: 'Fira Code', monospace;
    font-size: 0.75rem;
    color: var(--color-text-muted);
    margin-left: 0.5rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* Navigation breadcrumb trail */
.nav-trail {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.4rem;
    padding: 0.75rem 1rem;
    background: var(--color-surface);
    border-radius: 8px;
    margin-bottom: 1rem;
    border: 1px solid var(--color-surface-dark);
}

.nav-trail-level {
    background: #C6F6D5;
    padding: 0.2rem 0.6rem;
    border-radius: 9999px;
    font-size: 0.8rem;
    color: var(--color-success-dark);
}

.nav-trail-current {
    background: var(--color-secondary-light);
    padding: 0.2rem 0.6rem;
    border-radius: 9999px;
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--color-primary-dark);
}

.nav-trail-arrow {
    color: var(--color-text-muted);
    font-size: 0.8rem;
}

/* ===== Depth Indicator ===== */
.depth-indicator {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.6rem 1rem;
    background: var(--color-surface);
    border-radius: 10px;
    border: 1px solid var(--color-surface-dark);
    margin-bottom: 1rem;
}

.depth-dots {
    display: flex;
    align-items: center;
    gap: 0.35rem;
}

.depth-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    transition: all 0.3s ease;
}

.depth-dot.filled {
    background: var(--color-success);
}

.depth-dot.current {
    background: var(--color-primary);
    box-shadow: 0 0 0 3px rgba(90, 169, 230, 0.25);
    animation: depth-pulse 1.8s ease-in-out infinite;
}

.depth-dot.empty {
    background: var(--color-surface-dark);
}

@keyframes depth-pulse {
    0%, 100% { box-shadow: 0 0 0 3px rgba(90, 169, 230, 0.2); }
    50% { box-shadow: 0 0 0 6px rgba(90, 169, 230, 0.35); }
}

.depth-label {
    font-family: var(--font-heading);
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--color-text-light);
    margin-left: 0.25rem;
}

.depth-connector {
    width: 12px;
    height: 2px;
    background: var(--color-surface-dark);
    border-radius: 1px;
}

.depth-connector.filled {
    background: var(--color-success);
}

/* Wizard headers */
.wizard-question {
    font-family: var(--font-heading);
    font-size: 1.5rem;
    font-weight: 500;
    letter-spacing: -0.02em;
    color: var(--color-text);
    margin-bottom: 0.5rem;
    line-height: 1.3;
    text-align: center;
}

.wizard-hint {
    color: var(--color-text-muted);
    font-size: 0.85rem;
    font-weight: 300;
    margin-bottom: 2rem;
    text-align: center;
    max-width: 480px;
    margin-left: auto;
    margin-right: auto;
    line-height: 1.5;
}

/* AI reasoning box */
.ai-reasoning {
    background: var(--color-surface);
    border-left: 4px solid var(--color-primary);
    border-radius: 0 8px 8px 0;
    padding: 1rem 1.25rem;
    margin: 1rem 0;
    color: var(--color-text-light);
    font-size: 0.95rem;
    line-height: 1.5;
}

/* Highlight legend */
.highlight-legend {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.8rem;
    color: var(--color-text-muted);
    padding: 0.3rem 0.6rem;
    background: #FFF5F5;
    border: 1px solid #FED7D7;
    border-radius: 4px;
    margin-bottom: 0.5rem;
}

.highlight-swatch {
    width: 12px;
    height: 12px;
    border: 2px solid #E74C3C;
    border-radius: 2px;
    box-shadow: 0 0 4px rgba(231, 76, 60, 0.4);
}

/* DataFrame styling */
.stDataFrame {
    border: 1px solid var(--color-surface-dark);
    border-radius: 8px;
}

/* Form styling */
[data-testid="stForm"] {
    background-color: var(--color-surface);
    padding: 1.5rem;
    border-radius: 12px;
    border: 1px solid var(--color-surface-dark);
}

/* Radio buttons */
.stRadio > div {
    background-color: var(--color-surface);
    padding: 0.5rem;
    border-radius: 8px;
}

/* Slider */
.stSlider > div > div > div {
    background-color: var(--color-primary);
}

/* Checkbox */
.stCheckbox > label > span {
    color: var(--color-text);
}

/* Text area */
.stTextArea > div > div > textarea {
    background-color: var(--color-surface);
    border: 2px solid var(--color-surface-dark);
    border-radius: 8px;
}

/* Select box */
.stSelectbox > div > div {
    background-color: var(--color-surface);
}

/* Number input */
.stNumberInput > div > div > input {
    background-color: var(--color-surface);
    border: 2px solid var(--color-surface-dark);
    border-radius: 8px;
}

/* Multiselect */
.stMultiSelect > div > div {
    background-color: var(--color-surface);
}

/* Download button */
.stDownloadButton > button {
    background-color: var(--color-primary);
    color: #FFFFFF;
    border: none;
}

.stDownloadButton > button:hover {
    background-color: var(--color-primary-dark);
}
</style>
"""


def get_css() -> str:
    """Return the main CSS styles."""
    return MAIN_CSS
