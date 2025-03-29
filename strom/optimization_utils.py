import numpy as np
import pandas as pd
import cvxpy as cp
import matplotlib.pyplot as plt
import plotly.graph_objects as go

import requests
from datetime import datetime

import os
import xml.etree.ElementTree as ET
from entsoe import EntsoePandasClient

from strom import data_utils
from strom import api_utils

def get_temp_price_df():
    temp_df = data_utils.get_temp_series()
    prices_df = data_utils.get_price_series()
    temp_price_df = data_utils.join_data(temp_df, prices_df)
    return temp_price_df

# parameters estimated from https://protonsforbreakfast.wordpress.com/2022/12/19/estimating-the-heat-capacity-of-my-house/
# C_ air = 0.15*C_wall
# define an object heating_parameters

class House:
    def __init__(self, C_air=0.56, C_wall=3.5, R_interior=1.0,
                R_exterior=6.06, Q_heater=2.0, T_min=18.0, 
                T_max=24.0, T_interior_init = 18.5,
                T_wall_init = 18.5, P_base = 0.05,  freq='h'):
        
        self.C_air = C_air
        self.C_wall = C_wall
        self.R_interior = R_interior
        self.R_exterior= R_exterior
        self.Q_heater=Q_heater
        self.freq=freq
        self.T_min=T_min
        self.T_max=T_max
        self.T_interior_init = T_interior_init
        self.T_wall_init = T_wall_init
        self.P_base = P_base


import cvxpy as cp
import numpy as np

def find_heating_output(temp_price_df, house, heating_mode):
    """
    Determines the optimal heating output for a given day based on exterior temperature and electricity price,
    using explicit Euler integration for thermal dynamics.
    """
    state_df = temp_price_df.copy()  # Make a copy of the dataframe
    state_df['Price'] = temp_price_df['Price'] + house.P_base  # Add custom tolls and taxes

    if house.freq == 'min':
        state_df = state_df.resample('min').interpolate(method='cubic')
        dt = 1.0/60
    elif house.freq == 'h':
        dt = 1.0

    time_steps = len(state_df)
    T_exterior = state_df["Exterior Temperature"]
    
    # Initialize CVXPY variables
    heater_output = cp.Variable(time_steps)
    constraints = [heater_output >= 0.0, heater_output <= 1.0]
    
    # Define the state vector variable: T[0,:] = T_interior, T[1,:] = wall_temperature
    T = cp.Variable((2, time_steps))

    # Initial conditions
    constraints.append(T[0, 0] == house.T_interior_init)
    constraints.append(T[1, 0] == house.T_wall_init)

    # Define the system matrix A
    A = cp.vstack([
        [-1./(house.R_interior * house.C_air), 1./(house.R_interior * house.C_air)],
        [1./(house.R_interior * house.C_wall), -((1./house.R_interior) + (1./house.R_exterior)) / house.C_wall]
    ])

    # Dynamics constraints: For each time step, T[t+1] = T[t] + dt * (A @ T[t] + b_t)
    for t in range(time_steps - 1):
        b_t = cp.vstack([
            house.Q_heater * heater_output[t] / house.C_air,
            T_exterior.iloc[t] / (house.R_exterior * house.C_wall)
        ])
        constraints.append( T[0, t + 1] == T[0, t] + dt * (A[0,0] * T[0, t] + A[0,1] * T[1, t] + b_t[0]) )
        constraints.append( T[1, t + 1] == T[1, t] + dt * (A[1,0] * T[0, t] + A[1,1] * T[1, t] + b_t[1]) )
    
    # Minimum and maximum temperature constraint
    constraints.append(T[0, :] >= house.T_min)  # Interior temperature constraint
    constraints.append(T[0, :] <= house.T_max)  # Interior temperature constraint
    
    # Objective function
    if heating_mode == "optimal":
        obj = cp.sum(cp.multiply(state_df["Price"], dt * house.Q_heater * heater_output ))
    elif heating_mode == "baseline":
        obj = cp.sum(cp.square(house.T_min - T[0, :]))  # Interior temperature squared error
    objective = cp.Minimize(obj)
    
    # Solve optimization problem
    problem = cp.Problem(objective, constraints)
    problem.solve()

    # Check if an optimal solution was found
    if problem.status == cp.OPTIMAL:
        # Add the output to the dataframe
        state_df['Heater Output'] = heater_output.value
        state_df['Interior Temperature'] = T[0, :].value
        state_df['Wall Temperature'] = T[1, :].value
        state_df['Cost'] = state_df['Price'] * dt * state_df['Heater Output'] * house.Q_heater
    else:
        print("No optimal solution found.")
        # Fill with NaN arrays
        state_df['Heater Output'] = np.full(time_steps, np.nan)
        state_df['Interior Temperature'] = np.full(time_steps, np.nan)
        state_df['Wall Temperature'] = np.full(time_steps, np.nan)
        state_df['Cost'] = np.full(time_steps, np.nan)
    
    return state_df



def compare_output_costs(temp_price_df,house):
        
    """
    units will use kW and kWh
    """

    optimal_state_df  = find_heating_output(temp_price_df, house, "optimal")
    #baseline_state_df = find_heating_output(temp_price_df, house, "hybrid")
    baseline_state_df = find_heating_output(temp_price_df, house, "baseline")

    return optimal_state_df, baseline_state_df

def get_state_df(temp_price_df, output, house):
    
    # time steps is the length of the time index resulting from starting at the first time and going to the last time in steps of dt
    state_df = temp_price_df.copy()  # Make a copy of the dataframe
    state_df['Heater Output'] = output
    if house.freq == 'min':
        state_df = state_df.resample('min').interpolate(method='cubic')
        dt = 1.0/60
    elif house.freq == 'h':
        dt = 1.0
    
    time_steps = len(state_df)

    T_interior = np.zeros(time_steps)
    wall_temperature = np.zeros(time_steps)

    T_interior[0] = house.T_interior_init
    wall_temperature[0] = house.T_wall_init

    for t in range(time_steps - 1):
        heat_loss_air = (T_interior[t] - wall_temperature[t]) / house.R_interior
        heat_loss_wall = (wall_temperature[t] - state_df['Exterior Temperature'][t]) / house.R_exterior
        
        T_interior[t + 1] = T_interior[t] + dt * (house.Q_heater * state_df['Heater Output'][t] - heat_loss_air) / house.C_air
        wall_temperature[t + 1] = wall_temperature[t] + dt * (heat_loss_air - heat_loss_wall) / house.C_wall

    # Calculate the cost of the baseline output
    state_df['Cost'] = state_df['Price'] * dt * state_df['Heater Output'] * house.Q_heater
    state_df['Wall Temperature'] = wall_temperature
    state_df['Interior Temperature'] = T_interior

    return state_df

def plot_state(state_df, case_label, plot_price=True):
    """
    Plots the costs, temperatures, and heater output for a single case (e.g., Baseline or Optimal).
    Args:
        compare_df (pd.DataFrame): DataFrame containing the costs, temperatures, and heater output.
        case_label (str): Label for the case being plotted (e.g., 'Baseline' or 'Optimal').
    Returns:
        fig, ax1, ax2, ax3: Matplotlib figure and axes objects.
    """
    fig, ax1 = plt.subplots()

    color = 'tab:blue'
    ax1.set_xlabel('Time (h)')
    ax1.set_ylabel(f'{case_label} Cost (€)', color=color)
    ax1.plot(state_df['Cost'].cumsum(), color=color, linestyle='-')
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.tick_params(axis='x', rotation=45)  # Rotate x-axis tick labels

    ax2 = ax1.twinx()  # instantiate a second axes that shares the same x-axis

    color = 'tab:red'
    ax2.set_ylabel(f'{case_label} Interior Temperature', color=color)
    ax2.plot(state_df['Interior Temperature'], color=color, linestyle='-')
    ax2.tick_params(axis='y', labelcolor=color)

    ax3 = ax1.twinx()
    color = 'tab:green'
    ax3.spines['right'].set_position(('outward', 60))
    ax3.plot(state_df['Heater Output'], color=color, linestyle='-')
    ax3.set_ylabel(f'{case_label} Heater Output', color=color)
    ax3.tick_params(axis='y', labelcolor=color)

    if plot_price:
        ax4 = ax1.twinx()
        color = 'tab:grey'
        ax4.spines['right'].set_position(('outward', 120))
        ax4.plot(state_df['Price'], color=color, linestyle='--')
        ax4.set_ylabel('Price (€/kWh)', color=color)
        ax4.tick_params(axis='y', labelcolor=color)

    fig.tight_layout()  # otherwise the right y-label is slightly clipped
    return fig 

def plot_combined_cases(state_opt_df, state_base_df, plot_heater_output=True, plot_price=True, plot_T_exterior=True, plot_wall_temp=True):
    # Determine the number of subplots based on heater output
    fig, (ax_temp, ax_cost) = plt.subplots(2, 1, figsize=(14, 8), 
                                              gridspec_kw={'height_ratios': [3, 1]}, sharex= True)
    
    # Single temperature axis
    color = 'tab:red'
    ax_temp.set_ylabel('Temperature (°C)')
    ax_temp.plot(state_opt_df['Interior Temperature'], color=color, linestyle='-', label='Optimal Interior Temp')
    ax_temp.plot(state_base_df['Interior Temperature'], color=color, linestyle='--', label='Baseline Interior Temp')
    
    # Optional additional temperature plots
    if plot_wall_temp:
        color = 'tab:brown'
        ax_temp.plot(state_opt_df['Wall Temperature'], color=color, linestyle='-', label='Optimal Wall Temp')
        ax_temp.plot(state_base_df['Wall Temperature'], color=color, linestyle='--', label='Baseline Wall Temp')
    
    if plot_T_exterior:
        color = 'tab:pink'
        ax_temp.plot(state_opt_df['Exterior Temperature'], color=color, linestyle='-', label='Exterior Temp')

    # Always plot cost on the first axis
    color = 'tab:blue'
    ax_cost.set_xlabel('Time (h)')
    ax_cost.set_ylabel('Cost (€)', color=color)
    ax_cost.plot(state_opt_df['Cost'].cumsum(), color=color, linestyle='-')
    ax_cost.plot(state_base_df['Cost'].cumsum(), color=color, linestyle='--')
    ax_cost.tick_params(axis='y', labelcolor=color)
    ax_cost.tick_params(axis='x', rotation=45)

    # Price Axis (if needed)
    if plot_price:
        ax_price = ax_cost.twinx()
        color = 'tab:grey'
        ax_price.plot(state_opt_df['Price'], color=color)
        ax_price.set_ylabel('Price (€/kWh)', color=color)
        ax_price.tick_params(axis='y', labelcolor=color)

    # Heater Output Subplot (if plot_heater_output is True)
    if plot_heater_output:
        ax_heater = ax_cost.twinx()
        color = 'tab:green'
        ax_heater.spines["right"].set_position(("outward", 60))
        ax_heater.plot(state_opt_df['Heater Output']*100, color=color, linestyle='-', label='Optimal Heater Output')
        ax_heater.plot(state_base_df['Heater Output']*100, color=color, linestyle='--', label='Baseline Heater Output')
        ax_heater.set_ylabel('Heater Output (%)', color=color)
        ax_heater.tick_params(axis='y', labelcolor=color)

    # Legend setup
    legends_temp = [(ax_temp.get_legend_handles_labels()[1], ax_temp, 'tab:red')]
    legends_cost = [(['Optimal Cost', 'Baseline Cost'], ax_cost, 'tab:blue')]

    if plot_price:
        legends_cost.append((['Price'], ax_price, 'tab:grey'))
    
    if plot_heater_output:
        legends_cost.append((['Optimal Heater Output', 'Baseline Heater Output'], ax_heater, 'tab:green'))

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
    for i, (legend_text, ax, color) in enumerate(legends_cost):
        ax.legend(
            legend_text, 
            loc='lower left', 
            bbox_to_anchor=(0.25*i, 1.01), 
            ncol=len(legend_text),
            prop={'size': 10}
        )

    # Adjust layout
    plt.tight_layout(rect=[0, 0, 1, 0.95])  # Leave room for legends

    return fig


def plot_factor_analysis(optimal_cost,baseline_cost,
                        C_walls_list, Q_heater_list, R_external_list,
                        type):
    # Create meshgrid
    X, Y, Z = np.meshgrid(C_walls_list, Q_heater_list, R_external_list)
    if type == 'Relative':
        values = 100 * (baseline_cost - optimal_cost) / baseline_cost
        title = 'Relative Cost Savings (%)'
    elif type == 'Absolute':
        values = baseline_cost - optimal_cost
        title = 'Absolute Cost Savings (€)'


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