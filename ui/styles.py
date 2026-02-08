"""
CSS styles for the CatalogChat Streamlit UI.
"""

"""
Color Palette - Data Exploration Theme:
Base colors provided:
- #96B6C5 - Muted teal-blue (primary actions)
- #ADC4CE - Light blue-gray (secondary, header)
- #EEE0C9 - Warm beige (cards, surfaces)
- #F1F0E8 - Warm light gray (main background)

Added for harmony:
- #7A9AA8 - Dark teal (primary hover)
- #C9B896 - Warm sand (current step highlight)
- #A8BFA8 - Muted sage (success/completed)
- #3A4A50 - Dark slate (text)
"""

MAIN_CSS = """
<style>
/* Global Styles */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
    --color-primary: #96B6C5;
    --color-primary-dark: #7A9AA8;
    --color-primary-darker: #5E7E8C;
    --color-secondary: #ADC4CE;
    --color-secondary-dark: #8BAAB6;
    --color-background: #F1F0E8;
    --color-surface: #EEE0C9;
    --color-surface-dark: #E0D0B8;
    --color-accent: #C9B896;
    --color-accent-dark: #B0A080;
    --color-success: #A8BFA8;
    --color-success-dark: #8AA88A;
    --color-text: #3A4A50;
    --color-text-light: #5A6A70;
    --color-text-muted: #7A8A90;
}

.stApp {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background-color: var(--color-background);
}

/* Hide Streamlit branding */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

/* Custom Header */
.main-header {
    background: var(--color-secondary);
    padding: 2rem;
    border-radius: 12px;
    margin-bottom: 2rem;
    color: var(--color-text);
    text-align: center;
    border: 1px solid var(--color-secondary-dark);
}

.main-header h1 {
    margin: 0;
    font-size: 2.5rem;
    font-weight: 700;
    color: var(--color-text);
}

.main-header p {
    margin: 0.5rem 0 0;
    color: var(--color-text-light);
    font-size: 1.1rem;
}

/* Card Styles */
.card {
    background: var(--color-surface);
    border-radius: 12px;
    padding: 1.5rem;
    box-shadow: 0 2px 8px rgba(58, 74, 80, 0.06);
    margin-bottom: 1rem;
    border: 1px solid var(--color-surface-dark);
}

.card-header {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

/* Status Badges */
.status-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    font-size: 0.875rem;
    font-weight: 500;
}

.status-pending {
    background: var(--color-background);
    color: var(--color-text-light);
}

.status-active {
    background: var(--color-primary);
    color: var(--color-primary-darker);
}

.status-complete {
    background: var(--color-secondary);
    color: #5A6A58;
}

.status-error {
    background: #F5D5D5;
    color: #8A4A4A;
}

/* Progress Indicator */
.progress-container {
    background: var(--color-background);
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
    background: var(--color-accent);
    border-left: 4px solid var(--color-accent-dark);
}

.progress-step.complete {
    background: var(--color-success);
    border-left: 4px solid var(--color-success-dark);
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
    background: var(--color-accent-dark);
    color: var(--color-background);
}

.step-number.complete {
    background: var(--color-success-dark);
    color: var(--color-background);
}

.step-number.pending {
    background: var(--color-surface-dark);
    color: var(--color-text-muted);
}

/* Decision Card */
.decision-card {
    background: var(--color-surface);
    border: 2px solid var(--color-secondary);
    border-radius: 12px;
    padding: 1.5rem;
    margin: 1rem 0;
}

.decision-prompt {
    font-size: 1.1rem;
    font-weight: 500;
    color: var(--color-text);
    margin-bottom: 1rem;
    line-height: 1.5;
}

.decision-context {
    background: var(--color-background);
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    font-size: 0.9rem;
    color: var(--color-text-light);
    border-left: 4px solid var(--color-primary);
}

/* Option Buttons */
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
    color: var(--color-text);
}

.option-btn-primary:hover {
    background: var(--color-primary-dark);
    transform: translateY(-1px);
}

.option-btn-secondary {
    background: var(--color-background);
    color: var(--color-text-light);
    border: 1px solid var(--color-secondary);
}

.option-btn-secondary:hover {
    background: var(--color-background-dark);
}

.option-btn-success {
    background: var(--color-success);
    color: var(--color-text);
}

.option-btn-success:hover {
    background: var(--color-success-dark);
}

.option-btn-warning {
    background: var(--color-accent);
    color: var(--color-text);
}

.option-btn-warning:hover {
    background: var(--color-accent-dark);
}

/* Schema Display */
.schema-container {
    background: #3A3A40;
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
    color: var(--color-accent);
    font-weight: 600;
    font-size: 1rem;
    margin-bottom: 0.75rem;
}

.schema-field {
    display: flex;
    align-items: center;
    padding: 0.5rem;
    margin: 0.25rem 0;
    background: rgba(241, 240, 232, 0.08);
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

/* Sample Data Table */
.sample-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
}

.sample-table th {
    background: var(--color-secondary);
    padding: 0.75rem 1rem;
    text-align: left;
    font-weight: 600;
    color: var(--color-text);
    border-bottom: 2px solid var(--color-secondary-dark);
}

.sample-table td {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--color-surface-dark);
    color: var(--color-text);
    background: var(--color-surface);
}

.sample-table tr:hover td {
    background: var(--color-background);
}

/* Loading Spinner */
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
    border: 3px solid var(--color-background-dark);
    border-top-color: var(--color-primary-dark);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
}

.loading-text {
    margin-left: 1rem;
    color: var(--color-text-muted);
    font-weight: 500;
}

/* Info Box */
.info-box {
    background: var(--color-secondary);
    border: 1px solid var(--color-primary);
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    color: var(--color-text);
}

.info-box-icon {
    margin-right: 0.5rem;
}

/* Success Box */
.success-box {
    background: var(--color-success);
    border: 1px solid var(--color-success-dark);
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    color: var(--color-text);
}

/* Warning Box */
.warning-box {
    background: var(--color-accent);
    border: 1px solid var(--color-accent-dark);
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    color: var(--color-text);
}

/* Error Box */
.error-box {
    background: #E8C8C8;
    border: 1px solid #C8A0A0;
    border-radius: 8px;
    padding: 1rem;
    margin: 1rem 0;
    color: #5A4040;
}

/* Responsive Design */
@media (max-width: 768px) {
    .main-header {
        padding: 1.5rem;
    }

    .main-header h1 {
        font-size: 1.75rem;
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
}

/* Custom Streamlit Overrides */
.stApp > header {
    background-color: transparent;
}

section[data-testid="stSidebar"] {
    background-color: var(--color-surface);
    border-right: 1px solid var(--color-surface-dark);
}

section[data-testid="stSidebar"] > div {
    background-color: var(--color-surface);
}

.stButton > button {
    border-radius: 8px;
    font-weight: 500;
    padding: 0.5rem 1.5rem;
    transition: all 0.2s ease;
}

.stButton > button[kind="primary"] {
    background-color: var(--color-primary);
    color: var(--color-text);
    border: none;
}

.stButton > button[kind="primary"]:hover {
    background-color: var(--color-primary-dark);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(150, 182, 197, 0.4);
}

.stButton > button[kind="secondary"] {
    background-color: var(--color-surface);
    color: var(--color-text);
    border: 1px solid var(--color-secondary);
}

.stButton > button[kind="secondary"]:hover {
    background-color: var(--color-background);
    border-color: var(--color-secondary-dark);
}

.stTextInput > div > div > input {
    border-radius: 8px;
    border: 2px solid var(--color-secondary);
    padding: 0.75rem;
    background-color: var(--color-surface);
}

.stTextInput > div > div > input:focus {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 3px rgba(150, 182, 197, 0.2);
}

.stSelectbox > div > div {
    border-radius: 8px;
}

/* Expander styling */
.streamlit-expanderHeader {
    font-weight: 600;
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
    background-color: var(--color-secondary);
}

/* Metric styling */
div[data-testid="metric-container"] {
    background: var(--color-surface);
    border: 1px solid var(--color-secondary);
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
    background: #3A3A40;
    color: var(--color-background);
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
    background: var(--color-primary);
    color: var(--color-text);
}

.tag-green {
    background: var(--color-success);
    color: var(--color-text);
}

.tag-purple {
    background: var(--color-secondary);
    color: var(--color-text);
}

.tag-orange {
    background: var(--color-accent);
    color: var(--color-text);
}

/* Sidebar navigation steps */
.stSidebar [data-testid="stButton"] button {
    text-align: left;
    justify-content: flex-start;
}

.stSidebar [data-testid="stButton"] button[kind="secondary"] {
    background: var(--color-success);
    color: var(--color-text);
    border: none;
}

.stSidebar [data-testid="stButton"] button[kind="secondary"]:hover {
    background: var(--color-success-dark);
    border: none;
}

/* Field Cards */
.field-card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 0.75rem;
    margin: 1rem 0;
}

.field-card {
    background: var(--color-surface);
    border: 1px solid var(--color-secondary);
    border-radius: 10px;
    padding: 1rem;
    transition: box-shadow 0.2s ease;
}

.field-card:hover {
    box-shadow: 0 4px 12px rgba(58, 74, 80, 0.1);
}

.field-card-name {
    font-weight: 600;
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
    background: var(--color-primary);
    color: var(--color-text);
    padding: 0.1rem 0.5rem;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 500;
}

/* Page preview */
.preview-bar {
    background: var(--color-secondary);
    padding: 0.4rem 1rem;
    border-radius: 8px 8px 0 0;
    font-size: 0.8rem;
    color: var(--color-text);
    display: flex;
    align-items: center;
    gap: 0.5rem;
    border: 1px solid var(--color-secondary-dark);
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
    background: var(--color-success);
    padding: 0.2rem 0.6rem;
    border-radius: 9999px;
    font-size: 0.8rem;
    color: var(--color-text);
}

.nav-trail-current {
    background: var(--color-accent);
    padding: 0.2rem 0.6rem;
    border-radius: 9999px;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--color-text);
}

.nav-trail-arrow {
    color: var(--color-text-muted);
    font-size: 0.8rem;
}

/* Wizard headers */
.wizard-question {
    font-size: 1.5rem;
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: 0.25rem;
    line-height: 1.3;
}

.wizard-hint {
    color: var(--color-text-light);
    font-size: 0.95rem;
    margin-bottom: 1.5rem;
}

/* AI reasoning box */
.ai-reasoning {
    background: var(--color-background);
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
    border: 1px solid #E8C0C0;
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
    border: 1px solid var(--color-secondary);
    border-radius: 8px;
}

/* Form styling */
[data-testid="stForm"] {
    background-color: var(--color-surface);
    padding: 1.5rem;
    border-radius: 12px;
    border: 1px solid var(--color-secondary);
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
    border: 2px solid var(--color-secondary);
    border-radius: 8px;
}

/* Select box */
.stSelectbox > div > div {
    background-color: var(--color-surface);
}

/* Number input */
.stNumberInput > div > div > input {
    background-color: var(--color-surface);
    border: 2px solid var(--color-secondary);
    border-radius: 8px;
}

/* Multiselect */
.stMultiSelect > div > div {
    background-color: var(--color-surface);
}

/* Download button */
.stDownloadButton > button {
    background-color: var(--color-secondary);
    color: var(--color-text);
    border: none;
}

.stDownloadButton > button:hover {
    background-color: var(--color-secondary-dark);
}
</style>
"""


def get_css() -> str:
    """Return the main CSS styles."""
    return MAIN_CSS
