import streamlit as st
import serial
import serial.tools.list_ports
import joblib
import numpy as np
import pandas as pd
import time
import plotly.express as px
from sklearn.impute import SimpleImputer
import warnings
from datetime import datetime

# Suppress warnings
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=FutureWarning)

# Load models
scaler = joblib.load('scaler.joblib')
pca = joblib.load('pca.joblib')
kmeans = joblib.load('kmeans.joblib')

# Constants
WINDOW_SIZE = 200
STATE_MAPPING = {0: "Clogged", 1: "Unclogged"}

# Initialize session state
if 'data' not in st.session_state:
    st.session_state.data = pd.DataFrame(columns=["EncoderCount", "Current"])
if 'predictions' not in st.session_state:
    st.session_state.predictions = []
if 'pca_history' not in st.session_state:
    st.session_state.pca_history = pd.DataFrame(columns=["PCA1", "PCA2", "Cluster", "Condition", "Timestamp"])

def process_data(encoder_count, current):
    # Add data
    new_row = pd.DataFrame([[encoder_count, current]], columns=["EncoderCount", "Current"])
    st.session_state.data = pd.concat([st.session_state.data, new_row], ignore_index=True)

    # Trim data
    if len(st.session_state.data) > WINDOW_SIZE:
        st.session_state.data = st.session_state.data.iloc[-WINDOW_SIZE:]

    # Process window
    if len(st.session_state.data) == WINDOW_SIZE:
        window = st.session_state.data.copy()
        current_mean = window["Current"].mean()
        current_var = window["Current"].var()
        encoder_diff = abs(window["EncoderCount"].iloc[-1] - window["EncoderCount"].iloc[0])

        # Skip zero/invalid encoder_diff
        if encoder_diff == 0 or np.isnan(encoder_diff):
            return None, None

        current_per_encoder = (current_mean / encoder_diff) * 1000
        encoder_slope = np.polyfit(window.index, window["EncoderCount"], 1)[0]

        # Feature engineering
        features = pd.DataFrame(
            [[current_per_encoder, current_var, encoder_slope]],
            columns=["Current/Encoder", "CurrentVar", "EncoderSlope"]
        )

        # Preprocess
        features = SimpleImputer(strategy='mean').fit_transform(features)
        features = scaler.transform(features)
        pca_features = pca.transform(features)
        prediction = kmeans.predict(pca_features)

        # Track PCA history with timestamp and condition
        new_entry = pd.DataFrame({
            "PCA1": [pca_features[0, 0]],
            "PCA2": [pca_features[0, 1]],
            "Cluster": [prediction[0]],
            "Condition": [STATE_MAPPING[prediction[0]]],
            "Timestamp": [datetime.now()]
        })
        st.session_state.pca_history = pd.concat([st.session_state.pca_history, new_entry], ignore_index=True)

        return STATE_MAPPING[prediction[0]], pca_features
    return None, None

# Streamlit UI
st.set_page_config(page_title="Real-Time Nozzle Condition Monitoring", layout="wide")
st.title("Real-Time Nozzle Condition Monitoring")
st.markdown(
    """
    <div style="font-size: 20px; color: white;">
        Developed by Alexander Isiani, supervised by Dr. Crittenden and Dr. Weiss, and affiliated with the Institute for Micromanufacturing at Louisiana Tech University.
    </div>
    """,
    unsafe_allow_html=True
)
st.write("Connect to your Arduino and monitor the nozzle state in real-time.")

# COM port setup
ports = [port.device for port in serial.tools.list_ports.comports()]
selected_port = st.selectbox("Select Arduino COM Port", ports)

if st.button("Connect"):
    try:
        ser = serial.Serial(selected_port, 115200, timeout=1)
        st.success(f"Connected to {selected_port}")
    except Exception as e:
        st.error(f"Connection failed: {e}")

# Main loop
if 'ser' in locals():
    placeholder = st.empty()

    while True:
        try:
            raw_data = ser.readline()
            line = raw_data.decode('utf-8').strip()

            if line:
                parts = line.split(',')
                if len(parts) == 2:
                    try:
                        encoder = float(parts[0])
                        current = float(parts[1])

                        state, pca_features = process_data(encoder, current)

                        with placeholder.container():
                            # Display metrics
                            col1, col2 = st.columns(2)
                            col1.metric("Encoder Count", f"{encoder:.1f}")
                            col2.metric("Current", f"{current:.3f} A")

                            # Create three columns for plots
                            plot_col1, plot_col2, plot_col3 = st.columns(3)

                            with plot_col1:
                                fig1 = px.line(
                                    st.session_state.data,
                                    y=["EncoderCount", "Current"],
                                    title="Real-Time Sensor Data"
                                )
                                st.plotly_chart(fig1, use_container_width=True, key=f"line_{datetime.now().timestamp()}")

                            with plot_col2:
                                if not st.session_state.pca_history.empty:
                                    fig2 = px.scatter(
                                        st.session_state.pca_history,
                                        x="PCA1",
                                        y="PCA2",
                                        color="Condition",
                                        title="Live Clustering Analysis",
                                        color_discrete_map={"Clogged": "red", "Unclogged": "green"}
                                    )
                                    st.plotly_chart(fig2, use_container_width=True, key=f"cluster_{datetime.now().timestamp()}")

                            with plot_col3:
                                if st.session_state.predictions:
                                    counts = pd.Series(st.session_state.predictions).value_counts(normalize=True) * 100
                                    counts_df = counts.reset_index()
                                    counts_df.columns = ['Condition', 'Percentage']
                                    fig3 = px.bar(
                                        counts_df,
                                        x='Condition',
                                        y='Percentage',
                                        title="Condition Distribution",
                                        color='Condition',
                                        color_discrete_map={"Clogged": "red", "Unclogged": "green"}
                                    )
                                    st.plotly_chart(fig3, use_container_width=True, key=f"bar_{datetime.now().timestamp()}")

                            # Show state
                            if state:
                                st.session_state.predictions.append(state)
                                st.success(f"Status: {state}")

                    except ValueError:
                        st.warning(f"Skipped invalid data: {line}")
                else:
                    st.warning(f"Invalid format: {line}")

            time.sleep(0.1)

        except Exception as e:
            st.error(f"Error: {str(e)}")
            break