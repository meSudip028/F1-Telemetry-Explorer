# 🏎️ F1 Telemetry Explorer

A Python-based Formula 1 data analysis project that explores qualifying lap times, car telemetry, circuit speed maps, and driver comparisons using real session data.

Built as a hands-on learning project to explore Python, data analysis, and motorsport telemetry.

## 📌 Project Overview

The F1 Telemetry Explorer analyzes the **2022 Bahrain Grand Prix qualifying session** using the FastF1 Python library.

It retrieves session and lap data, visualizes car telemetry, and compares Charles Leclerc's and Max Verstappen's fastest qualifying laps.

## ✨ Features

- **Qualifying Lap Analysis:** Retrieve and sort the ten fastest available laps.
- **Circuit Speed Map:** Visualize Charles Leclerc's racing line, colored according to car speed.
- **Telemetry Analysis:** Plot speed, throttle, brake application, and gear against distance.
- **Driver Comparison:** Compare Leclerc and Verstappen using speed, throttle, braking, and an estimated time-gap curve.
- **Exportable Visualizations:** Save the generated charts as PNG images.

## 📊 Project Screenshots

### 1. Circuit Speed Map

The circuit is colored according to Leclerc's recorded speed around the lap.

![F1 circuit speed map](images/f1_circuit_speed_map.png)

### 2. Telemetry Analysis

Speed, throttle, brake application, and gear plotted against distance.

![F1 telemetry analysis](images/f1_telemetry_analysis.png)

### 3. Leclerc vs. Verstappen

A comparison of both drivers' fastest qualifying laps, including telemetry and an estimated distance-aligned time-gap curve.

![F1 driver comparison](images/f1_driver_comparison.png)

## 🛠️ Technologies Used

- **Python** — Programming language
- **FastF1** — Formula 1 session, lap, and telemetry data
- **Pandas** — Data cleaning and tabular analysis
- **NumPy** — Numerical operations and interpolation
- **Matplotlib** — Circuit maps and telemetry visualizations
- **Google Colab** — Development and execution environment
- **Git and GitHub** — Version control and project sharing

## 🚀 Getting Started

### Option 1: Run in Google Colab

1. Download or clone this repository.
2. Open `F1_Telemetry_Explorer.ipynb` in Google Colab.
3. Install the required packages in a code cell:

   ```python
   !pip install fastf1 pandas numpy matplotlib
   ```

4. Run the notebook cells in order, from Stage 1 through Stage 4.
5. View the generated charts and analysis.

**Note:** If your Colab runtime restarts, run the installation cell again. Previously downloaded cache files and generated images may need to be recreated.

### Option 2: Install the dependencies locally

Install Python and the required packages:

```bash
pip install fastf1 pandas numpy matplotlib
```

The notebook was developed for Google Colab. Some file paths and environment-specific settings may need to be adjusted before running it locally.

## 📂 Project Structure

```text
F1-Telemetry-Explorer/
├── F1_Telemetry_Explorer.ipynb
├── README.md
└── images/
    ├── f1_circuit_speed_map.png
    ├── f1_telemetry_analysis.png
    └── f1_driver_comparison.png
```

## 📈 Understanding the Driver Comparison

The project selects each driver's fastest valid qualifying lap and compares their telemetry over distance.

The time-gap graph is an **estimate**, calculated by aligning each driver's telemetry time to a common distance grid. It is not an official FIA timing calculation.

The actual difference between the recorded lap times is reported separately. Because the drivers' fastest laps may have been recorded at different points in qualifying, this analysis does not establish a controlled, same-condition comparison.

The brake channel is visualized as an on/off signal when the underlying data is Boolean. It does not represent actual brake pressure.

## 🎯 What I Learned

- Working with a Python data library
- Loading and exploring structured data
- Cleaning missing and invalid telemetry values
- Using Pandas and NumPy for data analysis
- Creating visualizations with Matplotlib
- Comparing time-series data using distance-based interpolation
- Organizing a multi-stage Python project

## 🔮 Future Improvements

- Build an interactive dashboard using Streamlit.
- Add circuit selection and driver selection.
- Compare additional drivers and qualifying sessions.
- Add more telemetry analysis and improved visualizations.
- Deploy the dashboard as a public web application.

## ⚠️ Data and Disclaimer

This is an independent educational project and is not affiliated with Formula 1, the FIA, or any racing team.

Session data is accessed through FastF1. Availability depends on the data source, internet access, and any applicable authentication requirements.

Formula 1 names and related marks belong to their respective owners. Please respect the relevant data-source terms and usage restrictions.

---

**Built with Python and a passion for Formula 1. 🏁**