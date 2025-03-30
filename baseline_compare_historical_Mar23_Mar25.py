
from strom.api_utils import get_price_series
from strom.data_utils import join_data, regularize_df
from strom.optimization_utils import House, compare_output_costs
from strom.plot_utils import plot_combined_cases

import pandas as pd
import matplotlib.pyplot as plt

temp_price_df = pd.read_csv('data/Temp_Price_Barcelona_Mar23_Mar25.csv', index_col="Timestamp", parse_dates=["Timestamp"])

house = House(
    C_air = 0.56,
    C_wall = 3.5,
    R_interior = 1.0,
    R_exterior = 6.06,
    Q_heater = 2.0,
    Q_cooling = 2.0,
    T_min = 18.0,
    T_max = 24.0,
    T_interior_init = 18.5,
    T_wall_init = 18.5,
    P_base = 0.01,
    freq = '15min',
    cooling_unit = True
    )

optimal_state_df, baseline_state_df = compare_output_costs(temp_price_df,house)

fig = plot_combined_cases(optimal_state_df, baseline_state_df)
# Save as png
fig.savefig("./plots/compare_costs_temps_Barcelona_Nov.png")

#show the plot
plt.show()