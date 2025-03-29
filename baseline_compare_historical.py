
from strom.api_utils import get_price_series
from strom.data_utils import join_data, regularize_df
from strom.optimization_utils import House, compare_output_costs
from strom.plot_utils import plot_combined_cases

import pandas as pd
import matplotlib.pyplot as plt

temp_df = pd.read_csv('data/Temp_Barcelona_Nov.csv')
temp_df.rename(columns={'temp': 'Exterior Temperature'}, inplace=True)
temp_df['Timestamp'] = pd.to_datetime(temp_df['datetimeEpoch'], unit='s').dt.tz_localize('Europe/Madrid')
temp_df.set_index('Timestamp', inplace=True)
temperature_series = temp_df['Exterior Temperature']
time_range = temperature_series.index
price_series = get_price_series(time_range=time_range)
price_now_df = get_price_series()
temp_price_df = join_data(temperature_series, price_series)
temp_price_df = regularize_df(temp_price_df)

house = House(
    C_air = 0.56,
    C_wall = 3.5,
    R_interior = 1.0,
    R_exterior = 6.06,
    Q_heater = 2.0,
    T_min = 18.0,
    T_max = 24.0,
    T_interior_init = 18.5,
    T_wall_init = 18.5,
    P_base = 0.01,
    freq = '15min')

optimal_state_df, baseline_state_df = compare_output_costs(temp_price_df,house)

fig = plot_combined_cases(optimal_state_df, baseline_state_df)
# Save as png
fig.savefig("./plots/compare_costs_temps_Barcelona_Nov.png")

#show the plot
plt.show()