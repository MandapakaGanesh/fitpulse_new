import os
import pandas as pd
import numpy as np

os.makedirs("sample_data", exist_ok=True)

# 1. dailyActivity_merged.csv
dates = pd.date_range(start="2024-03-01", periods=30, freq="D")
df_activity = pd.DataFrame({
    "Id": [123456789] * 30,
    "ActivityDate": dates.strftime("%m/%d/%Y"),
    "TotalSteps": np.random.randint(2000, 15000, 30),
    "TotalDistance": np.random.uniform(1.5, 12.0, 30).round(2),
    "Calories": np.random.randint(1500, 3500, 30)
})
df_activity.to_csv("sample_data/dailyActivity_merged.csv", index=False)

# 2. sleepDay_merged.csv
sleep_dates = pd.date_range(start="2024-03-01", periods=25, freq="D")  # missing some days
df_sleep = pd.DataFrame({
    "Id": [123456789] * 25,
    "SleepDay": sleep_dates.strftime("%m/%d/%Y 12:00:00 AM"),
    "TotalMinutesAsleep": np.random.randint(240, 500, 25),
    "TotalTimeInBed": np.random.randint(260, 520, 25)
})
# Add a duplicate for realism
df_sleep = pd.concat([df_sleep, df_sleep.iloc[[-1]]], ignore_index=True)
df_sleep.to_csv("sample_data/sleepDay_merged.csv", index=False)

# 3. weightLogInfo_merged.csv (only a few measurements)
weight_dates = pd.date_range(start="2024-03-01", periods=5, freq="6D")
df_weight = pd.DataFrame({
    "Id": [123456789] * 5,
    "Date": weight_dates.strftime("%m/%d/%Y 11:59:59 PM"),
    "WeightKg": np.random.uniform(70.0, 72.5, 5).round(1),
    "BMI": np.random.uniform(22.0, 23.5, 5).round(1)
})
df_weight.to_csv("sample_data/weightLogInfo_merged.csv", index=False)

print("Sample datasets generated in sample_data/")
