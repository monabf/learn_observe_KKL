# -*- coding: utf-8 -*-

# Import base utils
import copy
import pathlib
import sys

import numpy as np
import torch
from torch import nn

# In order to import learn_KKL we need to add the working dir to the system path
working_path = str(pathlib.Path().resolve())
sys.path.append(working_path)

# Import KKL observer
from learn_KKL.learner import Learner
from learn_KKL.system import QuanserQubeServo2_meas1
from learn_KKL.luenberger_observer import LuenbergerObserver
from learn_KKL.utils import RMSE
from learn_KKL.filter_utils import EKF_ODE, interpolate_func, \
    dynamics_traj_observer

# Import learner utils
import pytorch_lightning as pl
from pytorch_lightning.callbacks import ModelCheckpoint
from pytorch_lightning.loggers import TensorBoardLogger
from sklearn.model_selection import train_test_split
import torch.optim as optim
import os
import matplotlib.pyplot as plt

# Script to learn a KKL observer from simulations of the Quanser Qube 2,
# test it on experimental data, and compare with EKF.
# Quanser Qube: state (theta, alpha, thetadot, alphadot),
# measurement (theta)

# For continuous data need theta in [-pi, pi] and alpha in [0, 2pi]: only
# managed to train KKL for angles that stay in this range! Rigorously should
# take extended state (x1, x2) = (cos(theta), sin(theta)) and (x3, x4) = (
# cos(alpha), sin(alpha)) to avoid this issue and (hopefully) train on whole
# state-space. Numerical results are only local for now and data generation
# should be made more systematic and rigorous.

if __name__ == "__main__":

    TRAIN = True

    ##########################################################################
    # Setup observer #########################################################
    ##########################################################################
    # Learning method
    learning_method = "Supervised"
    num_hl = 5
    size_hl = 50
    activation = nn.ReLU()

    # Define system
    system = QuanserQubeServo2_meas1()

    # Define data params (same characteristics as experimental data)
    dt = 0.04
    tsim = (0, 8.)
    traj_data = True  # whether to generate data on grid or from trajectories
    add_forward = False
    if traj_data:
        num_initial_conditions = 1000
        x_limits = np.array(
            [[-0.5, 0.5], [-0.5, 0.5], [-0.1, 0.1], [-0.1, 0.1]])
    else:
        num_samples = int(1e5)
        x_limits = np.array(
            [[-0.5, 0.5], [0, 2 * np.pi], [-10, 10.], [-10, 10.]])
    # wc = 1.9
    wc = float(sys.argv[1]) * 0.1 + 1
    print('wc', wc)
    D = 'block_diag'  # 'block_diag'

    # Solver options
    # solver_options = {'method': 'rk4', 'options': {'step_size': 1e-3}}
    solver_options = {'method': 'dopri5'}

    if TRAIN:
        # Create the observer
        observer = LuenbergerObserver(
            dim_x=system.dim_x,
            dim_y=system.dim_y,
            method=learning_method,
            wc=wc,
            D=D,
            activation=activation,
            num_hl=num_hl,
            size_hl=size_hl,
            solver_options=solver_options
        )
        observer.set_dynamics(system)

        # Generate data
        if traj_data:
            data = observer.generate_trajectory_data(
                x_limits, num_initial_conditions, method="LHS", tsim=tsim,
                stack=False, dt=dt
            )
            data_ordered = copy.deepcopy(data)
            data = torch.cat(torch.unbind(data, dim=1), dim=0)
            if add_forward:  # add one forward trajectory to dataset
                init = torch.tensor([0., 0.1, 0., 0.] + [0.] * observer.dim_z)
                data_forward = observer.generate_data_forward(
                    init=init, tsim=(0, 8),
                    num_datapoints=200, k=10, dt=dt, stack=True)
                data = torch.cat((data, data_forward), dim=0)
        else:
            data = observer.generate_data_svl(
                x_limits, num_samples, method="LHS", k=10)
            if add_forward:  # add forward trajectory to have stable data
                init = torch.tensor([0., 0.1, 0., 0.] + [0.] * observer.dim_z)
                data_forward = observer.generate_data_forward(
                    init=init, tsim=(0, 8),
                    num_datapoints=200, k=10, dt=dt, stack=True)
                data = torch.cat((data, data_forward), dim=0)
        data, val_data = train_test_split(data, test_size=0.3, shuffle=False)

        print(data.shape)

        ##########################################################################
        # Setup learner ##########################################################
        ##########################################################################

        # Trainer options
        num_epochs = 100
        trainer_options = {"max_epochs": num_epochs}
        if traj_data:
            batch_size = 100
            init_learning_rate = 1e-3
        else:
            batch_size = 20
            init_learning_rate = 1e-3

        # Optim options
        optim_method = optim.Adam
        if traj_data:
            optimizer_options = {"weight_decay": 1e-6}
        else:
            optimizer_options = {"weight_decay": 1e-6}

        # Scheduler options
        scheduler_method = optim.lr_scheduler.ReduceLROnPlateau
        scheduler_options = {
            "mode": "min",
            "factor": 0.5,
            "patience": 5,
            "threshold": 5e-4,
            "verbose": True,
        }
        stopper = pl.callbacks.early_stopping.EarlyStopping(
            monitor="val_loss", min_delta=1e-4, patience=7, verbose=False,
            mode="min"
        )

        # Instantiate learner
        learner = Learner(
            observer=observer,
            system=system,
            training_data=data,
            validation_data=val_data,
            method='T_star',
            batch_size=batch_size,
            lr=init_learning_rate,
            optimizer=optim_method,
            optimizer_options=optimizer_options,
            scheduler=scheduler_method,
            scheduler_options=scheduler_options,
        )
        learner.traj_data = traj_data  # to keep track
        learner.x0_limits = x_limits
        learner.add_forward = add_forward
        learner.data_dt = dt
        if traj_data:
            learner.num_initial_conditions = num_initial_conditions
        else:
            learner.num_samples = num_samples

        # Define logger and checkpointing
        logger = TensorBoardLogger(save_dir=learner.results_folder + "/tb_logs")
        checkpoint_callback = ModelCheckpoint(monitor="val_loss")
        trainer = pl.Trainer(
            callbacks=[stopper, checkpoint_callback],
            **trainer_options,
            logger=logger,
            log_every_n_steps=1,
            check_val_every_n_epoch=2
        )

        # To see logger in tensorboard, copy the following output name_of_folder
        print(f"Logs stored in {learner.results_folder}/tb_logs")
        # which should be similar to jupyter_notebooks/runs/method/exp_0/tb_logs/
        # Then type this in terminal:
        # tensorboard --logdir=name_of_folder

        # Train and save results
        trainer.fit(learner)

        # To see logger in tensorboard, copy the following output name_of_folder
        print(f"Logs stored in {learner.results_folder}/tb_logs")

        # Plot training data (as trajectories)
        if traj_data:
            n = 1000
            N = data_ordered.shape[0]
            data_ordered = data_ordered[::int(np.ceil(N / n)), :, :]
            plt.plot(data_ordered[..., 0], 'x')
            plt.title(r'Training data: $\theta$')
            plt.savefig(os.path.join(learner.results_folder, 'Train_theta.pdf'))
            plt.clf()
            plt.close('all')
            plt.plot(data_ordered[..., 1], 'x')
            plt.title(r'Training data: $\alpha$')
            plt.savefig(os.path.join(learner.results_folder, 'Train_alpha.pdf'))
            plt.clf()
            plt.close('all')
            plt.plot(data_ordered[..., 2], 'x')
            plt.title(r'Training data: $\dot{\theta}$')
            plt.savefig(
                os.path.join(learner.results_folder, 'Train_thetadot.pdf'))
            plt.clf()
            plt.close('all')
            plt.plot(data_ordered[..., 3], 'x')
            plt.title(r'Training data: $\dot{\alpha}$')
            plt.savefig(
                os.path.join(learner.results_folder, 'Train_alphadot.pdf'))
            plt.clf()
            plt.close('all')

    else:
        # Load learner
        path = "runs/QuanserQubeServo2_meas1/Supervised/T_star/exp_3"
        learner_path = path + "/learner.pkl"
        import dill as pkl
        with open(learner_path, "rb") as rb_file:
            learner = pkl.load(rb_file)
        learner.results_folder = path
        observer = learner.model

    ##########################################################################
    # Generate plots #########################################################
    ##########################################################################

    # Test parameters
    dt = 0.04
    tsim = (0, 8)  # for test trajectories
    with torch.no_grad():
        learner.save_results(
            limits=x_limits, nb_trajs=10, tsim=tsim, dt=dt, fast=True,
            method='LHS',
            checkpoint_path=checkpoint_callback.best_model_path)

    ##########################################################################
    # Test trajectory ########################################################
    ##########################################################################

    # Experiment
    dt_exp = 0.004
    fileName = 'example_csv_fin4'
    filepath = 'Data/QQS2_data_diffx0/' + fileName + '.csv'
    exp_data = np.genfromtxt(filepath, delimiter=',')
    tq_exp = torch.from_numpy(exp_data[1:2001, -1] - exp_data[1, -1])
    exp_data = exp_data[1:2001, 1:-1]
    exp_data = torch.from_numpy(system.remap_hardware(exp_data))

    # Observer
    t_exp = torch.cat((tq_exp.unsqueeze(1), exp_data), dim=1)
    exp_func = interpolate_func(x=t_exp, t0=tq_exp[0], init_value=exp_data[0])
    tq = torch.arange(tsim[0], tsim[1], dt)
    exp = exp_func(tq)
    measurement = system.h(exp)
    y = torch.cat((tq.unsqueeze(1), measurement), dim=1)
    with torch.no_grad():
        estimation = observer.predict(y, tsim, dt).detach()

    # Compare both
    os.makedirs(os.path.join(learner.results_folder, fileName), exist_ok=True)
    rmse = RMSE(exp, estimation, dim=0)
    for i in range(estimation.shape[1]):
        plt.plot(tq, exp[:, i], label=rf'$x_{i + 1}$')
        plt.plot(tq, estimation[:, i], '--', label=rf'$\hat{{x}}_{i + 1}$')
        plt.title(rf'Test trajectory for $\omega_c$ = {wc:0.2g}, RMSE = '
                  rf'{rmse[i]:0.2g}')
        plt.xlabel(rf"$t$")
        plt.ylabel(rf"$x_{i + 1}$")
        plt.legend()
        plt.savefig(
            os.path.join(learner.results_folder, fileName, f'Traj{i}.pdf'),
            bbox_inches="tight"
        )
        plt.clf()
        plt.close('all')

    # Compare EKF
    x0 = exp[0].unsqueeze(0)
    dyn_config = {'prior_kwargs': {
        'n': x0.shape[1],
        'observation_matrix': torch.tensor([[1., 0., 0., 0.]]),
        'EKF_process_covar': torch.diag(torch.tensor([1e1, 1e2, 1e4, 1e4])),
        'EKF_init_covar': torch.diag(torch.tensor([1e1, 1e1, 1e1, 1e1])),
        'EKF_meas_covar': 1e-2 * torch.eye(measurement.shape[1])}}
    EKF_observer = EKF_ODE('cpu', dyn_config)
    y_func = interpolate_func(x=y, t0=tq[0], init_value=measurement[0])
    controller = lambda t, kwargs, t0, init_control, impose_init: 0.
    x0_estim = torch.cat((
        measurement[0].unsqueeze(1), torch.zeros(1, 3),
        torch.unsqueeze(torch.flatten(dyn_config['prior_kwargs'][
                                          'EKF_init_covar']), 0)), dim=1)
    xtraj = dynamics_traj_observer(
        x0=x0_estim, u=controller, y=y_func, t0=tq[0],
        dt=dt, init_control=0., version=EKF_observer, t_eval=tq, GP=system,
        kwargs=dyn_config)
    estimation_EKF = xtraj[:, :exp.shape[1]]
    rmse_EKF = RMSE(exp, estimation_EKF, dim=0)
    for i in range(estimation.shape[1]):
        plt.plot(tq, exp[:, i], label=rf'$x_{i + 1}$')
        plt.plot(tq, estimation[:, i], '--', label=rf'$\hat{{x}}_{i + 1}$')
        plt.plot(tq, estimation_EKF[:, i], '-.',
                 label=rf'$\hat{{x}}_{i + 1}^{{EKF}}$')
        plt.xlabel(rf"$t$")
        plt.ylabel(rf"$x_{i + 1}$")
        plt.title(rf'RMSE = {rmse[i]:0.2g} for KKL, RMSE = '
                  rf'{rmse_EKF[i]:0.2g} for EKF')
        plt.legend()
        plt.savefig(
            os.path.join(learner.results_folder, fileName, f'Traj_EKF{i}.pdf'),
            bbox_inches="tight"
        )
        plt.clf()
        plt.close('all')
