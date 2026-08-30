import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import plotly.graph_objects as go
from typing import List
from matplotlib.figure import Figure

def plot_combined_cases(
    state_opt_df: pd.DataFrame,
    state_base_df: pd.DataFrame,
    plot_heater_output: bool = True,
    plot_cooling_output: bool = False,
    plot_price: bool = True,
    plot_T_exterior: bool = True,
    plot_wall_temp: bool = True
) -> Figure:
    """
    Create a combined plot comparing optimal and baseline cases for temperature and cost metrics.

    Args:
        state_opt_df: DataFrame containing optimal state data
        state_base_df: DataFrame containing baseline state data
        plot_heater_output: Whether to plot heater output
        plot_cooling_output: Whether to plot cooling output
        plot_price: Whether to plot electricity price
        plot_T_exterior: Whether to plot exterior temperature
        plot_wall_temp: Whether to plot wall temperature

    Returns:
        matplotlib.figure.Figure: The generated plot
    """
    # Determine the number of subplots based on heater output
    fig, (ax_temp, ax_cost) = plt.subplots(2, 1, figsize=(14, 8), 
                                              gridspec_kw={'height_ratios': [3, 1]}, sharex= True)
    

    # Single temperature axis
    legends_temp: list = []
    color = 'tab:red'
    ax_temp.set_ylabel('Temperature (°C)')
    ax_temp.plot(state_opt_df['InteriorTemperature'], color=color, linestyle='-', label='Optimal Interior Temp')
    ax_temp.plot(state_base_df['InteriorTemperature'], color=color, linestyle='--', label='Baseline Interior Temp')
    
    # Optional additional temperature plots
    if plot_wall_temp:
        color = 'tab:brown'
        ax_temp.plot(state_opt_df['WallTemperature'], color=color, linestyle='-', label='Optimal Wall Temp')
        ax_temp.plot(state_base_df['WallTemperature'], color=color, linestyle='--', label='Baseline Wall Temp')
    
    if plot_T_exterior:
        color = 'tab:pink'
        ax_temp.plot(state_opt_df['ExteriorTemperature'], color=color, linestyle='-', label='Exterior Temp')

    legends_temp = [(ax_temp.get_legend_handles_labels()[1], ax_temp, 'tab:red')]

    # Price Axis with smoothing
    legends_cost = []

    if plot_price:
        ax_price = ax_cost.twinx()
        color = 'tab:grey'
        ax_price.plot(state_opt_df['Price'], color=color)
        ax_price.set_ylabel('Price (€/kWh)', color=color)
        ax_price.tick_params(axis='y', labelcolor=color)
        legends_cost.append((['Electricity Price'], ax_price, color))

    if plot_heater_output or plot_cooling_output:
        # Heater Output Subplot (if plot_heater_output is True)
        ax_heater = ax_cost.twinx()
        ax_heater.spines["right"].set_position(("outward", 60))
        ax_heater_label = []
        if plot_heater_output:
            color = 'tab:red'
            ax_heater.plot(state_opt_df['HeaterOutput']*100, color=color, linestyle='-', label='Optimal Heater Output')
            ax_heater.plot(state_base_df['HeaterOutput']*100, color=color, linestyle='--', label='Baseline Heater Output')
            ax_heater_label.append('Heater')

        # Heater Output Subplot (if plot_heater_output is True)
        if plot_cooling_output:
            color = 'tab:blue'
            ax_heater.plot(state_opt_df['CoolingOutput']*100, color=color, linestyle='-', label='Optimal Cooling Output')
            ax_heater.plot(state_base_df['CoolingOutput']*100, color=color, linestyle='--', label='Baseline Cooling Output')
            ax_heater_label.append('Cooling')

        ax_heater.set_ylabel('/'.join(ax_heater_label)+' Output (%)', fontsize=8)
        ax_heater.tick_params(axis='y', labelcolor='tab:red')
        legends_cost.append((ax_heater.get_legend_handles_labels()[1], ax_heater, 'tab:red'))

    # Place temp legends
    for i, (legend_text, ax, color) in enumerate(legends_temp):
        ax.legend(
            legend_text, 
            loc='lower left', 
            bbox_to_anchor=(0.25*i, 1.01), 
            ncol=len(legend_text),
            prop={'size': 10}
        )

    # Place cost legends
    len_count=0
    for i, (legend_text, ax, color) in enumerate(legends_cost):
        ax.legend(
            legend_text, 
            loc='lower left', 
            bbox_to_anchor=(0.2*(len_count), 1.01), 
            ncol=len(legend_text),
            prop={'size': 10}
        )
        len_count += len(legend_text)
        
    # Adjust layout
    plt.tight_layout(rect=(0, 0, 1, 0.95))  # Leave room for legends

    return fig

def plot_combined_cases_years(
    state_opt_df: pd.DataFrame,
    state_base_df: pd.DataFrame,
    plot_T_exterior: bool = True
) -> Figure:
    """
    Create a combined yearly plot comparing optimal and baseline cases with daily aggregations.

    Args:
        state_opt_df: DataFrame containing optimal state data
        state_base_df: DataFrame containing baseline state data
        plot_T_exterior: Whether to plot exterior temperature

    Returns:
        matplotlib.figure.Figure: The generated plot
    """
    # Determine the number of subplots based on heater output
    fig, (ax_temp, ax_cost) = plt.subplots(2, 1, figsize=(14, 8), 
                                              gridspec_kw={'height_ratios': [3, 1]}, sharex= True)
    
    start_time = state_opt_df.index.min()
    end_time = state_opt_df.index.max()
    ax_temp.set_xlim(start_time, end_time)
    ax_cost.set_xlim(start_time, end_time)

    if plot_T_exterior:
        # Create daily aggregations
        daily_temp = state_opt_df['ExteriorTemperature'].resample('D').agg(['mean', 'min', 'max'])
        
        # Create a rolling average of the daily mean temperatures (7-day window)
        rolling_mean = daily_temp['mean'].rolling(window=7, center=True).mean()
        

        # First, add the comfort zone as a shaded area
        comfort_min = 18.0
        comfort_max = 24.0
        ax_temp.axhspan(comfort_min, comfort_max, alpha=0.2, color='green', label='Comfort Zone (18-24°C)')

        # Plot the smoothed line
        color = 'tab:pink'
        ax_temp.plot(rolling_mean.index, rolling_mean, 
                    color=color, linestyle='-', linewidth=2, 
                    label='Exterior Temp (7-day avg)')
        
        # Create shaded envelope for min/max temperatures
        ax_temp.fill_between(daily_temp.index, 
                            daily_temp['min'], 
                            daily_temp['max'], 
                            color=color, alpha=0.3,
                            label='Daily Min/Max Range')

        # Add legend if not already present elsewhere
        handles, labels = ax_temp.get_legend_handles_labels()
        if 'Exterior Temp' in labels or 'Exterior Temp (7-day avg)' in labels:
            ax_temp.legend(loc='best')

    # Single temperature axis
    legends_temp = []
    color = 'tab:red'
    ax_temp.set_ylabel('Temperature (°C)')
    ax_temp.plot(state_opt_df['InteriorTemperature'], color=color, linestyle='-', label='Optimal Interior Temperature')
    ax_temp.plot(state_base_df['InteriorTemperature'], color='k', linestyle='-', label='Baseline Interior Temperature')

    legends_temp = [(ax_temp.get_legend_handles_labels()[1], ax_temp, 'tab:red')]

    # Create a twin axis for cost savings


    color = 'tab:grey'
    
    # Resample price to daily values
    daily_price = state_opt_df['Price'].resample('D').agg(['mean', 'min', 'max'])
    
    # Create a rolling average (7-day window)
    rolling_price = daily_price['mean'].rolling(window=7, center=True).mean()
    
    # Plot the smoothed line
    ax_cost.plot(rolling_price.index, rolling_price,
                color=color, linestyle='-', linewidth=2,
                label='Electricity Price (7-day avg)')
    
    ax_cost.fill_between(daily_price.index, 
                        daily_price['min'], 
                        daily_price['max'], 
                        color=color, alpha=0.3,
                        label='Daily Min/Max Range')
    handles, labels = ax_cost.get_legend_handles_labels()
    ax_cost.legend(loc='best')
    # Plot the original data with lower opacity if desired
    # ax_cost.plot(state_opt_df['Price'], color=color, alpha=0.3, linewidth=0.5)
    
    ax_cost.set_ylabel('Price (€/kWh)')
    ax_cost.tick_params(axis='y', labelcolor=color)
    legends_cost = [(ax_cost.get_legend_handles_labels()[1], ax_cost, 'tab:red')]

    # Cumulative cost
    ax_cost2 = ax_cost.twinx()
    color = 'tab:green'
    ax_cost2.set_xlabel('Time (h)')
    ax_cost2.set_ylabel('Cumulative Cost (€)')
    ax_cost2.plot(state_opt_df['Cost'].cumsum(), color=color, linestyle='-', label='Optimal Cumulative Cost')
    ax_cost2.plot(state_base_df['Cost'].cumsum(), color=color, linestyle='--', label='Baseline Cumulative Cost')
    ax_cost2.tick_params(axis='y', labelcolor=color)
    ax_cost2.tick_params(axis='x', rotation=45)
    legends_cost.append((ax_cost2.get_legend_handles_labels()[1], ax_cost2, color))
    # print the difference in total costs
    print(sum(state_base_df['Cost']-state_opt_df['Cost'])/sum(state_base_df['Cost']))

    # Daily cost
    ax_day = ax_cost.twinx()
    ax_day.spines["right"].set_position(("outward", 60))
    color = 'tab:olive'

    # Get the base and optimal costs
    base_cost = state_base_df['Cost']
    opt_cost = state_opt_df['Cost']  # Fixed: was using state_base_df twice

    # Resample to daily values
    daily_base = base_cost.resample('D').sum()
    daily_opt = opt_cost.resample('D').sum()

    # Create rolling averages (30-day window)
    rolling_base = daily_base.rolling(window=7, center=True).mean()
    rolling_opt = daily_opt.rolling(window=7, center=True).mean()

    # Plot both lines
    ax_day.plot(rolling_base.index, rolling_base, 
                color=color, linestyle='--', linewidth=2, 
                label='Base Cost (7-day avg)')
                
    ax_day.plot(rolling_opt.index, rolling_opt, 
                color=color, linestyle='-', linewidth=2, 
                label='Optimal Cost (7-day avg)')

    ax_day.set_xlabel('Time (h)')
    ax_day.set_ylabel('Cost (€/day)')
    ax_day.tick_params(axis='y', labelcolor=color)
    ax_day.tick_params(axis='x', rotation=45)
    legends_cost.append((ax_day.get_legend_handles_labels()[1], ax_day, color))

    # Place temp legends
    for i, (legend_text, ax, color) in enumerate(legends_temp):
        ax.legend(
            legend_text, 
            loc='lower left', 
            bbox_to_anchor=(0.25*i, 1.01), 
            ncol=len(legend_text),
            prop={'size': 8}
        )

    # Place cost legends
    for i, (legend_text, ax, color) in enumerate(legends_cost):
        ax.legend(
            legend_text, 
            loc='lower left', 
            bbox_to_anchor=(0.33*i, 1.01), 
            ncol=len(legend_text),
            prop={'size': 8}
        )

    # Adjust layout
    plt.tight_layout(rect=(0, 0, 1, 0.95))  # Leave room for legends

    return fig


def plot_factor_analysis(
    optimal_cost: np.ndarray,
    baseline_cost: np.ndarray,
    C_walls_list: List[float],
    Q_heater_list: List[float],
    R_external_list: List[float],
    type: str
) -> go.Figure:
    """
    Create a 3D scatter plot analyzing the impact of different factors on cost savings.

    Args:
        optimal_cost: Array of optimal costs for different parameter combinations
        baseline_cost: Array of baseline costs for different parameter combinations
        C_walls_list: List of wall heat capacity values
        Q_heater_list: List of heating power values
        R_external_list: List of R-values (thermal resistance)
        type: Type of analysis ('Relative' or 'Absolute')

    Returns:
        plotly.graph_objects.Figure: Interactive 3D scatter plot
    """
    # Create meshgrid
    X, Y, Z = np.meshgrid(C_walls_list, Q_heater_list, R_external_list)
    if type == 'Relative':
        values = 100 * (baseline_cost - optimal_cost) / baseline_cost
        title = 'Relative Cost Savings (%)'
    elif type == 'Absolute':
        values = baseline_cost - optimal_cost
        title = 'Absolute Cost Savings (€)'
    else:
        raise ValueError("Invalid type. Expected 'Relative' or 'Absolute'.")


    # Flatten for Plotly
    X_flat = X.flatten()
    Y_flat = Y.flatten()
    Z_flat = Z.flatten()
    values_flat = values.flatten()

    # Create interactive 3D scatter plot
    fig = go.Figure(data=[go.Scatter3d(
        x=X_flat, 
        y=Y_flat, 
        z=Z_flat, 
        mode='markers',
        marker=dict(
            size=5,
            color=values_flat,  # Color by cost_diff values
            colorscale='PRGn',
            colorbar=dict(title=title),
            opacity=0.8
        )
    )])

    # Set axis labels
    fig.update_layout(
        scene=dict(
            xaxis_title='Wall heat capacity (kWh/°C)',
            yaxis_title='Heating Power (kW)',
            zaxis_title='R-Value (°C/kW)',
            aspectmode='cube',  # Forces equal aspect ratio
            aspectratio=dict(x=1, y=1, z=1)  # Sets the aspect ratio to 1:1:1
        ),
        title="{} Cost Savings Analysis".format(type),
    )
    return fig
