import numpy as np
import pandas as pd
import cvxpy as cp

# parameters estimated from https://protonsforbreakfast.wordpress.com/2022/12/19/estimating-the-heat-capacity-of-my-house/
# C_ air = 0.15*C_wall
# define an object heating_parameters

class House:
    def __init__(self, C_air=0.56, C_wall=3.5, R_interior=1.0,
                R_exterior=6.06, Q_heater=2.0, T_min=18.0, 
                T_max=24.0, T_interior_init = 18.5,
                T_wall_init = 18.5, P_base = 0.01,  freq='1h'):
        
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

def find_heating_output(temp_price_df, house, heating_mode):
    """
    Determines the optimal heating output for a given day based on exterior temperature and electricity price,
    using explicit Euler integration for thermal dynamics.
    """
    state_df = temp_price_df.copy()  # Make a copy of the dataframe
    state_df['Price'] = temp_price_df['Price'] + house.P_base  # Add custom tolls and taxes

    freq_timedelta = pd.to_timedelta(house.freq)
    dt = freq_timedelta.total_seconds() / 3600.0  # Convert to hours

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