#!/usr/bin/env python3
"""
Logmon SIEM Developer Assistant - Production Ready Streamlit App
A conversational AI assistant for Splunk SIEM query development and analysis.

Features:
- Modern Streamlit UI with chat interface
- Session state management
- Secure configuration
- Error handling and logging
- Export conversation history
- Health monitoring
"""

import os
import sys
import logging
import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import streamlit as st

try:
    from langchain_groq import ChatGroq
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.messages import HumanMessage, AIMessage
except ImportError as e:
    st.error(f"❌ Missing required dependencies: {e}")
    st.info("Install with: pip install langchain-groq langchain-core streamlit")
    st.stop()

# ------------------------------- 
# Configuration
# ------------------------------- 

@dataclass
class Config:
    """Application configuration"""
    groq_api_key: str
    model_name: str = "llama-3.3-70b-versatile"
    temperature: float = 0.6
    max_tokens: int = 2048
    max_history: int = 20
    log_level: str = "INFO"
    timeout: int = 30
    max_retries: int = 3
    
    @classmethod
    def from_env(cls) -> Optional['Config']:
        """Load configuration from environment variables"""
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return None
        
        return cls(
            groq_api_key=api_key,
            model_name=os.getenv("MODEL_NAME", "llama-3.3-70b-versatile"),
            temperature=float(os.getenv("TEMPERATURE", "0.6")),
            max_tokens=int(os.getenv("MAX_TOKENS", "2048")),
            max_history=int(os.getenv("MAX_HISTORY", "20")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            timeout=int(os.getenv("TIMEOUT", "30")),
            max_retries=int(os.getenv("MAX_RETRIES", "3"))
        )

# System role definition
SYSTEM_ROLE = """
### SYSTEM ROLE
You are a Logmon SIEM Developer Assistant. Your goal is to provide read-only, analyst-assistive guidance 
for Splunk SIEM use cases and dashboard development. Mandatory Baseline Fields: Time, Account, Device, Source_IP, SAFE_name.

### TASKS

1. SIEM Queries
- Analyze the login events in the provided log sample.
- Map all Mandatory Baseline Fields to the log fields and flag any missing.
- Suggest additional relevant fields if applicable.
- Build and validate an SPL query to detect the specified requirement.

**Input:** 
- Log sample
- Log type / description
- Requirement (what needs to be detected)

2. Dashboards
- Translate business/security requirements into dashboard KPIs.
- Assist in developing search queries for dashboard panels.

**Input:**
- Business/security requirement
- Log type(s) from which data is derived

### CONSTRAINTS
- Use 'eval' to normalize field names to the Mandatory Baseline names.
- Optimize queries for large datasets (use 'TERM' or 'index/source' filters).
- Focus only on query design, validation, and KPI guidance; do not perform any actions on live systems.
"""

# ------------------------------- 
# Logging Setup
# ------------------------------- 

@st.cache_resource
def setup_logging() -> logging.Logger:
    """Configure logging"""
    logger = logging.getLogger("logmon_siem")
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger

# ------------------------------- 
# Session State Initialization
# ------------------------------- 

def init_session_state():
    """Initialize Streamlit session state"""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    if "conversation_history" not in st.session_state:
        st.session_state.conversation_history = []
    
    if "llm" not in st.session_state:
        st.session_state.llm = None
    
    if "config" not in st.session_state:
        st.session_state.config = None
    
    if "initialized" not in st.session_state:
        st.session_state.initialized = False
    
    if "error_count" not in st.session_state:
        st.session_state.error_count = 0
    
    if "session_start" not in st.session_state:
        st.session_state.session_start = datetime.utcnow()

# ------------------------------- 
# SIEM Assistant Class
# ------------------------------- 

class SIEMAssistant:
    """Production-ready SIEM Developer Assistant for Streamlit"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_ROLE),
            MessagesPlaceholder("conversation"),
            ("human", "{current_question}")
        ])
    
    def initialize_llm(self) -> bool:
        """Initialize the LLM with retry logic"""
        for attempt in range(self.config.max_retries):
            try:
                self.logger.info(f"Initializing LLM (attempt {attempt + 1}/{self.config.max_retries})...")
                
                llm = ChatGroq(
                    model=self.config.model_name,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    api_key=self.config.groq_api_key,
                    timeout=self.config.timeout
                )
                
                # Test the connection
                test_response = llm.invoke([HumanMessage(content="ping")])
                if test_response:
                    st.session_state.llm = llm
                    st.session_state.initialized = True
                    self.logger.info("✅ LLM initialized successfully")
                    return True
                    
            except Exception as e:
                self.logger.error(f"Initialization attempt {attempt + 1} failed: {e}")
                if attempt < self.config.max_retries - 1:
                    self.logger.info("Retrying initialization...")
                else:
                    self.logger.error("❌ Failed to initialize LLM after all retries")
                    return False
        
        return False
    
    def ask_question(self, question: str) -> str:
        """
        Ask a question with conversation context
        
        Args:
            question: User's question about SIEM queries
            
        Returns:
            AI assistant's response or error message
        """
        if not st.session_state.llm:
            return "❌ Error: LLM not initialized. Please check your API key."
        
        if not question or not question.strip():
            return "❌ Error: Question cannot be empty"
        
        try:
            question = question.strip()
            self.logger.debug(f"Processing question: {question[:100]}...")
            
            # Trim conversation history if needed
            if len(st.session_state.conversation_history) > self.config.max_history:
                st.session_state.conversation_history = st.session_state.conversation_history[-self.config.max_history:]
            
            # Format messages
            formatted_messages = self.prompt_template.format_messages(
                conversation=st.session_state.conversation_history.copy(),
                current_question=question
            )
            
            # Get response
            response = st.session_state.llm.invoke(formatted_messages)
            
            # Update conversation history
            st.session_state.conversation_history.append(HumanMessage(content=question))
            st.session_state.conversation_history.append(AIMessage(content=response.content))
            
            self.logger.debug("Question processed successfully")
            return response.content
            
        except Exception as e:
            st.session_state.error_count += 1
            error_msg = f"❌ Error processing query: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return error_msg
    
    def health_check(self) -> Dict[str, Any]:
        """Perform health check"""
        status = {
            "timestamp": datetime.utcnow().isoformat(),
            "llm_initialized": st.session_state.initialized,
            "memory_size": len(st.session_state.conversation_history),
            "max_history": self.config.max_history,
            "error_count": st.session_state.error_count,
            "session_duration": str(datetime.utcnow() - st.session_state.session_start),
            "status": "healthy"
        }
        
        try:
            if st.session_state.llm:
                st.session_state.llm.invoke([HumanMessage(content="ping")])
                status["llm_responsive"] = True
            else:
                status["llm_responsive"] = False
                status["status"] = "degraded"
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            status["llm_responsive"] = False
            status["status"] = "unhealthy"
            status["error"] = str(e)
        
        return status

# ------------------------------- 
# UI Helper Functions
# ------------------------------- 

def export_conversation():
    """Export conversation history as JSON"""
    if not st.session_state.messages:
        return None
    
    export_data = {
        "exported_at": datetime.utcnow().isoformat(),
        "session_start": st.session_state.session_start.isoformat(),
        "message_count": len(st.session_state.messages),
        "conversation": st.session_state.messages
    }
    
    return json.dumps(export_data, indent=2)

def clear_conversation():
    """Clear conversation history"""
    st.session_state.messages = []
    st.session_state.conversation_history = []
    st.session_state.error_count = 0
    st.session_state.session_start = datetime.utcnow()

# ------------------------------- 
# Streamlit UI
# ------------------------------- 

def main():
    """Main Streamlit application"""
    
    # Page configuration
    st.set_page_config(
        page_title="Logmon SIEM Developer Assistant",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Initialize session state
    init_session_state()
    
    # Setup logging
    logger = setup_logging()
    
    # Header
    st.title("🛡️ Logmon SIEM Developer Assistant")
    st.markdown("*Production-Ready Splunk SIEM Query Development Assistant*")
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # API Key input
        api_key = st.text_input(
            "GROQ API Key",
            type="password",
            value=os.getenv("GROQ_API_KEY", ""),
            help="Enter your GROQ API key or set GROQ_API_KEY environment variable"
        )
        
        if api_key:
            os.environ["GROQ_API_KEY"] = api_key
        
        # Advanced settings
        with st.expander("🔧 Advanced Settings"):
            model = st.selectbox(
                "Model",
                ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "mixtral-8x7b-32768"],
                help="Select the LLM model"
            )
            
            temperature = st.slider(
                "Temperature",
                min_value=0.0,
                max_value=1.0,
                value=0.6,
                step=0.1,
                help="Controls randomness in responses"
            )
            
            max_tokens = st.number_input(
                "Max Tokens",
                min_value=512,
                max_value=4096,
                value=2048,
                step=256,
                help="Maximum response length"
            )
        
        st.divider()
        
        # Initialize button
        if st.button("🚀 Initialize Assistant", type="primary", use_container_width=True):
            if not api_key:
                st.error("❌ Please provide a GROQ API key")
            else:
                with st.spinner("Initializing LLM..."):
                    config = Config(
                        groq_api_key=api_key,
                        model_name=model,
                        temperature=temperature,
                        max_tokens=max_tokens
                    )
                    st.session_state.config = config
                    
                    assistant = SIEMAssistant(config, logger)
                    if assistant.initialize_llm():
                        st.success("✅ Assistant initialized successfully!")
                        st.rerun()
                    else:
                        st.error("❌ Failed to initialize assistant. Check your API key.")
        
        st.divider()
        
        # Session info
        st.subheader("📊 Session Info")
        
        if st.session_state.initialized:
            st.success("🟢 Assistant Ready")
        else:
            st.warning("🟡 Not Initialized")
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Messages", len(st.session_state.messages))
        with col2:
            st.metric("Errors", st.session_state.error_count)
        
        # Health check
        if st.session_state.initialized:
            if st.button("🏥 Health Check", use_container_width=True):
                config = st.session_state.config
                assistant = SIEMAssistant(config, logger)
                health = assistant.health_check()
                
                st.json(health)
        
        st.divider()
        
        # Actions
        st.subheader("🔧 Actions")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🗑️ Clear Chat", use_container_width=True):
                clear_conversation()
                st.rerun()
        
        with col2:
            if st.session_state.messages:
                export_json = export_conversation()
                if export_json:
                    st.download_button(
                        label="📥 Export",
                        data=export_json,
                        file_name=f"siem_conversation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                        mime="application/json",
                        use_container_width=True
                    )
        
        st.divider()
        
        # Help
        with st.expander("ℹ️ Help & Examples"):
            st.markdown("""
            **Example Queries:**
            
            1. *"Analyze this log sample and create an SPL query to detect failed login attempts"*
            
            2. *"Map the following fields to baseline: timestamp, username, host_ip"*
            
            3. *"Create a dashboard KPI for monitoring authentication failures"*
            
            4. *"Optimize this SPL query for large datasets"*
            
            **Mandatory Fields:**
            - Time
            - Account
            - Device
            - Source_IP
            - SAFE_name
            """)
    
    # Main chat interface
    if not st.session_state.initialized:
        st.info("👈 Please configure and initialize the assistant using the sidebar")
        
        # Show getting started guide
        st.markdown("---")
        st.subheader("🚀 Getting Started")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("### 1️⃣ API Key")
            st.markdown("Enter your GROQ API key in the sidebar")
        
        with col2:
            st.markdown("### 2️⃣ Configure")
            st.markdown("Adjust settings if needed (optional)")
        
        with col3:
            st.markdown("### 3️⃣ Initialize")
            st.markdown("Click 'Initialize Assistant' button")
        
        return
    
    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask about SIEM queries, SPL, or dashboard development..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Get assistant response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                config = st.session_state.config
                assistant = SIEMAssistant(config, logger)
                response = assistant.ask_question(prompt)
                st.markdown(response)
        
        # Add assistant response
        st.session_state.messages.append({"role": "assistant", "content": response})
        
        # Rerun to update UI
        st.rerun()

# ------------------------------- 
# Entry Point
# ------------------------------- 

if __name__ == "__main__":
    main()