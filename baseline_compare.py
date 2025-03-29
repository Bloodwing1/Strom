
from strom.data_utils import get_temp_price_df
from strom.optimization_utils import House, compare_output_costs, plot_combined_cases
import numpy as np
import matplotlib.pyplot as plt

temp_price_df = get_temp_price_df()

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
    freq = 'min')

optimal_state_df, baseline_state_df = compare_output_costs(temp_price_df,house)

fig = plot_combined_cases(optimal_state_df, baseline_state_df)
# Save as png
fig.savefig("./plots/compare_costs_temps.png")

#show the plot
plt.show()