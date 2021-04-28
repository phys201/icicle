# model.py
# contains functions to calculate the likelihood based on a linear and quadratic model given data and parameters
import arviz as az
import matplotlib.pyplot as plt
import numpy as np
import pymc3 as pm

def calc_linear_likelihood(data, m, b):
    """
    Calculates the likelihood based on a linear model given the data and parameters (m, b)
    model: temp = slope*depth + intercept

    Parameters
    ----------
    data : pandas DataFrame
        data and metadata contained in pandas DataFrame
        Format described in tutotial notebook
    m, b : floats
        parameter values used in calculation of likelihood 

    Returns
    -------
    likelihood : double
        The likelihood for a linear model given the data and specified parameters 
    """

    # prepare data
    depth = data['Depth'].values
    temp = data['Temperature'].values
    temp_error = data['temp_errors'].values
    likelihood =  np.prod(1. / np.sqrt(2 * np.pi * temp_error ** 2) * np.exp(-(temp - m * depth - b)**2 / (2 * temp_error ** 2) ) )
    return likelihood


def calc_quad_likelihood(data, q, m, b):
    """
    Calculates the likelihood based on a quadratic model given the data and parameters (m, b)
    model: temp = q*depth^2 + m*depth + b

    Parameters
    ----------
    data : pandas DataFrame
        data and metadata contained in pandas DataFrame
        Format described in tutotial notebook
    q, m, b : floats
        parameter values used in calculation of likelihood 

    Returns
    -------
    likelihood : double
        The likelihood for a quadratic model given the data and specified parameters 
    """

    # prepare data
    depth = data['Depth'].values
    temp = data['Temperature'].values
    temp_error = data['temp_errors'].values
    likelihood =  np.prod(1. / np.sqrt(2 * np.pi * temp_error ** 2) * np.exp(-(temp - q*depth**2 - m * depth - b)**2 / (2 * temp_error ** 2) ) )
    return likelihood


def fit_quad(data):
    """
    Fits the data to a quadratic function
    Only errors on temperature are considered in this model
    Based on Hogg, Bovy, and Lang section 1 (https://arxiv.org/abs/1008.4686)
    model: temp = q*depth^2 + m*depth + b

    Parameters
    ----------
    data : pandas DataFrame
        data and metadata contained in pandas DataFrame
        Format described in tutotial notebook

    Returns
    -------
    q, m, b (parameters, 1D array of length 3), covariance matrix (3 by 3) : floats, matrix of floats
        parameters and covariance matrix from fit to quadratic function

    """

    # prepare data
    depth = data['Depth'].values
    temp = data['Temperature'].values
    sigma_y = data['temp_errors'].values

    # define quantities from HBL equation 2, 3, and 4
    Y = temp
    A = depth[:, np.newaxis] ** (0, 1, 2)
    C = np.diag(sigma_y ** 2)


    C_inv = np.linalg.inv(C)
    cov = np.linalg.inv(A.T @ C_inv @ A)
    params = cov @ (A.T @ C_inv @ Y)
    return params, cov


def fit_quad_MCMC(data, init_guess):
    """
    Fits the data to a quadratic function using pymc3
    Errors on temperature are considered in the model
    model: temp = q*depth^2 + m*depth + b
    Plots the traces in the MCMC

    Parameters
    ----------
    data : pandas DataFrame
        data and metadata contained in pandas DataFrame
        Format described in tutotial notebook
    init_guess : dict
        dictionary containing initial values for each of the parameters in the model

    Returns
    -------
    params, param_errors: 1D numpy arrays of floats
        parameter values from the model
        standard deviations of each parameter

    """
    # prepare data
    depth = data['Depth'].values
    temp = data['Temperature'].values
    sigma_y = data['temp_errors'].values

    with pm.Model() as _:
        # define priors for each parameter in the quadratic fit
        m = pm.Uniform('m', -100, 100)
        b = pm.Uniform('b', -100, 100)
        q = pm.Uniform('q', -100, 100)
        line = q * depth**2 + m * depth + b

        # define likelihood
        y_obs = pm.Normal("temp_pred", mu = line, sd = sigma_y, observed=temp)

        # unleash the inference
        n_tuning_steps = 2000
        ndraws = 2500
        traces = pm.sample(start=init_guess, tune=n_tuning_steps, draws=ndraws, chains=2) # need at least two chains to use following arviz function
        az.plot_trace(traces)

        # extract parameters and uncertainty using arviz
        params_list = []
        params_uncert = []
        for parameter in ['b', 'm', 'q']:
            params_list.append(az.summary(traces, round_to=9)['mean'][parameter])
            params_uncert.append(az.summary(traces, round_to=9)['sd'][parameter])
        
        params = np.array(params_list)
        param_errors = np.array(params_uncert)
    return params, param_errors

def fit_GPR(timetable, nosetest=False):
    '''
    Performs a Gaussian Process Regression to infer temperature v. time dependence

    Parameters
    ----------
    timetable: pandas DataFrame
        DataFrame of data and metadata for temperatures at a certain depth over a large period of time
        Incoporates the following columns: year, Temperature, prediction_errors (error on regressions from above)
    nosetest: bool
        Whether or not to perform sampling. This is useful in nosetests to make sure that the model compiles.

    Returns
    -------
    marginal_gp_model: pymc3 model
        model that will later allow us to sample and plot the posterior predictive distribution of
        temperature vs. time
    '''
    
    # data extraction
    X = timetable['year'].values[:, None]
    y = timetable['Temperature'].values
    sigma = timetable['prediction_errors'].values

    # compute mean of data
    mu = y.mean()

    with pm.Model() as marginal_gp_model:
        # prior on length scale. change prior with future iterations of model
        ls = pm.Gamma('ls', 1, 0.5)
        
        # (Vinny) can also make the noise level and mean into parameters, if
        # you want:
        #sigma = pm.HalfCauchy('sigma', 1)
        #mu = pm.Normal('mu', y.mean(), sigma)
        
        # Specify the mean and covariance functions
        cov_func = pm.gp.cov.ExpQuad(1, ls=ls)
        mean_func = pm.gp.mean.Constant(mu)

        # Specify the GP.
        gp = pm.gp.Marginal(cov_func=cov_func, mean_func=mean_func)
        
        # set the marginal likelihood based on the training data
        # and give it the noise level
        y_ = gp.marginal_likelihood("y", X=X, y=y, noise=sigma)

    # perform hyperparameter sampling (this trains our model)
    if not nosetest:
        with marginal_gp_model:
            traces = pm.sample()

        # plot posterior
        az.plot_trace(traces)
        plt.show()

        # predictions
        range_x = np.max(X) - np.min(X)
        Xnew = np.linspace(np.min(X) - 0.2*range_x, np.max(X) + 0.2*range_x, 100)[:, None]
        with marginal_gp_model:
            y_pred = gp.conditional('y_pred', Xnew)
            ppc = pm.sample_posterior_predictive(traces, var_names=['y_pred'], samples=100)

        # plot results
        plt.scatter(X, y, c='red', label='True data')
        plt.plot(Xnew, ppc['y_pred'].T, c='grey', alpha=0.1)
        plt.xlabel('Time [years]')
        plt.ylabel('Temperature [$^\\ocirc C$]')
        plt.title('Temperature vs. time\nPosterior of Gaussian Process Regression')
        plt.legend()
        plt.show()

    return marginal_gp_model

    