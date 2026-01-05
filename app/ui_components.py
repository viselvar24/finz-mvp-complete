"""
Professional UI Components for Perfient
Loading states, skeleton screens, trust signals, and branded elements
"""

import streamlit as st
import time
from pathlib import Path

def load_custom_css():
    """Load professional custom CSS styling"""
    css_file = Path(__file__).parent / "styles" / "professional.css"
    
    if css_file.exists():
        with open(css_file) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    else:
        # Fallback: Load inline minimal professional styling
        st.markdown("""
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .stDeployButton {display: none;}
        
        :root {
            --perfient-primary: #17a673;
            --perfient-primary-dark: #128a5e;
        }
        
        .stButton > button {
            background: linear-gradient(135deg, var(--perfient-primary) 0%, var(--perfient-primary-dark) 100%);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 0.75rem 1.5rem;
            font-weight: 500;
            transition: all 0.2s ease;
        }
        
        .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        }
        </style>
        """, unsafe_allow_html=True)


def show_loading_spinner(message="Loading...", key=None):
    """
    Display a professional loading spinner with message
    
    Args:
        message: Loading message to display
        key: Unique key for the spinner component
    """
    spinner_html = f"""
    <div class="loading-overlay" style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; 
         background: rgba(255, 255, 255, 0.95); display: flex; flex-direction: column; 
         justify-content: center; align-items: center; z-index: 9999; backdrop-filter: blur(4px);">
        <div class="loading-spinner" style="width: 60px; height: 60px; border: 4px solid #e5e7eb; 
             border-top-color: #17a673; border-radius: 50%; animation: spin 1s linear infinite;"></div>
        <div class="loading-text" style="margin-top: 1.5rem; font-size: 1rem; font-weight: 500; 
             color: #4b5563;">{message}</div>
    </div>
    <style>
    @keyframes spin {{
        to {{ transform: rotate(360deg); }}
    }}
    </style>
    """
    return st.markdown(spinner_html, unsafe_allow_html=True)


def show_skeleton_screen(num_rows=3):
    """
    Display skeleton loading screen for better perceived performance
    
    Args:
        num_rows: Number of skeleton rows to display
    """
    skeleton_html = """
    <style>
    .skeleton {
        background: linear-gradient(90deg, #f3f4f6 25%, #e5e7eb 50%, #f3f4f6 75%);
        background-size: 200% 100%;
        animation: loading 1.5s ease-in-out infinite;
        border-radius: 8px;
        margin-bottom: 1rem;
    }
    @keyframes loading {
        0% { background-position: 200% 0; }
        100% { background-position: -200% 0; }
    }
    </style>
    """
    
    for i in range(num_rows):
        height = "60px" if i == 0 else "40px"
        skeleton_html += f'<div class="skeleton" style="height: {height}; width: 100%;"></div>'
    
    return st.markdown(skeleton_html, unsafe_allow_html=True)


def show_trust_signals():
    """Display trust and security badges"""
    trust_html = """
    <div style="display: flex; justify-content: center; gap: 1rem; margin: 2rem 0; flex-wrap: wrap;">
        <div class="trust-badge" style="display: inline-flex; align-items: center; padding: 0.5rem 1rem; 
             background: white; border: 1px solid #e5e7eb; border-radius: 6px; font-size: 0.875rem; 
             color: #4b5563; box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" 
                 style="margin-right: 0.5rem;">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                <path d="M9 12l2 2 4-4"/>
            </svg>
            Bank-Level Encryption
        </div>
        
        <div class="trust-badge" style="display: inline-flex; align-items: center; padding: 0.5rem 1rem; 
             background: white; border: 1px solid #e5e7eb; border-radius: 6px; font-size: 0.875rem; 
             color: #4b5563; box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" 
                 style="margin-right: 0.5rem;">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
            Your Data is Private
        </div>
        
        <div class="trust-badge" style="display: inline-flex; align-items: center; padding: 0.5rem 1rem; 
             background: white; border: 1px solid #e5e7eb; border-radius: 6px; font-size: 0.875rem; 
             color: #4b5563; box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" 
                 style="margin-right: 0.5rem;">
                <circle cx="12" cy="12" r="10"/>
                <path d="M9 12l2 2 4-4"/>
            </svg>
            SEC-Compliant
        </div>
    </div>
    """
    return st.markdown(trust_html, unsafe_allow_html=True)


def show_professional_header(title, subtitle=None):
    """
    Display professional page header with optional subtitle
    
    Args:
        title: Main page title
        subtitle: Optional subtitle/description
    """
    header_html = f"""
    <div style="padding: 2rem 0 1rem 0; border-bottom: 1px solid #e5e7eb; margin-bottom: 2rem;">
        <h1 style="font-size: 2.5rem; font-weight: 700; color: #111827; margin: 0; 
                   letter-spacing: -0.02em;">{title}</h1>
    """
    
    if subtitle:
        header_html += f"""
        <p style="font-size: 1.125rem; color: #6b7280; margin-top: 0.5rem; margin-bottom: 0;">
            {subtitle}
        </p>
        """
    
    header_html += "</div>"
    return st.markdown(header_html, unsafe_allow_html=True)


def show_professional_footer():
    """Display professional footer with links and trust information"""
    footer_html = """
    <div class="custom-footer" style="border-top: 1px solid #e5e7eb; padding: 2rem 0; 
         margin-top: 4rem; text-align: center; color: #6b7280; font-size: 0.875rem;">
        <div style="margin-bottom: 1rem;">
            <strong style="color: #17a673; font-size: 1.125rem;">Perfient</strong> — 
            Personalized Financial Intelligence
        </div>
        <div style="margin-bottom: 1rem;">
            <a href="/Trust & Data Usage" style="color: #17a673; text-decoration: none; 
               font-weight: 500; margin: 0 1rem;">Privacy Policy</a>
            <a href="/Trust & Data Usage" style="color: #17a673; text-decoration: none; 
               font-weight: 500; margin: 0 1rem;">Data Security</a>
            <a href="mailto:support@perfient.com" style="color: #17a673; text-decoration: none; 
               font-weight: 500; margin: 0 1rem;">Contact Support</a>
        </div>
        <div style="font-size: 0.8rem; color: #9ca3af;">
            © 2025 Perfient. All rights reserved. | Investment advice is personalized and AI-powered.
            <br>
            Not FDIC insured. Investments involve risk including possible loss of principal.
        </div>
    </div>
    """
    return st.markdown(footer_html, unsafe_allow_html=True)


def show_progress_indicator(step, total_steps, step_names=None):
    """
    Display professional progress indicator for multi-step processes
    
    Args:
        step: Current step number (1-indexed)
        total_steps: Total number of steps
        step_names: Optional list of step names
    """
    progress_pct = (step / total_steps) * 100
    
    progress_html = f"""
    <div style="margin: 2rem 0;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
            <span style="font-size: 0.875rem; font-weight: 500; color: #4b5563;">
                Step {step} of {total_steps}
            </span>
            <span style="font-size: 0.875rem; font-weight: 500; color: #17a673;">
                {progress_pct:.0f}% Complete
            </span>
        </div>
        <div style="width: 100%; height: 8px; background: #e5e7eb; border-radius: 4px; overflow: hidden;">
            <div style="width: {progress_pct}%; height: 100%; background: linear-gradient(90deg, #17a673 0%, #20c997 100%); 
                 transition: width 0.3s ease;"></div>
        </div>
    """
    
    if step_names and len(step_names) == total_steps:
        progress_html += '<div style="display: flex; justify-content: space-between; margin-top: 1rem; font-size: 0.75rem;">'
        for i, name in enumerate(step_names, 1):
            color = "#17a673" if i <= step else "#9ca3af"
            weight = "600" if i == step else "400"
            progress_html += f'<span style="color: {color}; font-weight: {weight};">{name}</span>'
        progress_html += '</div>'
    
    progress_html += "</div>"
    return st.markdown(progress_html, unsafe_allow_html=True)


def show_info_card(title, content, icon="ℹ️", color="#3b82f6"):
    """
    Display professional information card
    
    Args:
        title: Card title
        content: Card content
        icon: Emoji icon
        color: Border color (hex)
    """
    card_html = f"""
    <div style="background: white; border-left: 4px solid {color}; border-radius: 8px; 
         padding: 1.25rem; margin: 1rem 0; box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);">
        <div style="display: flex; align-items: start;">
            <span style="font-size: 1.5rem; margin-right: 1rem;">{icon}</span>
            <div>
                <h4 style="margin: 0 0 0.5rem 0; font-size: 1rem; font-weight: 600; color: #111827;">
                    {title}
                </h4>
                <p style="margin: 0; font-size: 0.95rem; color: #4b5563; line-height: 1.6;">
                    {content}
                </p>
            </div>
        </div>
    </div>
    """
    return st.markdown(card_html, unsafe_allow_html=True)


class LoadingContext:
    """Context manager for showing loading states"""
    
    def __init__(self, message="Loading...", show_skeleton=False):
        self.message = message
        self.show_skeleton = show_skeleton
        self.placeholder = None
    
    def __enter__(self):
        self.placeholder = st.empty()
        if self.show_skeleton:
            with self.placeholder:
                show_skeleton_screen()
        else:
            with self.placeholder:
                with st.spinner(self.message):
                    pass
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.placeholder:
            self.placeholder.empty()


# Utility function for lazy loading with visual feedback
def lazy_load_component(load_func, loading_message="Loading...", use_skeleton=True):
    """
    Lazy load a component with professional loading state
    
    Args:
        load_func: Function to call for loading
        loading_message: Message to display while loading
        use_skeleton: Whether to show skeleton screen
    
    Returns:
        Result of load_func()
    """
    placeholder = st.empty()
    
    with placeholder:
        if use_skeleton:
            show_skeleton_screen(num_rows=3)
        else:
            st.info(f"⏳ {loading_message}")
    
    try:
        result = load_func()
        placeholder.empty()
        return result
    except Exception as e:
        placeholder.empty()
        st.error(f"❌ Failed to load: {str(e)}")
        return None
