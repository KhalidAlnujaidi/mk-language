"""Streamlit Observability Dashboard (vision §9 #5).

Reads from ~/.kinox/broker-events.jsonl and provides an interactive
dashboard with metrics, charts, and a filterable datatable of events.
"""

import os
from pathlib import Path
import json
import shutil
import subprocess

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, ColumnsAutoSizeMode
from streamlit_autorefresh import st_autorefresh
from streamlit_agraph import agraph, Node, Edge, Config

st.set_page_config(page_title="Kinox Observability", page_icon="🔭", layout="wide")

# Automatically refresh every 5 seconds (5000 milliseconds)
count = st_autorefresh(interval=5000, limit=1000, key="kinox_autorefresh")

def load_events(paths: list[Path]) -> pd.DataFrame:
    """Load JSONL events from multiple paths into a single pandas DataFrame."""
    events = []
    
    for path in paths:
        if not path.exists():
            continue
            
        source_name = path.stem.split('-')[0]  # 'broker' or 'chat'
        
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        record = json.loads(line)
                        record["_source"] = source_name
                        events.append(record)
                    except json.JSONDecodeError:
                        continue
                        
    if not events:
        return pd.DataFrame()
        
    df = pd.DataFrame(events)
    # Convert latency to numeric, handle missing values
    if "latency_ms" in df.columns:
        df["latency_ms"] = pd.to_numeric(df["latency_ms"], errors="coerce")
    if "tokens_in" in df.columns:
        df["tokens_in"] = pd.to_numeric(df["tokens_in"], errors="coerce")
    if "tokens_out" in df.columns:
        df["tokens_out"] = pd.to_numeric(df["tokens_out"], errors="coerce")
        
    # Sort events by time conceptually (JSONL is append-only)
    return df

def _get_loaded_models() -> list[dict]:
    """Get currently loaded models from `ollama ps`."""
    if shutil.which("ollama") is None:
        return []
        
    try:
        result = subprocess.run(
            ["ollama", "ps"], capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return []
            
        lines = result.stdout.strip().splitlines()
        if len(lines) <= 1:
            return []
            
        # NAME ID SIZE PROCESSOR UNTIL
        models = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 4:
                # Typically: llama3:8b <id> <size> <unit> <processor...> <until...>
                name = parts[0]
                size_str = f"{parts[2]} {parts[3]}" if len(parts) > 3 else "Unknown"
                
                # The processor is whatever comes after the size unit, until the "UNTIL" part
                # UNTIL is usually like "4 minutes from now" or "Forever".
                # It's fuzzy, let's just grab the next two parts for processor if possible
                processor_str = f"{parts[4]} {parts[5]}" if len(parts) > 5 else "Unknown"
                
                models.append({
                    "name": name,
                    "size": size_str,
                    "processor": processor_str
                })
        return models
    except Exception:
        return []

def _get_active_sessions() -> int:
    """Get number of active kinox sessions running in parallel."""
    try:
        result = subprocess.run(["ps", "-ef"], capture_output=True, text=True)
        count = 0
        for line in result.stdout.splitlines():
            if "kx" in line and "session" in line and "grep" not in line and "streamlit" not in line:
                count += 1
        return count
    except Exception:
        return 0

def _get_crashes() -> pd.DataFrame:
    """Parse outbox and event streams to find crashes and errors."""
    outbox_path = Path.home() / ".kinox" / "broker-outbox.jsonl"
    crashes = []
    
    if outbox_path.exists():
        with open(outbox_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        record = json.loads(line)
                        if record.get("status") == "failed":
                            crashes.append({
                                "Type": "Outbox Failure (Crash)",
                                "Task ID": record.get("id"),
                                "Kind": record.get("kind"),
                                "Details": record.get("payload")
                            })
                    except Exception:
                        pass
                        
    return pd.DataFrame(crashes)

def _lan_host() -> str:
    """Best-effort LAN IP of this machine; the fallback href for the cross-dashboard
    link (JS upgrades it to the browser's live hostname)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return socket.gethostname() or "localhost"
    finally:
        s.close()


def render_dashboard():
    st.title("🔭 Kinox Observability Dashboard")
    st.markdown("Real-time view of the Agentic Control Plane events and routing decisions.")

    # Cross-link to sibling dashboards on this box (read-only, separate ports).
    # Real markdown anchor (not a sandboxed component iframe) so the click works;
    # href is baked to this machine's LAN IP, which is how the box is reached.
    _lang_url = f"http://{_lan_host()}:8800/"
    st.sidebar.subheader("🔗 Related dashboards")
    st.sidebar.markdown(
        f'<a href="{_lang_url}" target="_blank" rel="noopener" '
        f'style="font:600 14px/1.4 system-ui,sans-serif;color:#4da3ff;text-decoration:none">'
        f'🗣️ Language / Council experiment ↗</a>'
        f'<div style="font:12px system-ui,sans-serif;color:#888;margin-top:4px">'
        f'Live council run · proposals, ballots, Borda tally · :8800</div>',
        unsafe_allow_html=True,
    )
    
    # Load data from all event streams to create a true mainframe view
    broker_path = Path.home() / ".kinox" / "broker-events.jsonl"
    chat_path = Path.home() / ".kinox" / "chat-events.jsonl"
    df = load_events([broker_path, chat_path])
    
    if df.empty:
        st.info("No events found. Run a task to generate events!")
        return
        
    # High-level metrics
    col1, col2, col3, col4, col5 = st.columns(5)
    
    total_events = len(df)
    col1.metric("Total Events", total_events)
    
    # Active Sessions
    active_sessions = _get_active_sessions()
    col2.metric("Active Sessions", active_sessions)
    
    # Corrections
    corrections = df["correction_of"].notna().sum() if "correction_of" in df.columns else 0
    correction_rate = (corrections / total_events) if total_events > 0 else 0
    col3.metric("Correction Rate", f"{correction_rate:.1%}")
    
    # Total Tokens Used
    total_tok = df["tokens_out"].sum() if "tokens_out" in df.columns else 0
    col4.metric("Tokens Out (Used)", f"{total_tok:,.0f}" if pd.notna(total_tok) else "—")
    
    # Tokens Saved (Anything not routed to the cloud)
    if "tier" in df.columns and "tokens_out" in df.columns and "tokens_in" in df.columns:
        local_df = df[~df["tier"].astype(str).str.contains("cloud", na=False)]
        tokens_saved = local_df["tokens_in"].sum() + local_df["tokens_out"].sum()
        col5.metric("Cloud Tokens Saved", f"{tokens_saved:,.0f}" if pd.notna(tokens_saved) else "0")
    else:
        col5.metric("Cloud Tokens Saved", "—")
    
    st.divider()
    
    # --- Machine State ---
    st.subheader("💻 Machine State (VRAM)")
    loaded_models = _get_loaded_models()
    
    if loaded_models:
        for m in loaded_models:
            model_name = m["name"]
            
            # Find recent role from Event Stream
            recent_role = "unknown"
            if "tier" in df.columns and "kind" in df.columns:
                # Last event for this tier
                model_events = df[df["tier"] == model_name]
                if not model_events.empty:
                    recent_role = model_events.iloc[-1]["kind"]
                    
            st.info(f"**{model_name}** (`{recent_role}`) — {m['size']} ({m['processor']})")
    else:
        # Check if Ollama is installed
        if shutil.which("ollama") is None:
            st.warning("Ollama is not installed or not in PATH. Cannot fetch VRAM state.")
        else:
            st.info("No models currently loaded in VRAM.")
    
    st.divider()
    
    # --- Charts ---
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        st.subheader("Tier Usage")
        if "tier" in df.columns:
            tier_counts = df["tier"].value_counts().reset_index()
            tier_counts.columns = ["Tier", "Count"]
            st.bar_chart(data=tier_counts, x="Tier", y="Count", color="#00b4d8")
            
    with chart_col2:
        st.subheader("Average Latency by Tier")
        if "tier" in df.columns and "latency_ms" in df.columns:
            lat_by_tier = df.groupby("tier")["latency_ms"].mean().reset_index()
            lat_by_tier.columns = ["Tier", "Avg Latency (ms)"]
            st.bar_chart(data=lat_by_tier, x="Tier", y="Avg Latency (ms)", color="#ff5400")
            
    # --- Causal Graph (Reasoning DAG) ---
    st.divider()
    st.subheader("🕸️ Reasoning Graph")
    
    if "task_id" in df.columns and "correction_of" in df.columns:
        nodes = []
        edges = []
        added_nodes = set()
        
        # We'll visualize the last 50 events to avoid clutter
        graph_df = df.tail(50)
        
        for _, row in graph_df.iterrows():
            task_id = str(row["task_id"])
            kind = row["kind"]
            tier = row["tier"]
            
            if task_id not in added_nodes:
                # Add node
                nodes.append(Node(
                    id=task_id,
                    label=f"{kind}\n({tier})",
                    size=25,
                    shape="dot"
                ))
                added_nodes.add(task_id)
                
            correction_of = row.get("correction_of")
            if pd.notna(correction_of) and str(correction_of) != "None":
                corr_id = str(correction_of)
                if corr_id not in added_nodes:
                    nodes.append(Node(
                        id=corr_id,
                        label=corr_id[:8],
                        size=20,
                        shape="dot"
                    ))
                    added_nodes.add(corr_id)
                
                # Edge from corrected -> correction
                edges.append(Edge(
                    source=corr_id,
                    target=task_id,
                    label="correction"
                ))
                
        if nodes:
            config = Config(
                width=1000,
                height=400,
                directed=True,
                physics=True,
                hierarchical=False,
            )
            agraph(nodes=nodes, edges=edges, config=config)
        else:
            st.info("No corrections found in the recent events to build a graph.")
    
    st.divider()
    
    # Interactive Datatable (AG Grid)
    st.subheader("Event Stream")
    
    # Filter by Source & Tier
    col_f1, col_f2 = st.columns(2)
    
    with col_f1:
        if "_source" in df.columns:
            sources = ["All"] + list(df["_source"].unique())
            selected_source = st.selectbox("Filter by Source", sources)
        else:
            selected_source = "All"
            
    with col_f2:
        if "tier" in df.columns:
            tiers = ["All"] + list(df["tier"].unique())
            selected_tier = st.selectbox("Filter by Tier", tiers)
        else:
            selected_tier = "All"
            
    display_df = df
    if selected_source != "All":
        display_df = display_df[display_df["_source"] == selected_source]
    if selected_tier != "All":
        display_df = display_df[display_df["tier"] == selected_tier]
        
    # Build AG Grid
    gb = GridOptionsBuilder.from_dataframe(display_df)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
    gb.configure_side_bar()
    gb.configure_selection('multiple', use_checkbox=True)
    gb.configure_default_column(filterable=True, sortable=True)
    gridOptions = gb.build()
    
    AgGrid(
        display_df,
        gridOptions=gridOptions,
        data_return_mode='AS_INPUT',
        update_mode='NO_UPDATE',
        fit_columns_on_grid_load=False,
        columns_auto_size_mode=ColumnsAutoSizeMode.FIT_CONTENTS,
        theme='streamlit'
    )
    
    # --- Errors & Crashes ---
    st.divider()
    st.subheader("🚨 Crashes & Errors")
    crash_df = _get_crashes()
    
    # Also find broker exhaustions in the event stream
    exhaustions = []
    if "latency_ms" in df.columns:
        exhausted_events = df[df["latency_ms"].isna()]
        for _, row in exhausted_events.iterrows():
            exhaustions.append({
                "Type": "Chain Exhausted (No Model fit)",
                "Task ID": row.get("task_id"),
                "Kind": row.get("kind"),
                "Details": f"Tier: {row.get('tier')}"
            })
            
    if exhaustions:
        crash_df = pd.concat([crash_df, pd.DataFrame(exhaustions)], ignore_index=True)
        
    if not crash_df.empty:
        st.error(f"Detected {len(crash_df)} crashes or critical errors.")
        AgGrid(crash_df, fit_columns_on_grid_load=True, theme='streamlit')
    else:
        st.success("No crashes or critical errors detected! The system is healthy.")

if __name__ == "__main__":
    render_dashboard()
